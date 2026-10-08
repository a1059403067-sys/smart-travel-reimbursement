"""意图识别与路由（Router）

把用户输入路由到五个业务域：

    weather_ticket  天气/票务查询
    travel_apply    出差申请
    reimbursement   差旅报销
    analysis        可视化分析
    chitchat        普通闲聊

四层漏斗（参考 EduAgent api/v1/unified_chat.py 的规则前置 + LLM 路由）：

    1. 规则零 token 拦截：问候/感谢/道别/身份/功能询问直接命中 chitchat
    2. LLM Router Chain：prompt | llm | 输出 JSON {"label","reason"}
    3. 解析容错：去 markdown code fence、提取首个 {...}、非法 label 降级
    4. 兜底：LLM 不可用 / 解析失败 → chitchat（宁可闲聊，不误执行）

统一返回 RouteResult（label/reason/routed_by/fallback_used/raw），
由 api/v1/unified_chat.py 按 ROUTE_TABLE 分发到各业务域。

用法示例：

    from backend.core.llm_factory import get_llm
    from backend.core.router import IntentRouter

    router = IntentRouter(get_llm("intent"))  # temperature=0，DeepSeek，带限流包装
    result = router.route("帮我查一下明天北京到上海的高铁票")
    # result.label -> IntentLabel.WEATHER_TICKET
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

# ──────────────────────────────────────────────────────────────
# 一、类别定义
# ──────────────────────────────────────────────────────────────


class IntentLabel(StrEnum):
    """五大意图类别，值与用户需求一一对应。"""

    WEATHER_TICKET = "weather_ticket"  # [天气/票务查询]
    TRAVEL_APPLY = "travel_apply"      # [出差申请]
    REIMBURSEMENT = "reimbursement"    # [差旅报销]
    ANALYSIS = "analysis"              # [可视化分析]
    CHITCHAT = "chitchat"              # [普通闲聊]


# 分发表：统一入口（api/v1/unified_chat.py）按 label 查表路由。
# reimbursement 需上传发票文件，先回引导卡片而非直接执行；weather_ticket 由查询工具承接。
ROUTE_TABLE: dict[IntentLabel, dict[str, str]] = {
    IntentLabel.WEATHER_TICKET: {"target": "core.providers", "mode": "tool"},
    IntentLabel.TRAVEL_APPLY: {"target": "agents.travel", "mode": "agent"},
    IntentLabel.REIMBURSEMENT: {"target": "agents.reimbursement", "mode": "guide_card"},
    IntentLabel.ANALYSIS: {"target": "api.analytics", "mode": "agent"},
    IntentLabel.CHITCHAT: {"target": "templates.chitchat", "mode": "reply"},
}

# ──────────────────────────────────────────────────────────────
# 二、Prompt 模板（LLM Router Chain 的核心）
# ──────────────────────────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """你是"企业差旅管理智能助手"的意图路由模块，负责把用户的输入归类到唯一一个业务类别。

可选类别（label 只能取以下值之一）：
- weather_ticket：天气查询、车票/机票/酒店等票务与出行信息查询（只查不办）
- travel_apply：提出出差申请、安排出差行程、需要订票订酒店规划路线（办理意图）
- reimbursement：发票报销、上传发票、报销进度查询
- analysis：差旅数据统计、报表、图表、可视化分析
- chitchat：问候、感谢、道别、闲聊，或与差旅业务无关的话题

判定规则：
1. 只依据用户当前这句话判断，不联想历史对话。
2. "查票/查天气"是 weather_ticket；"我要出差/帮我订票订酒店"是 travel_apply。
3. 涉及发票、报销一律 reimbursement。
4. 要求统计/分析/图表/报表一律 analysis。
5. 寒暄与业务无关话题一律 chitchat。

输出格式：只输出一个 JSON 对象，不要输出任何其他内容，不要用 markdown 代码块包裹：
{{"label": "<类别>", "reason": "<一句话理由>"}}

示例：
输入：帮我查一下明天北京到上海的高铁票
输出：{{"label": "weather_ticket", "reason": "查询车票信息，属于票务查询"}}

输入：我下周要去杭州出差三天，帮我安排一下
输出：{{"label": "travel_apply", "reason": "提出出差申请并安排行程"}}

输入：这张住宿发票能报销吗
输出：{{"label": "reimbursement", "reason": "涉及发票报销"}}

输入：上个月我们部门差旅费花了多少，出个图
输出：{{"label": "analysis", "reason": "要求统计并可视化差旅数据"}}

输入：你好呀
输出：{{"label": "chitchat", "reason": "问候寒暄"}}"""

# ──────────────────────────────────────────────────────────────
# 三、规则层（零 token 拦截，只对整句精确匹配，避免误伤真实业务句）
# ──────────────────────────────────────────────────────────────

_CHITCHAT_GREETINGS = frozenset({
    "你好", "您好", "你好呀", "哈喽", "嗨", "hi", "hello", "hey",
    "早上好", "中午好", "下午好", "晚上好", "在吗", "在不在",
})
_CHITCHAT_THANKS = frozenset({
    "谢谢", "多谢", "感谢", "辛苦了", "thanks", "thank you", "thankyou", "3q",
})
_CHITCHAT_BYE = frozenset({
    "再见", "拜拜", "bye", "byebye", "88", "下次见", "回头见",
})
_CHITCHAT_REGEX: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"你是谁|你叫什么|你是干什么的|你是什么"), "身份询问"),
    (re.compile(r"你能做什么|你会什么|你有什么功能|能干嘛|能帮我做什么"), "功能询问"),
)


@dataclass
class RouteResult:
    """统一路由结果。routed_by: rule（规则命中）/ llm（模型判定）/ fallback（降级）。"""

    label: IntentLabel
    reason: str = ""
    routed_by: str = "rule"
    fallback_used: bool = False
    raw: dict | None = field(default=None)  # LLM 原始输出，排查用


def _extract_json(raw_text: str) -> dict | None:
    """从 LLM 输出中尽力提取 JSON dict；失败返回 None。

    容错顺序：直接解析 → 去 markdown code fence → 提取首个 {...} 片段。
    """
    text = (raw_text or "").strip()
    if not text:
        return None
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


# ──────────────────────────────────────────────────────────────
# 四、Router 本体
# ──────────────────────────────────────────────────────────────


class IntentRouter:
    """意图路由：规则层先行，LLM Router Chain 兜底判定，失败降级 chitchat。"""

    def __init__(self, llm):
        """llm: 任意 LangChain Runnable（温度设 0 保证判定稳定）。"""
        self._llm = llm
        prompt = ChatPromptTemplate.from_messages([
            ("system", ROUTER_SYSTEM_PROMPT),
            ("human", "{input}"),
        ])
        # Router Chain：prompt -> llm -> 文本输出（JSON 解析统一在 _parse_llm_output 里做，
        # 不用 JsonOutputParser，以便自己控制"解析失败降级"而不是抛异常）
        self._chain = prompt | llm | StrOutputParser()

    # ---- 同步（示例/调试用）----

    def route(self, text: str) -> RouteResult:
        if (hit := self._rule_layer(text)) is not None:
            return hit
        try:
            raw_text = self._chain.invoke({"input": text.strip()})
        except Exception as exc:
            return RouteResult(
                IntentLabel.CHITCHAT,
                reason=f"LLM 调用失败，降级闲聊：{exc}",
                routed_by="fallback", fallback_used=True,
            )
        return self._parse_llm_output(raw_text)

    # ---- 异步（FastAPI 端点用）----

    async def aroute(self, text: str) -> RouteResult:
        if (hit := self._rule_layer(text)) is not None:
            return hit
        try:
            raw_text = await self._chain.ainvoke({"input": text.strip()})
        except Exception as exc:
            return RouteResult(
                IntentLabel.CHITCHAT,
                reason=f"LLM 调用失败，降级闲聊：{exc}",
                routed_by="fallback", fallback_used=True,
            )
        return self._parse_llm_output(raw_text)

    # ---- 内部 ----

    def _rule_layer(self, text: str) -> RouteResult | None:
        """规则层：命中返回 RouteResult，否则返回 None 继续走 LLM 层。"""
        cleaned = (text or "").strip()
        if not cleaned:
            return RouteResult(IntentLabel.CHITCHAT, reason="空输入", routed_by="rule")
        lowered = cleaned.lower()
        if lowered in _CHITCHAT_GREETINGS:
            return RouteResult(IntentLabel.CHITCHAT, reason="规则命中：问候", routed_by="rule")
        if lowered in _CHITCHAT_THANKS:
            return RouteResult(IntentLabel.CHITCHAT, reason="规则命中：感谢", routed_by="rule")
        if lowered in _CHITCHAT_BYE:
            return RouteResult(IntentLabel.CHITCHAT, reason="规则命中：道别", routed_by="rule")
        for pattern, desc in _CHITCHAT_REGEX:
            if pattern.search(cleaned):
                return RouteResult(IntentLabel.CHITCHAT, reason=f"规则命中：{desc}", routed_by="rule")
        return None

    def _parse_llm_output(self, raw_text: str) -> RouteResult:
        data = _extract_json(raw_text)
        if not data:
            return RouteResult(
                IntentLabel.CHITCHAT,
                reason="LLM 输出无法解析，降级闲聊",
                routed_by="fallback", fallback_used=True,
                raw={"raw_text": raw_text},
            )
        label_value = data.get("label")
        try:
            label = IntentLabel(label_value)
        except ValueError:
            return RouteResult(
                IntentLabel.CHITCHAT,
                reason=f"非法 label（{label_value!r}），降级闲聊",
                routed_by="fallback", fallback_used=True,
                raw=data,
            )
        return RouteResult(
            label=label,
            reason=str(data.get("reason", "")),
            routed_by="llm",
            raw=data,
        )


# ──────────────────────────────────────────────────────────────
# 五、离线自测
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Windows 控制台默认 GBK，强制 UTF-8 输出，避免中文乱码
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # 1) 规则层与解析容错自测（无需真实 LLM，用 Fake 模型模拟输出）
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    fake_messages = iter([
        '```json\n{"label": "travel_apply", "reason": "测试：带 fence 的输出"}\n```',
        '这段话里夹带了 JSON：{"label": "reimbursement", "reason": "测试：文本中夹带 JSON"}',
        '{"label": "unknown_label", "reason": "测试非法 label"}',
        '服务器开小差了',
    ])
    fake_llm = GenericFakeChatModel(messages=fake_messages)
    router = IntentRouter(fake_llm)

    print("--- 规则层与解析容错自测 ---")
    for q in ["你好", "帮我查一下明天的高铁票", "我下周去杭州出差", "这张发票能报销吗", "上个月差旅费出个图"]:
        r = router.route(q)
        print(f"[{r.label.value:15s} | {r.routed_by:8s} | fallback={r.fallback_used}] {q} → {r.reason}")

    # 2) 真实路由（可选）：.env.local 已填 DEEPSEEK_API_KEY 时自动执行
    try:
        from backend.core.llm_factory import get_llm

        real_router = IntentRouter(get_llm("intent"))
    except Exception as exc:
        print(f"\n无法初始化 LLM（请在 .env.local 填写 DEEPSEEK_API_KEY）：{exc}")
    else:
        print("\n--- 真实 LLM 路由 ---")
        for q in [
            "帮我查一下明天北京到上海的高铁票",
            "我下周要去杭州出差三天，帮我安排行程",
            "这张住宿发票能报销吗",
            "上个月我们部门差旅费花了多少，出个图",
            "今天天气怎么样",
            "你好呀",
        ]:
            r = real_router.route(q)
            print(f"[{r.label.value:15s}] {q} → {r.reason}")

# 统一对话入口（架构方案模块 1：api/v1/unified_chat.py）
# backend/api/v1/unified_chat.py
#
# 统一差旅助手入口：规则前置拦截 → LLM 意图路由 → 按 label 分发 → SSE 流式返回
#
# SSE 事件帧（契约 REQ-5，前端 useSSEChat.ts 已按此实现）：
#   routing_decision  路由决策（label/reason/routed_by/fallback_used）
#   progress          Agent 流水线进度（stage 节点名 + text 中文提示）
#   token             流式文本片段（chat 闲聊 / travel summary / 票务结果全文）
#   guidance          引导卡片（reimbursement/analysis 需跳转功能页，不直接执行）
#   meta              结构化数据收尾（structured_output / fallback_used）
#   done              流结束信号
#   error             异常（detail 中文文案）
#
# 参考 EduAgent unified_chat.py：
#   - 规则前置拦截五类社交/元场景，零 Token
#   - astream_events v2 + 生成节点白名单推 token；节点开始推 progress
#   - 所有分支最终都推 done 收尾，异常转 error 帧不炸流

from __future__ import annotations

import json
import re
from datetime import date

from fastapi import APIRouter, Depends, Query
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.agents.travel.prompts import TRIP_EXTRACT_PROMPT
from backend.agents.travel.state import TripInfo
from backend.config import get_settings
from backend.core.exceptions import DataSourceError
from backend.core.llm_factory import get_llm, get_structured_llm, set_llm_user_id
from backend.core.logger import get_logger
from backend.core.orchestrator import AgentType, get_orchestrator
from backend.core.providers.train import train_search
from backend.core.providers.weather import weather_query
from backend.core.router import IntentLabel, IntentRouter, RouteResult
from backend.dependencies import get_current_user, get_db

# 契约 REQ-11：会话固定——每用户一个持续会话（多会话切换属 P1）
def _session_id_of(user_id: str) -> str:
    return f"user_{user_id}"

router = APIRouter(prefix="/api/chat", tags=["统一对话"])
logger = get_logger(__name__)


class UnifiedChatRequest(BaseModel):
    """统一对话请求体（契约 REQ-5）。"""

    session_id: str = Field(..., description="会话 ID")
    message: str = Field(..., min_length=1, max_length=2000, description="用户输入")


# ──────────────────────────────────────────────────────────────
# 一、规则前置拦截（零 Token，差旅版五类模板）
# ──────────────────────────────────────────────────────────────

_HELLO_KEYWORDS = frozenset({
    "你好", "您好", "hi", "hello", "hey", "哈喽", "嗨", "在吗", "在不在",
})
_THANKS_KEYWORDS = frozenset({
    "谢谢", "感谢", "多谢", "谢了", "辛苦了", "麻烦你了", "谢谢啦",
})
_BYE_KEYWORDS = frozenset({
    "再见", "拜拜", "88", "bye", "下次见",
})
_IDENTITY_RE = re.compile(r"你是谁|你叫什么|你是干什么的|介绍一下你自己", re.IGNORECASE)
_CAPABILITY_RE = re.compile(
    r"你能做什么|你会什么|你有什么功能|能帮我做什么|怎么用|使用说明", re.IGNORECASE
)

_REPLY_HELLO = (
    "您好！我是企业差旅管理智能助手。\n\n"
    "我可以帮您：\n"
    "- **差旅申请**：告诉我「我下周去杭州出差三天」，自动查票订酒店生成申请单\n"
    "- **票务查询**：告诉我「查明天北京到上海的高铁票」\n"
    "- **发票报销**：前往「报销」页面上传发票，自动解析生成报销单\n"
    "- **数据分析**：前往「数据分析」页面查看差旅统计报表\n\n"
    "请问有什么可以帮到您？"
)
_REPLY_THANKS = "不客气，很高兴能帮到您！还有其他差旅需求随时告诉我。"
_REPLY_BYE = "再见！祝您出行顺利，一路平安！"
_REPLY_IDENTITY = (
    "我是**企业差旅管理智能助手**，基于多智能体协作技术：\n"
    "- 差旅申请 Agent 群：需求解析、12306 查票、酒店推荐、行程规划协同\n"
    "- 发票解析 Agent：上传发票自动识别关键信息、生成报销单\n"
    "- 审批流：部门经理 → 财务两级审批\n"
    "- 数据分析：部门费用占比、月度趋势可视化"
)
_REPLY_CAPABILITY = (
    "我能为您提供：\n\n"
    "- 直接说差旅需求（如「下周一去杭州出差三天」）→ 自动安排行程并生成申请单\n"
    "- 说「查票」或「查天气」→ 快速查询\n"
    "- 发票报销 → 请前往「报销」页面上传发票\n"
    "- 统计报表 → 请前往「数据分析」页面\n\n"
    "直接告诉我您的需求即可。"
)

_STRIP_TAIL_RE = re.compile(r"[\s!！?？。~～,.，]+$")


def _pre_filter(text: str) -> str | None:
    """规则前置拦截，命中返回模板回复字符串；未命中返回 None 继续 LLM 路由。"""
    t = (text or "").strip()
    t_lower = _STRIP_TAIL_RE.sub("", t.lower())
    if t_lower in _HELLO_KEYWORDS:
        return _REPLY_HELLO
    if t_lower in _THANKS_KEYWORDS:
        return _REPLY_THANKS
    if t_lower in _BYE_KEYWORDS:
        return _REPLY_BYE
    if _IDENTITY_RE.search(t):
        return _REPLY_IDENTITY
    if _CAPABILITY_RE.search(t):
        return _REPLY_CAPABILITY
    return None


# ──────────────────────────────────────────────────────────────
# 二、引导卡片（需跳转功能页的意图）
# ──────────────────────────────────────────────────────────────

# 意图中文名（R-28：前端 routing_decision 卡片直接展示，不再显英文枚举）
_LABEL_DISPLAY = {
    IntentLabel.WEATHER_TICKET: "票务查询",
    IntentLabel.TRAVEL_APPLY: "差旅申请",
    IntentLabel.REIMBURSEMENT: "发票报销",
    IntentLabel.ANALYSIS: "数据分析",
    IntentLabel.CHITCHAT: "闲聊",
}

_GUIDANCE = {
    IntentLabel.REIMBURSEMENT: {
        "message": "检测到您需要办理发票报销。请前往「报销」页面上传发票（PDF/JPG/PNG），"
                   "系统将自动识别发票信息并生成报销单提交审批。",
        "action_label": "前往发票报销",
        "action_url": "/reimbursement",
    },
    IntentLabel.ANALYSIS: {
        "message": "检测到您需要查看差旅数据分析。请前往「数据分析」页面，"
                   "查看部门费用占比、月度趋势等统计报表。",
        "action_label": "前往数据分析",
        "action_url": "/analytics",
    },
}

# ──────────────────────────────────────────────────────────────
# 三、travel 图流式事件映射
# ──────────────────────────────────────────────────────────────

_PROGRESS_LABELS = {
    "collect_info": "正在理解您的差旅需求...",
    "weather": "正在查询目的地天气...",
    "train": "正在查询车次...",
    "hotel": "正在查询酒店...",
    "summary": "正在生成差旅申请单...",
}
# 内容节点白名单：从节点结束事件提取 AIMessage 推 token。
# - summary：申请单文案 + structured_output（关键数据由代码组装，不信 LLM 二次生成）
# - collect_info：追问文案（信息缺失走 clarify 分支时，追问必须回显给用户）
# 注：限流包装的 astream 不冒泡 on_chat_model_stream（实测），故取 on_chain_end 的节点输出整段推送
_CONTENT_NODES = {"collect_info", "summary"}


def _sse(data: dict) -> dict:
    """把 dict 包成 sse_starlette 格式；ensure_ascii=False 保留中文。"""
    return {"data": json.dumps(data, ensure_ascii=False)}


def _travel_initial_state(message: str, session_id: str, current_user: dict) -> dict:
    """首轮必须传全量 State（EduAgent 传参纪律，字段与 graph.py 自测一致）。

    session_id 入 state（R-30）：P1 挂 checkpointer 后做多轮追问记忆的 thread_id 拼接。
    """
    return {
        "messages": [HumanMessage(content=message)],
        "user_id": current_user["user_id"],
        "tenant_id": current_user["tenant_id"],
        "session_id": session_id,
        "trip_reason": "", "departure_city": "", "arrival_city": "",
        "departure_date": "", "return_date": "", "missing_fields": [],
        "weather_info": "", "train_options": [], "hotel_options": [],
        "fallback_used": False, "structured_output": None,
    }


# ──────────────────────────────────────────────────────────────
# 四、分派流生成器
# ──────────────────────────────────────────────────────────────


async def _stream_travel_agent(req: UnifiedChatRequest, current_user: dict):
    """travel_apply：astream_events v2 流式跑差旅申请图。"""
    graph = get_orchestrator().get_graph(AgentType.TRAVEL)
    if graph is None:
        yield _sse({"type": "error", "detail": "差旅申请服务暂不可用，请稍后重试"})
        return
    initial_state = _travel_initial_state(req.message, req.session_id, current_user)
    # TODO(P1): core/memory.py 挂 checkpointer 后支持多轮追问；当前每轮独立执行
    pushed_stages: set[str] = set()  # 节点嵌套链会重复报 on_chain_start，progress 去重
    summary_output: dict | None = None  # summary 节点输出，供 meta 提取结构化数据
    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            evt = event["event"]
            node = event.get("metadata", {}).get("langgraph_node", "")
            if evt == "on_chain_start" and node in _PROGRESS_LABELS and node not in pushed_stages:
                pushed_stages.add(node)
                yield _sse({"type": "progress", "stage": node, "text": _PROGRESS_LABELS[node]})
            elif evt == "on_chain_end" and node in _CONTENT_NODES:
                # 节点返回 dict：messages 增量含 AIMessage（追问文案 / 申请单全文）
                # 注意：节点内嵌套链（with_structured_output 等）的 on_chain_end 也带同一
                # node 名，但其 output 是链产物（如 TripInfo 对象）而非 dict——类型过滤跳过
                output = event["data"].get("output")
                if not isinstance(output, dict):
                    continue
                msgs = output.get("messages") or []
                if msgs and msgs[-1].content:
                    yield _sse({"type": "token", "content": msgs[-1].content})
                if node == "summary":
                    summary_output = output
    except Exception as exc:
        logger.error("unified_chat.travel_stream_error", error=str(exc), exc_info=True)
        yield _sse({"type": "error", "detail": "差旅申请服务异常，请稍后重试"})
        return

    logger.info("unified_chat.travel_done", user_id=current_user["user_id"])
    yield _sse({
        "type": "meta",
        "structured_output": (summary_output or {}).get("structured_output"),
        "fallback_used": bool((summary_output or {}).get("fallback_used", False)),
    })


async def _stream_weather_ticket(req: UnifiedChatRequest, current_user: dict):
    """weather_ticket：结构化提取出发/到达/日期 → Mock 车次/天气查询 → 文本回复。"""
    # ① 结构化提取（temperature=0 + function_calling）
    try:
        sllm = get_structured_llm("travel", TripInfo)
        info: TripInfo = await sllm.ainvoke(
            TRIP_EXTRACT_PROMPT.format(today=date.today().isoformat(), input=req.message)
        )
    except Exception as exc:
        logger.warning("unified_chat.ticket_extract_failed", error=str(exc))
        yield _sse({"type": "error", "detail": "没太理解您的查询，请说清楚出发地、目的地和日期"})
        return

    if not info.departure_city or not info.arrival_city or not info.departure_date:
        yield _sse({"type": "token",
                    "content": "请告诉我完整的查询信息：出发城市、目的地城市、出发日期（如「查明天北京到上海的高铁票」）。"})
        return

    # ② 车次查询（Mock；失败静默降级）
    try:
        trains = await train_search(info.departure_city, info.arrival_city, info.departure_date)
    except DataSourceError as exc:
        logger.warning("unified_chat.ticket_train_failed", error=str(exc))
        trains = []

    # ③ 天气查询（失败静默降级）
    weather_text = "天气数据暂不可用"
    try:
        w = await weather_query(info.arrival_city, info.departure_date)
        weather_text = f"{w['city']} {w['date']}：{w['weather']}，{w['temperature']}"
    except DataSourceError as exc:
        logger.warning("unified_chat.ticket_weather_failed", error=str(exc))

    # ④ 组装回复文本（数据直接引用 provider 结果）
    if trains:
        lines = [f"{info.departure_city} → {info.arrival_city}（{info.departure_date}）查到 {len(trains)} 个车次："]
        for t in trains[:3]:
            lines.append(f"- {t['train_no']}：{t['departure']} 开，{t['arrive']} 到，二等座 {t['price_second']}，余票 {t['seats_left']} 张")
        lines.append(f"目的地天气：{weather_text}")
        lines.append("如需预订行程，请直接告诉我您的出差安排（如「帮我订票安排行程」）。")
        content = "\n".join(lines)
        structured = {
            "train_options": trains[:3],
            "weather": weather_text,
            "query": {
                "departure_city": info.departure_city,
                "arrival_city": info.arrival_city,
                "departure_date": info.departure_date,
            },
        }
    else:
        content = f"抱歉，{info.departure_city} → {info.arrival_city}（{info.departure_date}）暂未查到车次，请人工核验或换个日期试试。"
        structured = {"train_options": [], "query": None}

    yield _sse({"type": "token", "content": content})
    yield _sse({"type": "meta", "structured_output": structured, "fallback_used": False})


async def _stream_chitchat(req: UnifiedChatRequest, current_user: dict):
    """chitchat（LLM 路由判定）：get_llm('chat') 流式闲聊。"""
    llm = get_llm("chat")
    try:
        async for chunk in llm.astream(req.message):
            if chunk.content:
                yield _sse({"type": "token", "content": chunk.content})
    except Exception as exc:
        logger.warning("unified_chat.chitchat_failed", error=str(exc))
        yield _sse({"type": "error", "detail": "抱歉，我暂时无法处理您的请求，请稍后再试。"})


# ──────────────────────────────────────────────────────────────
# 五、SSE 端点
# ──────────────────────────────────────────────────────────────


@router.post("", summary="统一对话入口（意图路由 + SSE 流式，流结束落库历史）")
async def unified_chat(
    req: UnifiedChatRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /api/chat（契约 REQ-5）。

    流结束前按契约 REQ-11 落库历史：user 消息 + assistant 最终回复
    （token 累积文本 + guidance 卡片数组）；落库失败只记日志，不影响流。
    会话固定：session_id = user_{user_id}（前端传参忽略，多会话 P1 再做）。
    """
    set_llm_user_id(current_user["user_id"])  # 限流身份注入（子 task 自动继承）

    async def event_generator():
        # ── 帧累积（REQ-11 落库原料；子流透传帧也经 _collect 归集）──
        collected_content: list[str] = []
        collected_guidance: list[dict] = []
        error_detail: str | None = None

        def _collect(data: dict) -> None:
            nonlocal error_detail
            t = data.get("type")
            if t == "token":
                collected_content.append(data.get("content", ""))
            elif t == "guidance":
                collected_guidance.append({
                    "message": data.get("message", ""),
                    "action_label": data.get("action_label", ""),
                    "action_url": data.get("action_url", ""),
                })
            elif t == "error":
                error_detail = data.get("detail", "")

        async def _persist() -> None:
            """落库本轮对话；失败只记日志，绝不打断 SSE 流（对话主链路优先）。"""
            try:
                sid = _session_id_of(current_user["user_id"])
                uid = int(current_user["user_id"])
                await db.execute(text(
                    "INSERT INTO chat_messages (user_id, session_id, role, content) "
                    "VALUES (:uid, :sid, 'user', :content)"
                ), {"uid": uid, "sid": sid, "content": req.message})
                assistant_content = "".join(collected_content)
                if error_detail and not assistant_content:
                    assistant_content = error_detail
                await db.execute(text(
                    "INSERT INTO chat_messages (user_id, session_id, role, content, guidance) "
                    "VALUES (:uid, :sid, 'assistant', :content, :guidance)"
                ), {
                    "uid": uid, "sid": sid, "content": assistant_content,
                    "guidance": json.dumps(collected_guidance, ensure_ascii=False)
                    if collected_guidance else None,
                })
                await db.commit()
            except Exception as exc:
                await db.rollback()
                logger.warning("unified_chat.persist_failed", error=str(exc))

        def _emit(data: dict) -> dict:
            """累积帧（供落库）+ 包装为 sse 格式；同步函数，勿改 async。"""
            _collect(data)
            return _sse(data)

        # ── Step 0：规则前置拦截（零 Token 模板回复）──
        pre_reply = _pre_filter(req.message)
        if pre_reply is not None:
            yield _emit({"type": "token", "content": pre_reply})
            await _persist()
            yield _sse({"type": "done"})
            return

        # ── Step 1：LLM 路由（失败已在 router 内部降级 chitchat）──
        result: RouteResult = await IntentRouter(get_llm("intent")).aroute(req.message)
        logger.info("unified_chat.routed", user_id=current_user["user_id"],
                    label=result.label.value, routed_by=result.routed_by)

        # ── Step 2：推送路由决策帧（前端显示"已转接 XX"）──
        yield _emit({
            "type": "routing_decision",
            "label": result.label.value,
            "label_display": _LABEL_DISPLAY.get(result.label, result.label.value),
            "reason": result.reason,
            "routed_by": result.routed_by,
            "fallback_used": result.fallback_used,
        })

        # ── Step 3：按 label 分发（子流透传帧先经 _collect 归集再推送）──
        if result.label == IntentLabel.TRAVEL_APPLY:
            async for event in _stream_travel_agent(req, current_user):
                _collect(json.loads(event["data"]))
                yield event
        elif result.label == IntentLabel.WEATHER_TICKET:
            async for event in _stream_weather_ticket(req, current_user):
                _collect(json.loads(event["data"]))
                yield event
        elif result.label == IntentLabel.CHITCHAT:
            async for event in _stream_chitchat(req, current_user):
                _collect(json.loads(event["data"]))
                yield event
        elif result.label in _GUIDANCE:
            guidance = _GUIDANCE[result.label]
            yield _emit({
                "type": "guidance",
                "message": guidance["message"],
                "action_label": guidance["action_label"],
                "action_url": guidance["action_url"],
            })
        else:  # 理论不可达（router 保证 label 合法）；防御性兜底
            yield _emit({"type": "error", "detail": "无法识别您的请求，请换个说法试试。"})

        await _persist()
        yield _sse({"type": "done"})

    return EventSourceResponse(event_generator())


@router.get("/history", summary="对话历史（契约 REQ-11：before_id 游标分页）")
async def chat_history(
    limit: int = Query(default=3, ge=1, le=50, description="返回条数（消息条数，默认 3）"),
    before_id: int | None = Query(default=None, ge=1, description="游标：返回 id < before_id 的更早消息；缺省最新"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """按 id 倒序取 limit+1 判 has_more，再翻转为升序（旧→新）返回，前端直接追加渲染。"""
    sid = _session_id_of(current_user["user_id"])
    uid = int(current_user["user_id"])
    cond = "AND id < :before_id" if before_id else ""
    params: dict = {"uid": uid, "sid": sid, "limit": limit + 1}
    if before_id:
        params["before_id"] = before_id

    rows = (await db.execute(text(
        f"""
        SELECT id, role, content, guidance, created_at
        FROM chat_messages
        WHERE user_id = :uid AND session_id = :sid {cond}
        ORDER BY id DESC
        LIMIT :limit
        """
    ), params)).all()

    has_more = len(rows) > limit
    rows = list(reversed(rows[:limit]))  # 升序：旧→新
    items = [
        {
            "id": int(r.id),
            "role": r.role,
            "content": r.content or "",
            "guidance": r.guidance,  # JSONB 自动反序列化为 list/dict 或 None
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]
    logger.info("unified_chat.history_queried", user_id=current_user["user_id"],
                count=len(items), has_more=has_more)
    return {"items": items, "has_more": has_more}


if __name__ == "__main__":
    # 离线自测：真实 LLM + Mock 数据源，6 个场景校验事件帧序列
    # 前提：.env.local 已填 DEEPSEEK_API_KEY；DB 不需要（纯对话链路）
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    async def _read_sse(resp) -> list[dict]:
        """解析 SSE 响应为 [{"event": str, "data": dict}] 列表。

        sse_starlette 3.x 输出 `data: {"type": ...}` 行（无 event: 行），
        事件类型在 data JSON 的 type 字段（前端 useSSEChat.ts 已兼容）。
        """
        events = []
        async for line in resp.aiter_lines():
            line = line.strip()
            if line.startswith("data: "):
                data = json.loads(line[6:])
                events.append({"event": data.get("type", ""), "data": data})
        return events

    async def main():
        import httpx

        from backend.db.migrations import run_migrations
        from backend.main import app

        # 建表（幂等）：历史场景依赖 chat_messages 表（REQ-11）
        await run_migrations()

        # 登录拿 token（种子账号，需 PG 可用；仅对话接口需要 JWT）
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": "zhangwei", "password": "Employee@123456"})
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            async def chat(message: str) -> list[dict]:
                async with client.stream("POST", "/api/chat",
                                         json={"session_id": "s_test", "message": message},
                                         headers=headers) as resp:
                    assert resp.status_code == 200, f"HTTP {resp.status_code}"
                    return await _read_sse(resp)

            # 场景 1：问候 → 规则拦截（无 routing_decision，直接 token+done）
            evs = await chat("你好")
            types = [e["event"] for e in evs]
            print(f"[1 问候] 帧序列={types}")
            assert types == ["token", "done"] and "差旅管理智能助手" in evs[0]["data"]["content"]

            # 场景 2：查票 → weather_ticket + 工具查询结果
            evs = await chat("帮我查一下明天北京到上海的高铁票")
            types = [e["event"] for e in evs]
            rd = evs[0]["data"]
            print(f"[2 查票] label={rd['label']} 帧={types}")
            assert types[0] == "routing_decision" and rd["label"] == "weather_ticket"
            assert any(e["event"] == "token" and "车次" in e["data"]["content"] for e in evs)
            assert types[-1] == "done"

            # 场景 3：出差申请 → travel_apply 走 Agent 流（progress + token + meta）
            # 消息必须含事由/出发/到达/日期，否则 collect_info 按设计走追问分支（不调后续节点）
            evs = await chat("我下周一要从北京去杭州出差拜访客户，周三回来，帮我安排行程")
            rd = evs[0]["data"]
            types = [e["event"] for e in evs]
            print(f"[3 出差] label={rd['label']} 帧={types}")
            assert rd["label"] == "travel_apply"
            assert "progress" in types and "token" in types and "meta" in types and types[-1] == "done"

            # 场景 4：发票报销 → guidance 引导卡片
            evs = await chat("这张住宿发票能报销吗")
            rd = evs[0]["data"]
            print(f"[4 报销] label={rd['label']} 帧={[e['event'] for e in evs]}")
            assert rd["label"] == "reimbursement"
            assert any(e["event"] == "guidance" and e["data"]["action_url"] == "/reimbursement" for e in evs)

            # 场景 5：数据分析 → guidance 引导卡片
            evs = await chat("上个月我们部门差旅费花了多少，出个图")
            rd = evs[0]["data"]
            print(f"[5 分析] label={rd['label']} 帧={[e['event'] for e in evs]}")
            assert rd["label"] == "analysis"
            assert any(e["event"] == "guidance" and e["data"]["action_url"] == "/analytics" for e in evs)

            # 场景 6：闲聊 → chitchat LLM 流式回复
            evs = await chat("给我讲一个关于出差的笑话")
            rd = evs[0]["data"]
            print(f"[6 闲聊] label={rd['label']} 帧={[e['event'] for e in evs]}")
            assert rd["label"] == "chitchat" and any(e["event"] == "token" for e in evs)

            # 场景 7：无 Token → 401
            async with client.stream("POST", "/api/chat",
                                     json={"session_id": "s_test", "message": "你好"}) as resp:
                print(f"[7 无Token] HTTP {resp.status_code}")
                assert resp.status_code == 401

            # ── 对话历史场景（REQ-11，A-17）──
            from backend.dependencies import AsyncSessionLocal
            from sqlalchemy import text as sql_text

            # 幂等清理：删测试用户历史（保证重复运行断言一致）
            async with AsyncSessionLocal() as db:
                await db.execute(sql_text(
                    "DELETE FROM chat_messages WHERE user_id = "
                    "(SELECT id FROM users WHERE username = 'zhangwei')"
                ))
                await db.commit()

            # 8) 发"你好"（规则拦截）→ 落库 user+assistant 两条
            await chat("你好")
            r = await client.get("/api/chat/history", headers=headers)
            h = r.json()
            assert len(h["items"]) == 2 and h["items"][0]["role"] == "user" and h["items"][0]["content"] == "你好"
            assert h["items"][1]["role"] == "assistant" and "差旅管理智能助手" in h["items"][1]["content"]
            print(f"[8 落库] {r.status_code} 2 条（user+assistant），升序旧→新")

            # 9) 发发票问题（guidance 卡片）→ assistant 历史含 guidance 数组
            await chat("这张发票能报销吗")
            r = await client.get("/api/chat/history?limit=10", headers=headers)
            h = r.json()
            assert len(h["items"]) == 4
            last = h["items"][-1]
            assert last["role"] == "assistant" and last["guidance"]
            assert last["guidance"][0]["action_url"] == "/reimbursement"
            print(f"[9 guidance 落库] {r.status_code} 最新一轮 guidance={last['guidance'][0]['action_label']}")

            # 10) 游标分页：limit=3 取最新 3 条 + has_more；before_id 翻到更早 1 条
            r = await client.get("/api/chat/history", headers=headers)
            h = r.json()
            assert len(h["items"]) == 3 and h["has_more"] is True
            oldest_id = h["items"][0]["id"]
            r = await client.get(f"/api/chat/history?before_id={oldest_id}", headers=headers)
            h2 = r.json()
            assert len(h2["items"]) == 1 and h2["items"][0]["content"] == "你好" and h2["has_more"] is False
            print(f"[10 游标翻页] 最新3条 has_more=True；before_id 翻到最早 1 条（你好）has_more=False")

            # 11) 无 Token → 401
            r = await client.get("/api/chat/history")
            assert r.status_code == 401
            print(f"[11 无Token] {r.status_code}")

            print("\n断言通过 ✅：统一对话 SSE + 对话历史（REQ-11 落库/分页/翻页）全部正常")

    asyncio.run(main())

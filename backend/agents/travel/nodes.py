"""出差申请工作流节点实现。

节点约定（参考 EduAgent）：
- async def xxx_node(state) -> dict，只返回增量字段
- 外部依赖（天气/票务/酒店）失败一律静默降级，绝不阻断主流程
- 结构化提取用 get_structured_llm（function_calling），失败有兜底默认值
"""

from __future__ import annotations

from datetime import date

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from backend.agents.travel.prompts import PLAN_SUMMARY_PROMPT, TRIP_EXTRACT_PROMPT
from backend.agents.travel.state import TravelState, TripInfo
from backend.core.exceptions import DataSourceError
from backend.core.llm_factory import get_llm, get_structured_llm
from backend.core.logger import get_logger
from backend.core.providers.hotel import hotel_search
from backend.core.providers.train import train_search
from backend.core.providers.weather import weather_query

logger = get_logger(__name__)

# 收集信息阶段的必填字段（返程日期可选）
REQUIRED_FIELDS = ["trip_reason", "departure_city", "arrival_city", "departure_date"]
_FIELD_LABELS = {
    "trip_reason": "出差事由",
    "departure_city": "出发城市",
    "arrival_city": "目的地城市",
    "departure_date": "出发日期",
    "return_date": "返程日期",
}


def _last_user_text(state: TravelState) -> str:
    """取最近一条用户消息文本。"""
    for m in reversed(state.get("messages", [])):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            return m.content
    return ""


# ──────────────────────────────────────────────────────────────
# 节点 1：收集信息（事由/时间/地点）
# ──────────────────────────────────────────────────────────────


async def collect_info_node(state: TravelState) -> dict:
    """用结构化 LLM 提取差旅信息；缺失必填字段时追问，不继续走流程。"""
    user_text = _last_user_text(state)
    try:
        llm = get_structured_llm("travel", TripInfo)
        prompt = TRIP_EXTRACT_PROMPT.format(today=date.today().isoformat(), input=user_text)
        info: TripInfo = await llm.ainvoke(prompt)
    except Exception as exc:
        # 提取失败：不阻断，走统一追问
        logger.warning("travel.collect_info_failed", error=str(exc))
        return {
            "missing_fields": REQUIRED_FIELDS,
            "messages": [AIMessage(content="抱歉，我没理解您的出差需求，请告诉我：出差事由、出发城市、目的地城市和出发日期。")],
        }

    update = {
        field: getattr(info, field, "") or ""
        for field in ("trip_reason", "departure_city", "arrival_city", "departure_date", "return_date")
    }
    missing = [f for f in REQUIRED_FIELDS if not update.get(f)]
    if missing:
        labels = "、".join(_FIELD_LABELS[f] for f in missing)
        update["missing_fields"] = missing
        update["messages"] = [AIMessage(content=f"为了帮您安排出差，还需要补充：{labels}。请告诉我。")]
    return update


# ──────────────────────────────────────────────────────────────
# 节点 2：调用天气 API
# ──────────────────────────────────────────────────────────────


async def weather_node(state: TravelState) -> dict:
    """查询目的地天气；失败静默降级，不阻断主流程。"""
    try:
        info = await weather_query(state["arrival_city"], state["departure_date"])
        text = f"{info['city']} {info['date']}：{info['weather']}，{info['temperature']}"
        if info.get("advice"):
            text += f"（{info['advice']}）"
        return {"weather_info": text}
    except DataSourceError as exc:
        logger.warning("travel.weather_failed", error=str(exc))
        return {"weather_info": "天气数据暂不可用"}


# ──────────────────────────────────────────────────────────────
# 节点 3：调用 12306 查询工具（Mock，禁用爬虫）
# ──────────────────────────────────────────────────────────────


async def train_search_node(state: TravelState) -> dict:
    """查询车次；失败静默降级为空列表（汇总节点会提示人工查询）。"""
    try:
        options = await train_search(state["departure_city"], state["arrival_city"], state["departure_date"])
    except DataSourceError as exc:
        logger.warning("travel.train_failed", error=str(exc))
        return {"train_options": []}
    return {"train_options": options[:3]}  # 只保留前 3 个车次


# ──────────────────────────────────────────────────────────────
# 节点 4：推荐酒店
# ──────────────────────────────────────────────────────────────


async def hotel_recommend_node(state: TravelState) -> dict:
    """查询目的地酒店；失败静默降级为空列表。"""
    try:
        options = await hotel_search(state["arrival_city"], state["departure_date"])
    except DataSourceError as exc:
        logger.warning("travel.hotel_failed", error=str(exc))
        return {"hotel_options": []}
    return {"hotel_options": options}


# ──────────────────────────────────────────────────────────────
# 节点 5：申请单汇总（收尾）
# ──────────────────────────────────────────────────────────────


def _format_trains(options: list[dict]) -> str:
    if not options:
        return "暂无车次信息，请人工查询"
    lines = [
        f"{t['train_no']}：{t['departure']} 开，{t['arrive']} 到（历时 {t['duration']}），二等座 {t['price_second']}，余票 {t['seats_left']} 张"
        for t in options
    ]
    return "\n".join(lines)


def _format_hotels(options: list[dict]) -> str:
    if not options:
        return "暂无酒店信息，请人工查询"
    lines = [
        f"{h['name']}：¥{h['price']}/晚，评分 {h['rating']}，{h['distance']}，{h['breakfast']}"
        for h in options
    ]
    return "\n".join(lines)


async def plan_summary_node(state: TravelState) -> dict:
    """汇总生成《差旅申请单》草稿。

    关键数据（车次/酒店）来自 provider 结果直接引用，不信 LLM 二次生成——
    结构化出口由代码组装，LLM 只负责组织文案。
    """
    trains = state.get("train_options", [])
    hotels = state.get("hotel_options", [])
    return_suffix = f"，{state['return_date']} 返程" if state.get("return_date") else ""

    prompt = PLAN_SUMMARY_PROMPT.format(
        reason=state.get("trip_reason", ""),
        departure_city=state.get("departure_city", ""),
        arrival_city=state.get("arrival_city", ""),
        departure_date=state.get("departure_date", ""),
        return_suffix=return_suffix,
        weather=state.get("weather_info", "暂无"),
        trains=_format_trains(trains),
        hotels=_format_hotels(hotels),
    )
    try:
        # astream 流式拼接：unified_chat 的 astream_events 依赖流式事件推 token（ainvoke 无 stream 事件）
        summary = ""
        async for chunk in get_llm("travel").astream(prompt):
            if chunk.content:
                summary += chunk.content
    except Exception as exc:
        logger.warning("travel.summary_failed", error=str(exc))
        summary = "申请单生成失败，请稍后重试或联系管理员人工处理。"

    structured = {
        "summary": summary,
        "trip": {
            "trip_reason": state.get("trip_reason", ""),
            "departure_city": state.get("departure_city", ""),
            "arrival_city": state.get("arrival_city", ""),
            "departure_date": state.get("departure_date", ""),
            "return_date": state.get("return_date", ""),
        },
        "train_options": trains,
        "hotel_options": hotels,
        "weather_info": state.get("weather_info", ""),
    }
    return {"structured_output": structured, "messages": [AIMessage(content=summary)]}

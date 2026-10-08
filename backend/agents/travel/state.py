"""出差申请工作流 State 定义。

约定（参考 EduAgent 四文件模板）：
- 首部：messages + user_id/tenant_id/session_id 三件套（编排层注入，节点只读）
- 中间：按数据流阶段分组，顺序与图执行顺序一致
- 尾部：fallback_used + structured_output 统一收尾字段（编排层/API 读取的对外出口）
- 唯一 reducer 是 add_messages，其余字段默认覆盖语义
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class TripInfo(BaseModel):
    """LLM 结构化输出目标：从用户输入提取的差旅信息。"""

    trip_reason: str = Field(default="", description="出差事由，如拜访客户/参加会议")
    departure_city: str = Field(default="", description="出发城市")
    arrival_city: str = Field(default="", description="目的地城市")
    departure_date: str = Field(default="", description="出发日期 YYYY-MM-DD")
    return_date: str = Field(default="", description="返程日期 YYYY-MM-DD，未提及留空")


class TravelState(TypedDict):
    # ── ① 请求上下文 ──
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    tenant_id: str
    session_id: str

    # ── ② 收集信息（collect_info 节点产出）──
    trip_reason: str
    departure_city: str
    arrival_city: str
    departure_date: str
    return_date: str
    missing_fields: list[str]

    # ── ③ 中间结果（天气/车次/酒店）──
    weather_info: str
    train_options: list[dict]
    hotel_options: list[dict]

    # ── ④ 最终结果 ──
    fallback_used: bool
    structured_output: dict | None


if __name__ == "__main__":
    # 离线自测：校验 State 必填键与 Pydantic 模型
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    keys = list(TravelState.__annotations__)
    print(f"[State] 共 {len(keys)} 个字段: {keys}")
    sample = TripInfo(
        trip_reason="拜访客户", departure_city="北京", arrival_city="杭州",
        departure_date="2026-10-12", return_date="2026-10-14",
    )
    print(f"[TripInfo] {sample.model_dump()}")
    empty = TripInfo()
    print(f"[TripInfo 空实例] {empty.model_dump()}")

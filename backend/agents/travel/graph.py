"""出差申请工作流 Graph 定义。

拓扑（直线 + 一个条件边）：

    START → collect_info ─┬─(信息齐全)→ weather → train → hotel → summary → END
                          └─(缺失字段)→ END（追问，等待用户补充）

约定（参考 EduAgent graph.py）：
- 路由函数是模块级纯函数，读 state.get() 返回目标节点名
- build 工厂返回 compile 后的图；标签到节点的映射显式写在 add_conditional_edges
- 多轮追问需要 checkpointer，待 core/memory.py 完成后挂上（接口不变，调用方无感）
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from backend.agents.travel.nodes import (
    collect_info_node,
    hotel_recommend_node,
    plan_summary_node,
    train_search_node,
    weather_node,
)
from backend.agents.travel.state import TravelState


def _route_after_collect(state: TravelState) -> str:
    """收集信息后的出口路由：有缺失字段 → 追问结束；齐全 → 继续流程。"""
    if state.get("missing_fields"):
        return "clarify"
    return "weather"


def build_travel_graph():
    builder = StateGraph(TravelState)
    builder.add_node("collect_info", collect_info_node)
    builder.add_node("weather", weather_node)
    builder.add_node("train", train_search_node)
    builder.add_node("hotel", hotel_recommend_node)
    builder.add_node("summary", plan_summary_node)

    builder.add_edge(START, "collect_info")
    builder.add_conditional_edges(
        "collect_info",
        _route_after_collect,
        {"weather": "weather", "clarify": END},
    )
    builder.add_edge("weather", "train")
    builder.add_edge("train", "hotel")
    builder.add_edge("hotel", "summary")
    builder.add_edge("summary", END)
    return builder.compile()


if __name__ == "__main__":
    # 离线自测：跑通完整流程（真实 LLM + Mock 数据源）
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    def _initial_state(message: str) -> dict:
        """首轮必须传全量 State（EduAgent 传参纪律）。"""
        return {
            "messages": [("user", message)],
            "user_id": "u_test", "tenant_id": "tenant_default", "session_id": "s_test",
            "trip_reason": "", "departure_city": "", "arrival_city": "",
            "departure_date": "", "return_date": "", "missing_fields": [],
            "weather_info": "", "train_options": [], "hotel_options": [],
            "fallback_used": False, "structured_output": None,
        }

    async def main():
        graph = build_travel_graph()
        print("已编译节点:", [n for n in graph.get_graph().nodes])

        # 场景 1：信息完整 → 走全流程
        print("\n" + "=" * 60)
        print("场景 1：信息完整（真实 LLM 提取 + Mock 票务/天气/酒店）")
        print("=" * 60)
        result = await graph.ainvoke(_initial_state("我下周一要从北京去杭州出差拜访客户，周三回来"))
        print(result["messages"][-1].content)

        # 场景 2：信息缺失 → 追问
        print("\n" + "=" * 60)
        print("场景 2：信息缺失（应追问，不调后续节点）")
        print("=" * 60)
        result2 = await graph.ainvoke(_initial_state("我要出差"))
        print(result2["messages"][-1].content)
        print("缺失字段:", result2["missing_fields"])
        print("车次结果为空（未执行）:", result2["train_options"] == [])

    asyncio.run(main())

# Agent 编排边界（参考 EduAgent core/orchestrator.py）
# backend/core/orchestrator.py
#
# 职责（架构方案模块 2 三件套）：
#   1. 图懒加载注册表：AgentType → build 工厂，首次访问才编译（避免启动全量编译）
#   2. 实例缓存单例：get_orchestrator() 全局唯一，图只 build 一次
#   3. 永不抛异常：未注册类型返回 None，由调用方（unified_chat）降级处理，
#      编排层本身不对业务调用方抛错
#
# 用法：
#
#     from backend.core.orchestrator import AgentType, get_orchestrator
#
#     graph = get_orchestrator().get_graph(AgentType.TRAVEL)  # 不存在返回 None
from __future__ import annotations

from enum import StrEnum

from backend.agents.travel.graph import build_travel_graph
from backend.core.logger import get_logger

logger = get_logger(__name__)


class AgentType(StrEnum):
    """对话图类型标识。

    REIMBURSEMENT 不走对话图：发票解析需上传文件，
    对外入口是 agents/reimbursement/graph.py 的 parse_invoice_file（REQ-7 上传 API 调用），
    统一对话入口只回引导卡片。
    """

    TRAVEL = "travel"  # 差旅申请 Agent 群（collect_info → weather → train → hotel → summary）


# ──────────────────────────────────────────────────────────────
# 图懒加载注册表：新 Agent 在此登记（build 工厂，不编译）
# ──────────────────────────────────────────────────────────────

_GRAPH_BUILDERS = {
    AgentType.TRAVEL: build_travel_graph,
}


class AgentOrchestrator:
    """编排器：懒加载 + 缓存 + 永不抛异常。"""

    def __init__(self) -> None:
        self._graphs: dict[AgentType, object] = {}

    def get_graph(self, agent_type: AgentType):
        """取编译后的图；未注册类型返回 None（调用方降级，不抛错）。"""
        if agent_type in self._graphs:
            return self._graphs[agent_type]
        builder = _GRAPH_BUILDERS.get(agent_type)
        if builder is None:
            logger.warning("orchestrator.unknown_agent_type", agent_type=str(agent_type))
            return None
        graph = builder()
        self._graphs[agent_type] = graph
        return graph


_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    """全局单例（EduAgent 同款）。"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


if __name__ == "__main__":
    # 离线自测：懒加载 + 缓存 + 未知类型返回 None
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    orch = get_orchestrator()
    g1 = orch.get_graph(AgentType.TRAVEL)
    g2 = orch.get_graph(AgentType.TRAVEL)
    print(f"[懒加载] TRAVEL 图节点: {[n for n in g1.get_graph().nodes][:3]}...")
    print(f"[缓存] 同类型两次获取同一实例: {g1 is g2}")
    print(f"[不抛错] 未注册类型返回 None: {orch.get_graph(AgentType('nonexistent')) is None}")

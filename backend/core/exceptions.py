"""异常体系：一个基类 + 扁平子类。

设计（参考 EduAgent core/exceptions.py）：

- 基类携带 agent_type（哪个 Agent 出错）与 details（上下文字典）
- 可重试与否不写在类里：在 core/retry.py 用 RETRYABLE_ERRORS / NON_RETRYABLE_ERRORS
  两个 tuple 统一分类——新增异常只需决定归哪一组，不动类定义
"""

from __future__ import annotations


class TravelBaseError(Exception):
    """业务异常基类。"""

    def __init__(
        self,
        message: str,
        *,
        agent_type: str | None = None,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.agent_type = agent_type
        self.details = details or {}


class LLMAPIError(TravelBaseError):
    """LLM 服务调用失败（超时/限流/服务端错误）。"""


class DataSourceError(TravelBaseError):
    """外部数据源（票务/酒店/地图）调用失败，通常应静默降级。"""


class AgentExecutionError(TravelBaseError):
    """Agent 图执行失败。"""


class PipelineError(TravelBaseError):
    """多 Agent 编排（pipeline）失败。"""


class IntentRouteError(TravelBaseError):
    """意图路由失败。"""


class FileParseError(TravelBaseError):
    """文件解析失败（发票 PDF/图片等）。"""


class InvalidInputError(TravelBaseError):
    """用户输入非法（缺字段/格式错误），无需重试。"""


class AuthenticationError(TravelBaseError):
    """鉴权失败，无需重试。"""

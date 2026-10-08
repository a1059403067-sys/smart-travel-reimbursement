"""三层兜底重试（参考 EduAgent core/retry.py）。

    第一层 自动重试：MAX_RETRIES 次 + 退避数组 + 单次 wait_for 超时
    第二层 Agent 级业务降级：fallback_map 查表，返回结构与正常结果一致，语义降级
                            （如报销类降级为"转人工审核"而非报错）
    第三层 系统兜底：友好文案，永不失败，保证用户始终收到响应

约定：

- 模型层 max_retries=0（llm_factory 已设），重试只在本层，避免双重放大
- 未分类的异常（编程错误等）不重试、不降级，直接抛出，由编排层边界兜底

用法：

    @with_retry(agent_type="travel")
    async def invoke_travel_graph(state):
        return await graph.ainvoke(state)
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from backend.core.exceptions import (
    AgentExecutionError,
    AuthenticationError,
    DataSourceError,
    FileParseError,
    InvalidInputError,
    LLMAPIError,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────
# 一、异常分类（统一位置，不在类继承里做"可重试"分层）
# ──────────────────────────────────────────────────────────────

RETRYABLE_ERRORS = (
    LLMAPIError,
    DataSourceError,
    AgentExecutionError,
    TimeoutError,
    ConnectionError,
)
NON_RETRYABLE_ERRORS = (
    InvalidInputError,
    AuthenticationError,
    FileParseError,
)

# ──────────────────────────────────────────────────────────────
# 二、重试参数
# ──────────────────────────────────────────────────────────────

MAX_RETRIES = 2
RETRY_DELAYS = [1.0, 3.0]
TIMEOUT_PER_ATTEMPT = 120.0


# ──────────────────────────────────────────────────────────────
# 三、第二层：Agent 级业务降级
# ──────────────────────────────────────────────────────────────
# 降级返回值字段结构与正常结果一致（success/content/structured_output/fallback_used），
# 只是业务语义降级，不是报错。

def _fallback_travel(error: Exception) -> dict:
    return {
        "success": True, "fallback_used": True, "structured_output": None,
        "content": "差旅申请服务暂时繁忙，请稍后重试，或联系管理员人工处理。",
    }


def _fallback_reimbursement(error: Exception) -> dict:
    return {
        "success": True, "fallback_used": True, "needs_human_review": True,
        "structured_output": None,
        "content": "报销服务暂时繁忙，您的报销单已转人工审核，请稍后查看进度。",
    }


def _fallback_analysis(error: Exception) -> dict:
    return {
        "success": True, "fallback_used": True, "structured_output": None,
        "content": "数据分析服务暂时繁忙，请稍后重试。",
    }


def _fallback_chat(error: Exception) -> dict:
    return {
        "success": True, "fallback_used": True, "structured_output": None,
        "content": "抱歉，我暂时无法处理您的请求，请稍后再试。",
    }


class AgentFallbackHandler:
    """agent_type → 降级方法 查表；查不到策略时抛回原异常，交第三层。"""

    _fallback_map: dict[str, Callable[[Exception], dict]] = {
        "travel": _fallback_travel,
        "reimbursement": _fallback_reimbursement,
        "analysis": _fallback_analysis,
        "chat": _fallback_chat,
    }

    @classmethod
    def handle(cls, agent_type: str | None, original_error: Exception) -> dict:
        fn = cls._fallback_map.get(agent_type)
        if fn is None:
            raise original_error  # 无降级策略 → 第三层系统兜底
        logger.warning("retry.agent_fallback", agent_type=agent_type, error=str(original_error))
        return fn(original_error)


# ──────────────────────────────────────────────────────────────
# 四、第三层：系统兜底（永不失败）
# ──────────────────────────────────────────────────────────────

_SYSTEM_FALLBACK_MESSAGES: dict[str, str] = {
    "travel": "差旅申请服务暂时不可用，请稍后重试或联系管理员。",
    "reimbursement": "报销服务暂时不可用，请稍后重试或联系财务。",
    "analysis": "数据分析服务暂时不可用，请稍后重试。",
    "chat": "抱歉，我暂时无法处理您的请求，请稍后再试。",
}


def _system_fallback_response(agent_type: str | None, error: Exception) -> dict:
    logger.error("retry.system_fallback", agent_type=agent_type, error=str(error))
    return {
        "success": True,
        "fallback_used": True,
        "system_fallback": True,
        "structured_output": None,
        "content": _SYSTEM_FALLBACK_MESSAGES.get(agent_type, _SYSTEM_FALLBACK_MESSAGES["chat"]),
    }


# ──────────────────────────────────────────────────────────────
# 五、装饰器本体
# ──────────────────────────────────────────────────────────────


def with_retry(
    agent_type: str | None = None,
    max_retries: int = MAX_RETRIES,
    delays: Sequence[float] = RETRY_DELAYS,
    timeout: float = TIMEOUT_PER_ATTEMPT,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """装饰器工厂：包住 async 函数，逐层兜底、永不向上抛可恢复错误。"""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            # 第一层：自动重试
            for attempt in range(max_retries + 1):
                try:
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                except NON_RETRYABLE_ERRORS:
                    raise  # 不可重试：立即抛出，不消耗重试次数
                except RETRYABLE_ERRORS as exc:
                    last_error = exc
                    if attempt < max_retries:
                        await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                        continue
                    break  # 重试耗尽 → 第二层
                except Exception:
                    raise  # 未分类异常（编程错误等）：不重试、不降级，直接抛出
                else:
                    if attempt > 0:
                        logger.info("retry.succeeded", agent_type=agent_type, attempt=attempt)
                    return result
            # 第二层：Agent 级业务降级（无策略 raise → 第三层）
            try:
                return AgentFallbackHandler.handle(agent_type, last_error)
            except Exception:
                # 第三层：系统兜底，永不失败
                return _system_fallback_response(agent_type, last_error)

        return wrapper

    return decorator


# ──────────────────────────────────────────────────────────────
# 六、离线自测（5 个场景，delays 置零加速）
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    async def main():
        # 1) 成功路径
        @with_retry(agent_type="chat", delays=[0, 0], timeout=5)
        async def ok():
            return {"success": True, "content": "ok", "fallback_used": False}

        print(f"[1 成功] {await ok()}")

        # 2) 重试后成功
        calls = {"n": 0}

        @with_retry(agent_type="chat", delays=[0, 0], timeout=5)
        async def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise LLMAPIError("第一次超时", agent_type="chat")
            return {"success": True, "content": "second try", "fallback_used": False}

        r = await flaky()
        print(f"[2 重试后成功] 共调用 {calls['n']} 次 -> {r['content']}")

        # 3) 不可重试：立即抛出
        @with_retry(agent_type="chat", delays=[0, 0], timeout=5)
        async def bad_input():
            raise InvalidInputError("缺少必填字段")

        try:
            await bad_input()
        except InvalidInputError as exc:
            print(f"[3 不可重试] 立即抛出: {exc}")

        # 4) 有降级策略（travel → 业务降级）
        @with_retry(agent_type="travel", delays=[0, 0], timeout=5)
        async def fail_travel():
            raise LLMAPIError("服务超时", agent_type="travel")

        r = await fail_travel()
        print(f"[4 业务降级] fallback_used={r['fallback_used']} -> {r['content']}")

        # 5) 无降级策略（intent 未注册）→ 系统兜底
        @with_retry(agent_type="intent", delays=[0, 0], timeout=5)
        async def fail_unknown():
            raise LLMAPIError("boom")

        r = await fail_unknown()
        print(f"[5 系统兜底] system_fallback={r.get('system_fallback')} -> {r['content']}")

    asyncio.run(main())

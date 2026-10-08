"""LLM 工厂：全项目唯一 LLM 入口。

约束（参考 EduAgent core/llm_factory.py）：

1. 所有 Agent/节点禁止直接 new 模型，一律经本模块 get_llm / get_structured_llm 获取
2. 两级路由表：业务名 → 模型标识符 → 实际 model 名；换模型/换供应商各改一行
3. 模型层 max_retries=0：重试统一归 core/retry.py 的 with_retry，避免双重放大
4. 实例按 (模型标识符, 温度, 流式) 三元组缓存，clear_cache() 供测试/关停
5. 限流内建在工厂：contextvar 注入 user_id（子 task 自动继承）+ 每用户 → 全局两级信号量
6. 结构化输出统一 method="function_calling"（DeepSeek 必需，EduAgent 踩坑结论）

用法：

    from backend.core.llm_factory import get_llm, get_structured_llm, set_llm_user_id

    set_llm_user_id(user_id)                  # 请求入口注入（须在 asyncio.create_task 之前）
    llm = get_llm("travel")                   # 差旅 Agent 模型（限流包装，可直接 pipe）
    structured = get_structured_llm("intent", MySchema)
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.config import get_settings

# ──────────────────────────────────────────────────────────────
# 一、限流身份注入（contextvar）
# ──────────────────────────────────────────────────────────────
# 请求入口 set_llm_user_id(user_id)，子 task 自动继承。
# 注意：必须在 asyncio.create_task 之前调用——context 在 task 创建时复制。

_llm_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_user_id", default=None)


def set_llm_user_id(user_id: str | None) -> None:
    _llm_user_id.set(user_id)


def get_llm_user_id() -> str | None:
    return _llm_user_id.get()


# ──────────────────────────────────────────────────────────────
# 二、两级路由表
# ──────────────────────────────────────────────────────────────
# 业务名 → 模型标识符（新 Agent 在此登记）

_AGENT_MODEL_ROUTING: dict[str, str] = {
    "intent": "intent",          # 意图路由（temperature=0）
    "chat": "chat",              # 通用对话
    "travel": "chat",            # 差旅申请 Agent
    "reimbursement": "chat",     # 报销 Agent
    "analysis": "chat",          # 数据分析 / NL2SQL
    "summarize": "chat",         # 记忆摘要
}


def _resolve_model_key(agent_type: str) -> str:
    key = _AGENT_MODEL_ROUTING.get(agent_type)
    if key is None:
        raise ValueError(f"未注册的 agent_type: {agent_type!r}，可用值: {sorted(_AGENT_MODEL_ROUTING)}")
    return key


# ──────────────────────────────────────────────────────────────
# 三、实例缓存 + 构建
# ──────────────────────────────────────────────────────────────

_instances: dict[tuple[str, float, bool], ChatOpenAI] = {}


def _build_cached(model_key: str, temperature: float, streaming: bool) -> ChatOpenAI:
    cache_key = (model_key, temperature, streaming)
    if cache_key not in _instances:
        _instances[cache_key] = _build_model(model_key, temperature, streaming)
    return _instances[cache_key]


def _build_model(model_key: str, temperature: float, streaming: bool) -> ChatOpenAI:
    s = get_settings()
    # 模型标识符 → 实际 API model 名（换供应商只改这两行 + 构建参数）
    model_id = s.deepseek_model_intent if model_key == "intent" else s.deepseek_model_chat
    # trust_env=False：绕过系统代理，否则 Windows 系统代理可能导致 TLS 握手失败（EduAgent 踩坑）
    http_client = httpx.Client(
        timeout=httpx.Timeout(120.0, connect=15.0),
        trust_env=False,
    )
    return ChatOpenAI(
        model=model_id,
        api_key=s.deepseek_api_key,
        base_url=s.deepseek_base_url,
        temperature=temperature,
        streaming=streaming,
        max_retries=0,  # 重试统一归 core/retry.py，避免双重放大
        http_client=http_client,
    )


def clear_cache() -> None:
    """清空模型实例缓存（测试/关停用）。"""
    _instances.clear()


# ──────────────────────────────────────────────────────────────
# 四、限流闸（每用户 → 全局 两级信号量）
# ──────────────────────────────────────────────────────────────

_global_sem: asyncio.Semaphore | None = None
_user_sems: dict[str, asyncio.Semaphore] = {}
_user_sems_last_used: dict[str, float] = {}
_last_sweep = 0.0
_USER_SEM_TTL_SECONDS = 30 * 60  # 30 分钟未使用的用户信号量回收，防字典无限增长


def _get_user_sem(user_key: str) -> asyncio.Semaphore:
    global _global_sem, _last_sweep
    s = get_settings()
    if _global_sem is None:
        _global_sem = asyncio.Semaphore(s.llm_global_concurrency)
    now = time.time()
    if now - _last_sweep > 60:  # 最多每分钟做一次 TTL 回收
        _last_sweep = now
        for k in [k for k, ts in _user_sems_last_used.items() if now - ts > _USER_SEM_TTL_SECONDS]:
            _user_sems.pop(k, None)
            _user_sems_last_used.pop(k, None)
    if user_key not in _user_sems:
        _user_sems[user_key] = asyncio.Semaphore(s.llm_per_user_concurrency)
    _user_sems_last_used[user_key] = now
    return _user_sems[user_key]


@asynccontextmanager
async def llm_rate_guard(user_id: str | None) -> AsyncIterator[None]:
    """限流上下文：先每用户、后全局。所有调用点获取顺序一致，不会死锁。"""
    async with _get_user_sem(user_id or "anonymous"):
        async with _global_sem:
            yield


# ──────────────────────────────────────────────────────────────
# 五、限流包装（Runnable 子类，可直接参与 prompt | llm | parser 管道）
# ──────────────────────────────────────────────────────────────


class _RateLimitedChatModel(Runnable):
    """包装 ChatOpenAI：异步调用前过限流闸；同步路径（调试用）不限流。"""

    inner: Any  # 普通类注解（Runnable 非 pydantic 模型），仅作文档

    def __init__(self, inner: Any):
        self.inner = inner

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self.inner.invoke(input, config=config, **kwargs)

    def stream(self, input: Any, config: Any = None, **kwargs: Any):
        return self.inner.stream(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        async with llm_rate_guard(get_llm_user_id()):
            return await self.inner.ainvoke(input, config=config, **kwargs)

    async def astream(self, input: Any, config: Any = None, **kwargs: Any):
        async with llm_rate_guard(get_llm_user_id()):
            async for chunk in self.inner.astream(input, config=config, **kwargs):
                yield chunk


class _RateLimitedRunnable(Runnable):
    """包装结构化输出链：with_structured_output 内部链路会绕过 ChatOpenAI 的
    _agenerate/_astream，因此对整条链再包一层限流。"""

    inner: Any  # 普通类注解（Runnable 非 pydantic 模型），仅作文档

    def __init__(self, inner: Any):
        self.inner = inner

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return self.inner.invoke(input, config=config, **kwargs)

    def stream(self, input: Any, config: Any = None, **kwargs: Any):
        return self.inner.stream(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        async with llm_rate_guard(get_llm_user_id()):
            return await self.inner.ainvoke(input, config=config, **kwargs)

    async def astream(self, input: Any, config: Any = None, **kwargs: Any):
        async with llm_rate_guard(get_llm_user_id()):
            async for chunk in self.inner.astream(input, config=config, **kwargs):
                yield chunk


# ──────────────────────────────────────────────────────────────
# 六、对外 API
# ──────────────────────────────────────────────────────────────


def get_llm(agent_type: str, temperature: float = 0.0, streaming: bool = False) -> Runnable:
    """获取限流包装后的 LLM（Runnable，可直接 prompt | llm | parser）。"""
    key = _resolve_model_key(agent_type)
    return _RateLimitedChatModel(inner=_build_cached(key, temperature, streaming))


def get_structured_llm(agent_type: str, schema: type[BaseModel], temperature: float = 0.0) -> Runnable:
    """结构化输出 LLM：with_structured_output(function_calling) + 限流包装。"""
    key = _resolve_model_key(agent_type)
    inner = _build_cached(key, temperature, streaming=False)
    # method="function_calling"：DeepSeek 结构化输出必需（EduAgent 踩坑）
    structured = inner.with_structured_output(schema, method="function_calling")
    return _RateLimitedRunnable(inner=structured)


# ──────────────────────────────────────────────────────────────
# 七、离线自测
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # 1) 未注册类型必须报错并列出合法值
    try:
        get_llm("nonexistent")
    except ValueError as exc:
        print(f"[预期报错] {exc}")

    # 2) 实例缓存：同参数两次获取同一实例
    a = get_llm("intent")
    b = get_llm("intent")
    print(f"[缓存] 同参数同实例: {a.inner is b.inner}")

    # 3) 结构化输出：验证 function_calling 路径
    class _TestDecision(BaseModel):
        label: str
        reason: str

    async def _test_structured():
        set_llm_user_id("test_user")
        sllm = get_structured_llm("intent", _TestDecision)
        return await sllm.ainvoke("帮我查一下明天北京到上海的高铁票")

    try:
        decision = asyncio.run(_test_structured())
        print(f"[结构化输出] label={decision.label} reason={decision.reason}")
    except Exception as exc:
        print(f"[结构化输出失败] {exc}")

    # 4) 与 Router 集成：真实路由（需 .env.local 已填 DEEPSEEK_API_KEY）
    from backend.core.router import IntentRouter

    router = IntentRouter(get_llm("intent"))
    print("\n--- 真实 LLM 路由（DeepSeek）---")
    for q in [
        "帮我查一下明天北京到上海的高铁票",
        "我下周要去杭州出差三天，帮我安排行程",
        "这张住宿发票能报销吗",
        "上个月我们部门差旅费花了多少，出个图",
        "今天天气怎么样",
        "你好呀",
    ]:
        r = router.route(q)
        print(f"[{r.label.value:15s} | {r.routed_by:8s}] {q} → {r.reason}")

"""结构化日志：event | k=v 格式，便于 grep 与日志采集。

用法：

    from backend.core.logger import get_logger
    logger = get_logger(__name__)

    logger.info("auth.login_success", user_id=uid, role=role)
    logger.error("chat.invoke_error", error=str(e), exc_info=True)

设计（参考 EduAgent core/logger.py）：

- 包装而非继承：_Logger 持有标准库 logger
- 双写法兼容：logger.info("模板 %s", 值) 与 logger.info("事件名", key=value) 都支持
- error 的 exc_info 从 kwargs 提取透传，保留堆栈
- configure_logging(force=True)：重复调用 / 其他库先配置过也生效
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s | %(message)s"


class _Logger:
    """标准库 logger 的薄包装，统一「事件名 + 键值对」风格。"""

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, args, kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, args, kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, args, kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, args, kwargs)

    def _log(self, level: int, msg: str, args: tuple, kwargs: dict) -> None:
        exc_info = kwargs.pop("exc_info", None)  # 提取透传，保留堆栈
        text = msg
        if args:  # 兼容老写法 logger.info("模板 %s", 值)
            text = msg % args
        if kwargs:  # 事件风格：logger.info("事件名", key=value)
            pairs = " ".join(f"{k}={v}" for k, v in kwargs.items())
            text = f"{text} | {pairs}"
        self._logger.log(level, text, exc_info=exc_info)


def configure_logging(level: str = "INFO") -> None:
    """统一配置入口（在 main 的 lifespan 里调用一次）。"""
    resolved = getattr(logging, level.upper(), logging.INFO)  # 非法级别三重兜底
    logging.basicConfig(
        level=resolved,
        format=_DEFAULT_FORMAT,
        stream=sys.stdout,
        force=True,  # 保证重复调用 / 其他库先配置过也生效
    )
    # 压低第三方库噪音
    for noisy in ("sqlalchemy.engine", "sqlalchemy.pool", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> _Logger:
    """模块级工厂：get_logger(__name__)，模块名进日志便于定位。"""
    return _Logger(logging.getLogger(name))

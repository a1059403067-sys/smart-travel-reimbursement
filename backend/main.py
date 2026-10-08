# 应用入口（架构方案 P0 精简版：migrations + 路由聚合 + /health）
#
# 参考 EduAgent backend/main.py：
# - Windows conda 专用 DLL 补丁（_lzma.pyd 找不到 liblzma.dll 的坑）
# - lifespan：启动执行幂等 migrations，失败只告警不拦启动
# - CORS 放行前端开发端口
# 后续 P1/P2 模块就绪后，在 lifespan 里追加模型预热等逻辑。

import os
import sys

# Windows conda 专用：把 base 的 Library/bin 加入 DLL 搜索路径，
# 让 _lzma.pyd 能找到 liblzma.dll（非 Windows 跳过，不影响 Linux/Mac）
if sys.platform == "win32":
    _conda_base_lib_bin = os.path.normpath(
        os.path.join(os.path.dirname(sys.executable), "..", "..", "Library", "bin")
    )
    if os.path.isdir(_conda_base_lib_bin):
        os.add_dll_directory(_conda_base_lib_bin)

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.router import api_router
from backend.config import get_settings
from backend.core.logger import configure_logging, get_logger

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger(__name__)
    logger.info("app.starting | env=%s port=%s", settings.app_env, settings.app_port)

    # DB Schema 自动迁移（幂等，每次启动执行）
    try:
        from backend.db.migrations import run_migrations

        await run_migrations()
    except Exception as e:
        # 审核 R-10：dev 只告警；prod 迁移失败必须阻断启动（schema 落后时接口 500 无信号更危险）
        if settings.app_env == "prod":
            logger.error("app.migrations_failed | error=%s", e)
            raise
        logger.warning("app.migrations_failed | error=%s", e)  # dev 告警不拦启动

    logger.info("app.started")
    yield
    logger.info("app.shutting_down")


app = FastAPI(
    title=settings.app_name,
    description="智能差旅报销系统 API",
    version="0.1.0",
    docs_url="/docs",  # Swagger 文档
    redoc_url="/redoc",  # ReDoc 文档
    lifespan=lifespan,  # 挂生命周期钩子
)

# CORS：允许前端开发端口跨域访问（与 EduAgent 同款白名单；审核 R-06：补 localhost:3001）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", "http://localhost:5173", "http://localhost:8080",
        "http://localhost:3001",
        "http://127.0.0.1:3001", "http://127.0.0.1:5173", "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health", tags=["系统"])  # 健康检查（运维探活用）
async def health_check():
    return {"status": "ok", "env": settings.app_env}

# 依赖注入（DB 会话）
# backend/dependencies.py
#
# 参考 EduAgent backend/dependencies.py 的 DB 部分：
# - 引擎在模块导入时创建，连接串来自 config.py（最终来自 .env.local）
# - pool_size=30 / max_overflow=20 与 EduAgent 一致
# - get_db：FastAPI 依赖，自动提交 / 回滚 / 关闭
# - JWT 的 get_current_user 待 auth 模块（P0）实现时移植，当前接口先行不加鉴权
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings

settings = get_settings()

# ── 创建异步引擎（连接池）──
engine = create_async_engine(
    settings.database_url,  # postgresql+asyncpg://...（config.py 派生属性）
    pool_size=30,           # 连接池基础大小
    max_overflow=20,        # 高峰时最多再额外开 20 个连接
    echo=False,             # True 会打印所有 SQL，调试时可临时打开
)

# ── 会话工厂 ──
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取异步数据库会话，自动提交 / 回滚 / 关闭"""
    async with AsyncSessionLocal() as session:
        try:
            yield session  # 把会话交给接口使用
            await session.commit()  # 接口正常结束 → 自动提交
        except Exception:
            await session.rollback()  # 出错 → 自动回滚
            raise


if __name__ == "__main__":
    # 离线自测：验证 get_db 能连上数据库（需要 .env.local 指向可用 PG）
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from sqlalchemy import text

    async def main():
        async for db in get_db():
            r = await db.execute(text("SELECT current_database(), current_user"))
            row = r.fetchone()
            print(f"get_db 连到库: {row[0]} / 用户: {row[1]}")

    asyncio.run(main())
    print("get_db 测试通过 ✅")

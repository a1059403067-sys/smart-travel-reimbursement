# 依赖注入（DB 会话 + JWT 鉴权）
# backend/dependencies.py
#
# 参考 EduAgent backend/dependencies.py：
# - 引擎在模块导入时创建，连接串来自 config.py（最终来自 .env.local）
# - pool_size=30 / max_overflow=20 与 EduAgent 一致
# - get_db：FastAPI 依赖，自动提交 / 回滚 / 关闭
# - get_current_user：JWT 解析（PyJWT，与 EduAgent 的 jose 同 API）
# - require_role：角色守卫依赖工厂 —— 架构方案要求"role 必须参与鉴权"
#   （补 EduAgent 的坑：其教师端点无角色校验，任何登录用户都能调）
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
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


# ── JWT 鉴权 ───────────────────────────────────────────────────
# bearer_scheme：自动从请求头解析 "Authorization: Bearer <token>"，缺失/格式错直接 401

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """FastAPI 依赖：验证 JWT，返回 {"user_id": str, "role": str, "tenant_id": str}。

    Token 无效（签名错/过期/缺 sub）一律 401。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        role: str = payload.get("role", "employee")
        tenant_id: str = payload.get("tenant_id", settings.default_tenant_id)
        if not user_id:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    return {"user_id": user_id, "role": role, "tenant_id": tenant_id}


def require_role(*allowed_roles: str):
    """角色守卫依赖工厂：require_role("approver", "finance") 用于审批/财务端点。

    用法：

        @router.post("/approve")
        async def approve(..., current_user: dict = Depends(require_role("approver", "admin"))):
            ...
    """

    async def _role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"无权访问，需要角色：{'/'.join(allowed_roles)}",
            )
        return current_user

    return _role_checker


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

# 登录鉴权（架构方案 P0：api/v1/auth.py —— 登录/JWT 签发）
#
# POST /api/auth/login：账号密码验证成功签发 JWT（sub/role/tenant_id）
# GET  /api/auth/me   ：验证 Token 并返回当前用户信息（前端登录态校验用）
#
# 参考 EduAgent auth.py：
# - bcrypt 校验放线程池（CPU 密集 ~100ms，不阻塞事件循环）
# - 密码错误与账号不存在返回同一文案（不泄露账号是否存在）
# - JWT 用 PyJWT（与 EduAgent 的 python-jose 同 API）

import asyncio
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt_mod
import types as _types
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from backend.config import get_settings
from backend.core.logger import get_logger
from backend.dependencies import get_current_user, get_db

# ── 兼容性补丁：passlib 1.7.4 要读 bcrypt.__about__.__version__，而 bcrypt>=4 删了它 ──
if not hasattr(_bcrypt_mod, "__about__"):
    _about = _types.SimpleNamespace(__version__=getattr(_bcrypt_mod, "__version__", "4.x"))
    _bcrypt_mod.__about__ = _about  # 注入假的 __about__，让 passlib 能探测到版本

import jwt  # noqa: E402  PyJWT

router = APIRouter(prefix="/api/auth", tags=["认证"])
logger = get_logger(__name__)

# 密码哈希上下文（bcrypt；seed_data.py 灌种子账号时用同一方案）
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """登录成功的响应体。"""

    access_token: str  # JWT 令牌
    token_type: str = "bearer"  # 令牌类型，固定 bearer
    expires_in: int  # 有效期（秒）
    role: str  # 用户角色（前端据此渲染菜单/权限）
    user_id: str  # 用户ID
    real_name: str = ""  # 真实姓名（前端顶栏展示）


# ── 注册（契约 REQ-9/10，2026-10-09 会话 B 提出）──

# 注册允许部门白名单（与 GET /api/departments 同一常量，契约 REQ-10 五项）
_REGISTERABLE_DEPARTMENTS = ("幕墙设计部", "BIM部", "内装部", "城市更新部", "综合业务部")


class RegisterRequest(BaseModel):
    """注册请求体（契约 REQ-9）。"""

    real_name: str = Field(..., min_length=1, max_length=64, description="真实姓名")
    department: str = Field(..., min_length=1, max_length=128, description="所属部门（白名单）")
    password: str = Field(..., min_length=6, max_length=72, description="密码至少 6 位（bcrypt 上限 72 字节）")


class RegisterResponse(BaseModel):
    """注册成功响应体（前端展示 username 作为登录账号）。"""

    username: str
    real_name: str
    department: str
    role: str = "employee"


def _generate_username(real_name: str, taken: set[str]) -> str:
    """姓名拼音生成 username；与已有账号冲突时追加数字后缀（zhangsan、zhangsan2）。"""
    from pypinyin import lazy_pinyin  # 延迟导入：仅注册路径使用

    base = "".join(lazy_pinyin(real_name)).lower() or "user"
    candidate, suffix = base, 2
    while candidate in taken:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def _create_access_token(data: dict, expires_minutes: int) -> str:
    """把身份信息 + 过期时间打包，用密钥签名成 JWT 字符串。"""
    settings = get_settings()
    payload = data.copy()  # 拷一份，避免改到原字典
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload["exp"] = expire  # exp 是 JWT 标准的过期字段
    # 审核 R-09：声明签发方/接收方，与 get_current_user 的校验配对
    payload["iss"] = "travel-reimburse-api"
    payload["aud"] = "travel-reimburse-web"
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.post("/login", response_model=TokenResponse, summary="登录并签发 JWT")
async def login(
    req: LoginRequest,  # 请求体自动解析为 LoginRequest
    db: AsyncSession = Depends(get_db),  # 注入数据库会话
):
    """用户登录，返回 JWT Access Token（支持用户名或邮箱登录）。"""
    settings = get_settings()
    result = await db.execute(
        text(
            "SELECT id, password_hash, role, tenant_id, is_active, real_name "
            "FROM users WHERE username = :val OR email = :val ORDER BY id LIMIT 1"
        ),
        {"val": req.username},
    )
    row = result.fetchone()
    if not row:
        # 账号不存在与密码错误同文案，不泄露账号是否存在
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not row.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用，请联系管理员")

    # 密码校验是 CPU 密集型（~100ms），用线程池避免阻塞事件循环
    loop = asyncio.get_running_loop()
    password_ok = await loop.run_in_executor(
        None, pwd_context.verify, req.password, row.password_hash
    )
    if not password_ok:
        # TODO(限速): 登录失败限速未实现——应用层无共享存储，待部署网关（nginx rate_limit
        # 或云 WAF）统一限流后接入；当前仅记录日志供安全审计（审核 R-09）
        logger.warning("auth.login_failed", username=req.username)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token = _create_access_token(
        data={"sub": str(row.id), "role": row.role, "tenant_id": row.tenant_id},
        expires_minutes=settings.jwt_access_token_expire_minutes,
    )
    logger.info("auth.login_success", user_id=str(row.id), role=row.role)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        role=row.role,
        user_id=str(row.id),
        real_name=row.real_name or "",
    )


@router.get("/me", summary="当前登录用户信息（前端登录态校验）")
async def get_me(
    current_user: dict = Depends(get_current_user),
):
    """验证 Token 并返回身份信息（顺带完成鉴权）。"""
    return current_user


@router.post("/register", response_model=RegisterResponse,
             status_code=status.HTTP_201_CREATED, summary="注册新员工（契约 REQ-9）")
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """注册流程：部门白名单校验 → bcrypt 哈希 → username 拼音生成 → 落库。

    错误码（契约 REQ-9）：
    - 422 非法部门 / 密码不足 6 位（pydantic 自动）
    - 409 （real_name, department）组合已注册（唯一索引兜底并发）
    """
    # ① 部门白名单（REQ-10 五部门，种子部门不可选）
    if req.department not in _REGISTERABLE_DEPARTMENTS:
        raise HTTPException(status_code=422, detail="请选择正确的部门")

    # ② 部门幂等落库 + 回查 id（注册用户有 department_id，统计口径与种子账号一致）
    await db.execute(text(
        "INSERT INTO departments (name) VALUES (:name) ON CONFLICT (name) DO NOTHING"
    ), {"name": req.department})
    dept_id = (await db.execute(text(
        "SELECT id FROM departments WHERE name = :name"
    ), {"name": req.department})).scalar()

    # ③ username：姓名拼音 + 冲突数字后缀（现有账号集合去重）
    taken = {r[0] for r in (await db.execute(text("SELECT username FROM users"))).all()}
    username = _generate_username(req.real_name, taken)

    # ④ bcrypt 哈希（CPU 密集，线程池，同 login）
    loop = asyncio.get_running_loop()
    password_hash = await loop.run_in_executor(
        None, pwd_context.hash, req.password
    )

    # ⑤ 落库；组合唯一索引兜底并发重复 → 409（username 已去重，冲突只可能来自组合索引）
    try:
        await db.execute(text(
            "INSERT INTO users (username, password_hash, real_name, department_id, role) "
            "VALUES (:username, :hash, :real_name, :dept_id, 'employee')"
        ), {"username": username, "hash": password_hash,
            "real_name": req.real_name, "dept_id": dept_id})
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="该姓名在此部门已注册")

    logger.info("auth.registered", username=username, department=req.department)
    return RegisterResponse(
        username=username, real_name=req.real_name,
        department=req.department, role="employee",
    )


# ── 部门列表（REQ-10）：公开接口，注册页下拉用（前缀与 auth 不同，独立 router）──

dept_router = APIRouter(prefix="/api/departments", tags=["部门"])


@dept_router.get("", summary="可注册部门列表（契约 REQ-10，公开接口）")
async def list_departments():
    """返回注册白名单五部门；注册页下拉直接渲染。"""
    return {"items": list(_REGISTERABLE_DEPARTMENTS)}


if __name__ == "__main__":
    # 离线自测：真库种子 → 登录 → 带 Token 访问 /me（403/401 场景）
    # 前提：.env.local 指向可用 PG（可用环境变量覆盖 DB_USER/DB_PASSWORD）
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    async def main():
        import httpx

        from backend.db.migrations import run_migrations
        from backend.main import app
        from backend.dependencies import require_role
        from fastapi import FastAPI

        # ① 建表 + 种子（依赖 scripts/seed_data.py 的幂等逻辑）
        await run_migrations()
        from scripts.seed_data import seed_all

        await seed_all()

        # ② 角色守卫验证：临时挂一个 admin-only 端点
        _guard_app = FastAPI()
        _guard_router = APIRouter()

        @_guard_router.get("/admin-only")
        async def _admin_only(current_user: dict = Depends(require_role("admin"))):
            return {"ok": True, "user": current_user}

        _guard_app.include_router(_guard_router)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1) 错误密码 → 401
            r = await client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
            print(f"[1 错误密码] {r.status_code} {r.json()['detail']}")
            assert r.status_code == 401

            # 2) 正确登录 → token
            r = await client.post("/api/auth/login", json={"username": "admin", "password": "Admin@123456"})
            print(f"[2 登录成功] {r.status_code} role={r.json()['role']} real_name={r.json()['real_name']}")
            assert r.status_code == 200 and r.json()["role"] == "admin"
            token = r.json()["access_token"]

            # 3) 带 Token 访问 /me → 200
            r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            print(f"[3 /me] {r.status_code} {r.json()}")
            assert r.status_code == 200 and r.json()["role"] == "admin"

            # 4) 无 Token → 401
            r = await client.get("/api/auth/me")
            print(f"[4 无 Token] {r.status_code}")
            assert r.status_code == 401

            # 5) 员工账号调 admin-only → 403（role 鉴权生效）
            r = await client.post("/api/auth/login", json={"username": "zhangwei", "password": "Employee@123456"})
            emp_token = r.json()["access_token"]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_guard_app), base_url="http://test") as gc:
                r = await gc.get("/admin-only", headers={"Authorization": f"Bearer {emp_token}"})
                print(f"[5 员工调 admin-only] {r.status_code} {r.json()['detail']}")
                assert r.status_code == 403
                r = await gc.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
                print(f"[6 admin 调 admin-only] {r.status_code} {r.json()}")
                assert r.status_code == 200

            # ── 注册场景（REQ-9/10，A-16）──
            from backend.dependencies import AsyncSessionLocal

            # 幂等清理：删此前自测注册的用户（演示用户 zhangsan 占拼音，analytics 自测会重建）
            async with AsyncSessionLocal() as db:
                await db.execute(text("DELETE FROM users WHERE username IN ('zhangsan', 'zhangsan2')"))
                await db.commit()

            # 7) 部门列表（公开接口，无 Token）
            r = await client.get("/api/departments")
            assert r.status_code == 200 and len(r.json()["items"]) == 5
            print(f"[7 部门列表] {r.status_code} 共 {len(r.json()['items'])} 个注册部门")

            # 8) 正常注册 → 201 + username 拼音生成
            r = await client.post("/api/auth/register", json={
                "real_name": "张三", "department": "幕墙设计部", "password": "Zhangsan@123"})
            data = r.json()
            assert r.status_code == 201 and data["username"] == "zhangsan" and data["role"] == "employee"
            print(f"[8 注册] 201 username={data['username']} department={data['department']}")

            # 9) 同姓名同部门重复 → 409（组合唯一）
            r = await client.post("/api/auth/register", json={
                "real_name": "张三", "department": "幕墙设计部", "password": "Zhangsan@123"})
            assert r.status_code == 409 and "已注册" in r.json()["detail"]
            print(f"[9 重复注册] {r.status_code} {r.json()['detail']}")

            # 10) 非法部门（种子部门不在白名单）/ 短密码 → 422
            r = await client.post("/api/auth/register", json={
                "real_name": "李四", "department": "研发部", "password": "Lisi@123456"})
            assert r.status_code == 422
            r = await client.post("/api/auth/register", json={
                "real_name": "李四", "department": "幕墙设计部", "password": "123"})
            assert r.status_code == 422
            print("[10 非法部门/短密码] 422 / 422")

            # 11) 同姓名不同部门 → 201 + 拼音冲突数字后缀
            r = await client.post("/api/auth/register", json={
                "real_name": "张三", "department": "内装部", "password": "Zhangsan@123"})
            data = r.json()
            assert r.status_code == 201 and data["username"] == "zhangsan2"
            print(f"[11 拼音冲突] username={data['username']}（同姓名不同部门）")

            # 12) 注册后立即登录 → 200
            r = await client.post("/api/auth/login", json={"username": "zhangsan", "password": "Zhangsan@123"})
            assert r.status_code == 200 and r.json()["real_name"] == "张三"
            print(f"[12 注册后登录] {r.status_code} real_name={r.json()['real_name']}")

        print("\n断言通过 ✅：登录 / JWT 鉴权 / 角色守卫 / 注册 / 部门列表全部正常")

    asyncio.run(main())

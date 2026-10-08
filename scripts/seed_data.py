# 灌种子数据
# scripts/seed_data.py
# 执行：python scripts/seed_data.py（.env.local 指向可用 PG）
# 用途：灌入本地开发测试账号（四角色）+ 部门；全部幂等（ON CONFLICT DO NOTHING）
# 参考 EduAgent scripts/seed_data.py：asyncpg 直连 + 密码 bcrypt 哈希绝不存明文

import asyncio
import sys

import asyncpg  # PostgreSQL 异步驱动（脚本直接用它，简单直接）
import bcrypt as _b
import types as _t
from passlib.context import CryptContext

from backend.config import get_settings

# 兼容性补丁：同 auth.py，让 passlib 能读到 bcrypt 版本
if not hasattr(_b, "__about__"):
    _b.__about__ = _t.SimpleNamespace(__version__=getattr(_b, "__version__", "4.x"))

s = get_settings()
# asyncpg 连接串（注意 asyncpg 用 postgresql:// 而非 +asyncpg）
DB_DSN = (
    f"postgresql://{s.db_user}:{s.db_password}"
    f"@{s.db_host}:{s.db_port}"
    f"/{s.db_name}"
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 种子部门：账号按部门名回查 id（不用固定序号——SERIAL 序列不保证从 1 连续）
SEED_DEPARTMENTS = ["研发部", "市场部", "销售部", "财务部"]

# 种子账号：username / 密码 / 角色 / 姓名 / 部门名（None=无部门）
SEED_USERS = [
    {"username": "admin",     "pwd": "Admin@123456",    "role": "admin",     "real_name": "系统管理员", "dept": None,   "email": "admin@corp.local"},
    {"username": "zhangwei",  "pwd": "Employee@123456", "role": "employee",  "real_name": "张伟",       "dept": "研发部", "email": "zhangwei@corp.local"},
    {"username": "lium",      "pwd": "Approver@123456", "role": "approver",  "real_name": "刘敏",       "dept": "研发部", "email": "lium@corp.local"},
    {"username": "wangcai",   "pwd": "Finance@123456",  "role": "finance",   "real_name": "王财",       "dept": "财务部", "email": "wangcai@corp.local"},
]


async def seed_all() -> None:
    """灌入部门 + 测试账号（已存在则跳过），并打印账号清单。"""
    conn = await asyncpg.connect(DB_DSN)
    try:
        # 部门（name 唯一索引兜底幂等）
        for name in SEED_DEPARTMENTS:
            await conn.execute(
                "INSERT INTO departments (name) VALUES ($1) ON CONFLICT (name) DO NOTHING",
                name,
            )
        # 回查 name → id 映射（幂等重跑后 id 不变）
        dept_ids = {
            r["name"]: r["id"]
            for r in await conn.fetch("SELECT id, name FROM departments")
        }
        # 账号（username 唯一索引兜底幂等；密码只存 bcrypt 哈希）
        for u in SEED_USERS:
            await conn.execute(
                """
                INSERT INTO users (username, password_hash, real_name, email, department_id, role)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (username) DO NOTHING
                """,
                u["username"], pwd_context.hash(u["pwd"]), u["real_name"],
                u["email"], dept_ids.get(u["dept"]), u["role"],
            )
        print("✅ 种子数据灌入完成（已存在则跳过）")
        for u in SEED_USERS:
            print(f"   {u['username']:<10} / {u['pwd']:<16} 角色={u['role']:<9} 部门={u['dept'] or '（无）'}")
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(seed_all())

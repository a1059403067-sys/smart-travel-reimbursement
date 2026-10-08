# 自动迁移补丁
# backend/db/migrations.py
#
# 启动时自动执行的 Schema 补丁（全部幂等，可重复运行）。
# 规则（参考 EduAgent db/migrations.py）：
#   - 只写 CREATE TABLE/INDEX IF NOT EXISTS 等幂等 DDL
#   - 禁止写 DROP / TRUNCATE 等破坏性变更
#   - 新表/新字段按时间顺序在 _MIGRATIONS 里追加，只增不删
#
# 建表 SQL 与架构方案.md 第 7 节表设计一致。
# 当前先行三张表（stats 接口所需）：departments / users / travel_requests；
# invoices / reimbursements / approvals / expense_policies 待对应模块实现时追加。

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

# ── 所有建表/索引 DDL，按时间顺序追加。SQL 必须幂等（IF NOT EXISTS）──
_MIGRATIONS: list[tuple[str, str]] = [
    (
        "departments",
        """
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            name VARCHAR(128) NOT NULL UNIQUE,
            parent_id INTEGER,
            manager_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ),
    (
        "users",
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(256) NOT NULL,
            real_name VARCHAR(64),
            department_id INTEGER REFERENCES departments(id),
            role VARCHAR(16) NOT NULL DEFAULT 'employee',
            tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ),
    (
        "travel_requests",
        """
        CREATE TABLE IF NOT EXISTS travel_requests (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            title VARCHAR(256),
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            trip_type VARCHAR(16),
            departure_city VARCHAR(64),
            arrival_city VARCHAR(64),
            start_date DATE,
            end_date DATE,
            reason TEXT,
            estimated_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            itinerary JSONB,
            approver_id INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""",
    ),
    (
        "idx_travel_requests_user_status",
        "CREATE INDEX IF NOT EXISTS idx_travel_requests_user_status "
        "ON travel_requests (user_id, status)",
    ),
    (
        "idx_travel_requests_status_created",
        "CREATE INDEX IF NOT EXISTS idx_travel_requests_status_created "
        "ON travel_requests (status, created_at DESC)",
    ),
    (
        "idx_users_department",
        "CREATE INDEX IF NOT EXISTS idx_users_department ON users (department_id)",
    ),
]


async def run_migrations() -> None:
    """
    在应用启动时执行所有 Schema 补丁。
    单条失败只记录警告，不阻断启动流程（EduAgent 同款）。
    """
    async with AsyncSessionLocal() as session:
        for desc, sql in _MIGRATIONS:
            try:
                await session.execute(text(sql))
                await session.commit()
                logger.debug("db.migration_applied", item=desc)
            except Exception as e:
                await session.rollback()
                err = str(e)
                if "already exists" not in err:
                    logger.warning("db.migration_failed", item=desc, error=err)

    logger.info("db.migrations_done", count=len(_MIGRATIONS))

-- 冷启动建表（架构方案 scripts/init_db.sql：容器首次启动自动执行）
-- 注意：DDL 与 backend/db/migrations.py 保持一致（同增同改），全部 IF NOT EXISTS 幂等
-- 应用侧启动时也会跑 migrations.py，双保险不冲突

-- 部门
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(128) NOT NULL UNIQUE,
    parent_id INTEGER,
    manager_id INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 员工/账号
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    real_name VARCHAR(64),
    email VARCHAR(128),
    phone VARCHAR(32),
    department_id INTEGER REFERENCES departments(id),
    role VARCHAR(16) NOT NULL DEFAULT 'employee',  -- employee/approver/finance/admin
    tenant_id VARCHAR(64) NOT NULL DEFAULT 'tenant_default',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 差旅申请单
CREATE TABLE IF NOT EXISTS travel_requests (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    title VARCHAR(256),
    status VARCHAR(16) NOT NULL DEFAULT 'draft',  -- draft/pending/approved/rejected
    trip_type VARCHAR(16),                        -- visit/meeting/project/entertain
    departure_city VARCHAR(64),
    arrival_city VARCHAR(64),
    start_date DATE,
    end_date DATE,
    reason TEXT,
    estimated_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    itinerary JSONB,
    approver_id INTEGER,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_travel_requests_user_status ON travel_requests (user_id, status);
CREATE INDEX IF NOT EXISTS idx_travel_requests_status_created ON travel_requests (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_department ON users (department_id);

-- 报销单（审核 R-21：与 migrations.py 同步，之前遗漏）
CREATE TABLE IF NOT EXISTS reimbursements (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    travel_request_id INTEGER REFERENCES travel_requests(id),
    title VARCHAR(256),
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    current_step INTEGER NOT NULL DEFAULT 1,
    total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    approver_id INTEGER,
    finance_reviewer_id INTEGER,
    paid_at TIMESTAMPTZ,
    reject_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 审批留痕（差旅申请+报销共用）
CREATE TABLE IF NOT EXISTS approvals (
    id SERIAL PRIMARY KEY,
    biz_type VARCHAR(16) NOT NULL,
    biz_id INTEGER NOT NULL,
    step INTEGER NOT NULL DEFAULT 1,
    approver_id INTEGER,
    action VARCHAR(16) NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reimbursements_user_status ON reimbursements (user_id, status);
CREATE INDEX IF NOT EXISTS idx_approvals_biz ON approvals (biz_type, biz_id);

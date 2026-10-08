# 灌种子数据
# scripts/seed_data.py
# 执行：python -m scripts.seed_data（.env.local 指向可用 PG）
# 用途：
#   ① seed_all()       部门 + 四角色账号（幂等 ON CONFLICT DO NOTHING，可重复执行）
#   ② seed_demo_data() 10 人份全链路演示数据（差旅申请/审批留痕/报销单/发票/对话历史）
# 参考 EduAgent scripts/seed_data.py：asyncpg 直连 + 密码 bcrypt 哈希绝不存明文

import asyncio
import random
import sys
from datetime import date, timedelta

import asyncpg  # PostgreSQL 异步驱动（脚本直接用它，简单直接）
import bcrypt as _b
import types as _t
from passlib.context import CryptContext

from backend.config import get_settings

# 兼容性补丁：同 auth.py，让 passlib 能读到 bcrypt 版本
if not hasattr(_b, "__about__"):
    _b.__about__ = _t.SimpleNamespace(__version__=getattr(_b, "__version__", "4.x"))

s = get_settings()
if s.app_env == "prod":
    # 审核 R-08：弱演示密码只允许在非生产环境灌入
    raise RuntimeError("禁止在生产环境运行种子脚本（演示账号密码为弱口令，仅本地开发用）")

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

# ── 演示数据配置（seed_demo_data 专用）──────────────────────────
# 10 名演示员工：姓名 / username / 部门（5 个注册部门各 2 人）
DEMO_EMPLOYEES = [
    ("李娜", "demo01", "幕墙设计部"),
    ("王强", "demo02", "幕墙设计部"),
    ("刘洋", "demo03", "BIM部"),
    ("陈晓", "demo04", "BIM部"),
    ("杨帆", "demo05", "内装部"),
    ("赵磊", "demo06", "内装部"),
    ("黄敏", "demo07", "城市更新部"),
    ("周涛", "demo08", "城市更新部"),
    ("吴倩", "demo09", "综合业务部"),
    ("徐明", "demo10", "综合业务部"),
]
DEMO_PASSWORD = "Demo@123456"  # 演示账号统一密码（仅 dev 环境）

_TRIP_TYPES = ["visit", "meeting", "project", "entertain"]
_CITIES = ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "西安"]
_SELLERS = ["杭州云启科技有限公司", "上海锦江国际酒店管理有限公司", "广州白云机场商旅服务有限公司",
            "深圳智行商务服务有限公司", "北京中关村科技发展有限公司"]


async def seed_all() -> None:
    """灌入部门 + 测试账号（已存在则跳过），并打印账号清单。

    打印明文密码仅本地开发方便复制（生产禁跑，见模块级守卫）。
    """
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
        print("✅ 种子账号灌入完成（已存在则跳过）")
        for u in SEED_USERS:
            print(f"   {u['username']:<10} / {u['pwd']:<16} 角色={u['role']:<9} 部门={u['dept'] or '（无）'}")
    finally:
        await conn.close()


async def seed_demo_data() -> None:
    """灌 10 人份全链路演示数据：差旅申请 → 审批留痕 → 报销单 → 发票 → 对话历史。

    幂等策略（审核 R-03 同款）：
    - TRUNCATE 五张业务表（travel_requests/reimbursements/approvals/invoices/chat_messages）
    - 演示员工（demo01~demo10）DELETE 后重建；种子账号不动
    - 随机数固定 seed=42，重复执行结果一致可复现
    """
    rng = random.Random(42)
    # 先跑幂等迁移（确保 invoices 等新表已建，依赖 backend.db.migrations）
    from backend.db.migrations import run_migrations

    await run_migrations()

    conn = await asyncpg.connect(DB_DSN)
    try:
        # ── ① 清理（业务表全清 + 演示员工删除重建；种子账号不动）──
        await conn.execute(
            "TRUNCATE travel_requests, reimbursements, approvals, invoices, chat_messages "
            "RESTART IDENTITY CASCADE"
        )
        await conn.execute("DELETE FROM users WHERE username LIKE 'demo%'")

        # 注册白名单五部门幂等落库（仅注册过的才在表里，demo 员工分布其中）
        for dept in ("幕墙设计部", "BIM部", "内装部", "城市更新部", "综合业务部"):
            await conn.execute(
                "INSERT INTO departments (name) VALUES ($1) ON CONFLICT (name) DO NOTHING", dept)

        # ── ② 部门 / 审批角色回查 ──
        dept_ids = {r["name"]: r["id"] for r in await conn.fetch("SELECT id, name FROM departments")}
        approver_id = await conn.fetchval("SELECT id FROM users WHERE username = 'lium'")
        finance_id = await conn.fetchval("SELECT id FROM users WHERE username = 'wangcai'")

        # ── ③ 插 10 名演示员工 ──
        pwd_hash = pwd_context.hash(DEMO_PASSWORD)
        user_ids: dict[str, int] = {}
        for real_name, username, dept in DEMO_EMPLOYEES:
            uid = await conn.fetchval(
                "INSERT INTO users (username, password_hash, real_name, department_id, role) "
                "VALUES ($1, $2, $3, $4, 'employee') RETURNING id",
                username, pwd_hash, real_name, dept_ids[dept],
            )
            user_ids[username] = uid

        # ── ④ 每人 3 条差旅申请（approved 历史 / pending 本月 / draft|rejected）──
        today = date.today()
        trip_statuses: dict[int, str] = {}
        trip_amounts: dict[int, float] = {}
        for idx, (real_name, username, dept) in enumerate(DEMO_EMPLOYEES):
            uid = user_ids[username]
            trip_type = _TRIP_TYPES[idx % len(_TRIP_TYPES)]
            # 1) approved：过去 2~5 个月（月度趋势有历史数据）
            start1 = today - timedelta(days=rng.randint(60, 150))
            amount1 = rng.randint(15, 80) * 100
            tr1 = await conn.fetchrow(
                "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
                "start_date, end_date, reason, estimated_amount, approver_id) "
                "VALUES ($1, $2, 'approved', $3, '北京', $4, $5, $6, $7, $8, $9) RETURNING id",
                uid, f"{_CITIES[idx % len(_CITIES)]}客户拜访", trip_type,
                _CITIES[idx % len(_CITIES)], start1, start1 + timedelta(days=rng.randint(2, 5)),
                "拜访客户/项目洽谈", amount1, approver_id,
            )
            trip_statuses[tr1["id"]] = "approved"
            trip_amounts[tr1["id"]] = amount1

            # 2) pending：本月（审批中心有待办）
            start2 = today + timedelta(days=rng.randint(5, 20))
            amount2 = rng.randint(15, 80) * 100
            tr2 = await conn.fetchrow(
                "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
                "start_date, end_date, reason, estimated_amount) "
                "VALUES ($1, $2, 'pending', $3, '北京', $4, $5, $6, $7, $8) RETURNING id",
                uid, f"{_CITIES[(idx + 1) % len(_CITIES)]}项目出差", _TRIP_TYPES[(idx + 1) % len(_TRIP_TYPES)],
                _CITIES[(idx + 1) % len(_CITIES)], start2, start2 + timedelta(days=rng.randint(3, 7)),
                "项目驻场/会议", amount2,
            )
            trip_statuses[tr2["id"]] = "pending"
            trip_amounts[tr2["id"]] = amount2

            # 3) draft 或 rejected 交替
            status3 = "draft" if idx % 2 == 0 else "rejected"
            start3 = today - timedelta(days=rng.randint(5, 45))
            amount3 = rng.randint(15, 80) * 100
            tr3 = await conn.fetchrow(
                "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
                "start_date, end_date, reason, estimated_amount, reject_reason) "
                "VALUES ($1, $2, $3, $4, '北京', $5, $6, $7, $8, $9, $10) RETURNING id",
                uid, f"{_CITIES[(idx + 2) % len(_CITIES)]}会议出差", status3,
                _TRIP_TYPES[(idx + 2) % len(_TRIP_TYPES)],
                _CITIES[(idx + 2) % len(_CITIES)], start3, start3 + timedelta(days=rng.randint(2, 4)),
                "参加会议", amount3,
                "预算超标，请缩减行程" if status3 == "rejected" else None,
            )
            trip_statuses[tr3["id"]] = status3
            trip_amounts[tr3["id"]] = amount3

        # ── ⑤ 差旅审批留痕（approved/rejected 各一条）──
        for tr_id, status in trip_statuses.items():
            if status == "approved":
                await conn.execute(
                    "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
                    "VALUES ('travel', $1, 1, $2, 'approve', '同意，注意控制费用')",
                    tr_id, approver_id,
                )
            elif status == "rejected":
                await conn.execute(
                    "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
                    "VALUES ('travel', $1, 1, $2, 'reject', '预算超标，请缩减行程')",
                    tr_id, approver_id,
                )

        # ── ⑥ 每人 2 条报销单（approved 挂发票 / pending step1|step2 待审）──
        reimbs: list[tuple] = []  # (reimb_id, user_id, status, amount, created_date)
        for idx, (real_name, username, dept) in enumerate(DEMO_EMPLOYEES):
            uid = user_ids[username]
            approved_trip = await conn.fetchval(
                "SELECT id FROM travel_requests WHERE user_id = $1 AND status = 'approved' LIMIT 1", uid
            )
            amount1 = trip_amounts.get(approved_trip, 3000)
            rb1 = await conn.fetchrow(
                "INSERT INTO reimbursements (user_id, travel_request_id, title, status, current_step, "
                "total_amount, approver_id, finance_reviewer_id) "
                "VALUES ($1, $2, $3, 'approved', 2, $4, $5, $6) RETURNING id, created_at",
                uid, approved_trip, f"{real_name}差旅报销", amount1, approver_id, finance_id,
            )
            step = 1 if idx % 2 == 0 else 2
            pending_trip = await conn.fetchval(
                "SELECT id FROM travel_requests WHERE user_id = $1 AND status = 'pending' LIMIT 1", uid
            )
            amount2 = trip_amounts.get(pending_trip, 4000) if pending_trip else 4000
            rb2 = await conn.fetchrow(
                "INSERT INTO reimbursements (user_id, travel_request_id, title, status, current_step, total_amount) "
                "VALUES ($1, $2, $3, 'pending', $4, $5) RETURNING id",
                uid, pending_trip, f"{real_name}住宿交通报销", step, amount2,
            )
            reimbs.append((rb1["id"], uid, "approved", amount1, rb1["created_at"].date()))
            reimbs.append((rb2["id"], uid, "pending", amount2, None))

        # ── ⑦ 报销审批留痕 ──
        for rb_id, uid, status, amount, inv_date in reimbs:
            if status == "approved":
                await conn.execute(
                    "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
                    "VALUES ('reimbursement', $1, 1, $2, 'approve', '同意报销')", rb_id, approver_id)
                await conn.execute(
                    "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
                    "VALUES ('reimbursement', $1, 2, $2, 'approve', '票据合规，予以报销')", rb_id, finance_id)
            else:
                step_row = await conn.fetchrow(
                    "SELECT current_step FROM reimbursements WHERE id = $1", rb_id)
                if step_row and step_row["current_step"] == 2:
                    await conn.execute(
                        "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
                        "VALUES ('reimbursement', $1, 1, $2, 'approve', '同意，转财务复核')", rb_id, approver_id)

        # ── ⑧ 发票：每个 approved 报销单挂 1 张（invoice_number 唯一）──
        for seq, (rb_id, uid, status, amount, inv_date) in enumerate(
            r for r in reimbs if r[2] == "approved"
        ):
            await conn.execute(
                "INSERT INTO invoices (user_id, reimbursement_id, file_type, invoice_type, invoice_number, "
                "amount, tax_amount, total_amount, seller_name, buyer_name, invoice_date, "
                "ocr_status, ocr_confidence, is_verified) "
                "VALUES ($1, $2, 'pdf', '增值税电子普通发票', $3, $4, $5, $4, $6, $7, $8, "
                "'parsed', 0.98, TRUE)",
                uid, rb_id, f"0440321{seq:06d}21", amount, round(amount * 0.06, 2),
                _SELLERS[seq % len(_SELLERS)], "北京智行科技有限公司", inv_date,
            )

        # ── ⑨ 对话历史：每人 2 轮（4 条）──
        for idx, (real_name, username, dept) in enumerate(DEMO_EMPLOYEES):
            uid = user_ids[username]
            city = _CITIES[idx % len(_CITIES)]
            sid = f"user_{uid}"
            await conn.execute(
                "INSERT INTO chat_messages (user_id, session_id, role, content) "
                "VALUES ($1, $2, 'user', $3)", uid, sid, f"我下周要去{city}出差三天，帮我安排行程")
            await conn.execute(
                "INSERT INTO chat_messages (user_id, session_id, role, content) "
                "VALUES ($1, $2, 'assistant', $3)", uid, sid,
                f"已为您生成差旅申请单草稿：北京 → {city}，含推荐车次与酒店，请确认后提交审批。")
            await conn.execute(
                "INSERT INTO chat_messages (user_id, session_id, role, content) "
                "VALUES ($1, $2, 'user', $3)", uid, sid, "这张住宿发票能报销吗")
            await conn.execute(
                "INSERT INTO chat_messages (user_id, session_id, role, content, guidance) "
                "VALUES ($1, $2, 'assistant', '', $3::jsonb)", uid, sid,
                '[{"message": "检测到您需要办理发票报销。请前往「报销」页面上传发票（PDF/JPG/PNG），系统将自动识别发票信息并生成报销单提交审批。", '
                '"action_label": "前往发票报销", "action_url": "/reimbursement"}]',
            )

        # ── ⑩ 统计打印 ──
        print("✅ 10 人份演示数据灌入完成：")
        for table in ("users", "departments", "travel_requests", "reimbursements",
                      "approvals", "invoices", "chat_messages"):
            n = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            print(f"   {table:<18} {n} 条")
        print(f"   演示账号：demo01~demo10 / {DEMO_PASSWORD}（employee）")
    finally:
        await conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(seed_all())
    asyncio.run(seed_demo_data())

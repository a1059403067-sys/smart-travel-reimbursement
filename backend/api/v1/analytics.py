# 固定统计报表接口（架构方案模块 6：api/v1/analytics.py）
#
# GET /api/travel/stats：总出差人次 / 总费用 / 各部门招待费占比。
#
# 返回结构对齐 ECharts 直接渲染：
#   {
#     "summary": {"total_trips": 8, "total_amount": 30450.0},        ← 前端数字卡片直接用
#     "department_expense": [                                        ← 饼图 series.data 直接用
#       {"name": "研发部", "value": 11650.0, "percentage": 38.3},
#       ...
#     ]
#   }
#   ECharts 饼图原生支持 {name, value} 数组；percentage 为附加字段（tooltip 展示用），
#   不参与渲染，不影响 ECharts 解析。
#
# 口径说明：统计范围 = travel_requests（差旅申请单）。
#   - 总出差人次 = 申请单数量（COUNT）
#   - 总费用 = estimated_amount 合计（价税口径下 NUMERIC(12,2)，返回 float 供图表直接使用）
#   - 招待费占比 = 各部门费用占比（可加 ?trip_type=entertain 只统计招待类行程）
#     注意：表当前无"费用类型"字段，招待费以 trip_type 区分，默认统计全部行程类型。

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import get_logger
from backend.dependencies import get_db

logger = get_logger(__name__)

router = APIRouter(prefix="/api/travel", tags=["差旅统计"])

# trip_type → 中文名（Dashboard 直接展示，前端不再翻译）
_TRIP_TYPE_LABELS = {
    "visit": "客户拜访",
    "meeting": "会议",
    "project": "项目驻场",
    "entertain": "招待",
}

# 月度趋势窗口：近 6 个月（含当月）
_TREND_MONTHS = 6

# 报销单状态 → 中文名（Dashboard 首页状态分布，契约 REQ-1 五类固定）
_REIMB_STATUS_LABELS = {
    "draft": "草稿", "pending": "待审批", "approved": "已通过",
    "rejected": "已驳回", "paid": "已付款",
}


def _percentage(value: float, total: float) -> float:
    """占比：总额为 0 时记 0，避免除零。"""
    return round(value * 100 / total, 1) if total else 0.0


@router.get("/stats", summary="差旅统计（总出差人次 / 总费用 / 各部门招待费占比）")
async def travel_stats(
    trip_type: str | None = Query(default=None, description="行程类型过滤：entertain=招待，默认统计全部"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """固定报表聚合查询（三条只读 SQL，一次请求内完成）。"""
    # trip_type 走参数绑定，防注入
    where_sql = "WHERE tr.trip_type = :trip_type" if trip_type else ""
    params = {"trip_type": trip_type} if trip_type else {}

    # ① 总出差人次 + 总费用（一次往返拿两个标量）
    row = (
        await db.execute(
            text(
                f"""
                SELECT COUNT(*) AS trips, COALESCE(SUM(tr.estimated_amount), 0) AS amount
                FROM travel_requests tr
                {where_sql}
                """
            ),
            params,
        )
    ).one()
    total_trips: int = int(row.trips or 0)
    total_amount: float = round(float(row.amount or 0), 2)

    # ② 各部门招待费占比（LEFT JOIN users → departments，孤儿/未分配部门兜底，与卡片口径一致）
    rows = (
        await db.execute(
            text(
                f"""
                SELECT COALESCE(d.name, '未分配部门') AS department,
                       COALESCE(SUM(tr.estimated_amount), 0) AS amount
                FROM travel_requests tr
                LEFT JOIN users u ON tr.user_id = u.id
                LEFT JOIN departments d ON u.department_id = d.id
                {where_sql}
                GROUP BY d.name
                ORDER BY amount DESC
                """
            ),
            params,
        )
    ).all()

    department_expense = []
    for r in rows:
        value = round(float(r.amount or 0), 2)
        department_expense.append(
            {
                "name": r.department,
                "value": value,
                "percentage": _percentage(value, total_amount),
            }
        )

    logger.info("stats.travel_queried", total_trips=total_trips, total_amount=total_amount,
                departments=len(department_expense), trip_type=trip_type or "all")

    return {
        "summary": {"total_trips": total_trips, "total_amount": total_amount},
        "department_expense": department_expense,
    }


@router.get("/dashboard", summary="Dashboard 聚合（REQ-1）：卡片 + 部门饼图 + 月度趋势 + 费用类型")
async def travel_dashboard(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """前端 Dashboard 页一次请求拿全四块数据，ECharts 结构直接渲染：

    - summary          数字卡片（总人次/总费用/待审批/本月新增）
    - department_expense  饼图（各部门费用占比，同 /stats）
    - monthly_trend    折线（近 6 个月人次+金额，缺月补 0）
    - expense_by_type  柱状/饼图（行程类型费用占比，name 为中文）
    """
    # ① summary 卡片（FILTER 子句一次聚合，避免多条 SQL）
    row = (
        await db.execute(
            text(
                """
                SELECT COUNT(*) AS trips,
                       COALESCE(SUM(estimated_amount), 0) AS amount,
                       COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                       COUNT(*) FILTER (WHERE created_at >= date_trunc('month', NOW())) AS month_new
                FROM travel_requests
                """
            )
        )
    ).one()
    total_amount: float = round(float(row.amount or 0), 2)

    # ② 部门占比（与 /stats 同口径，LEFT JOIN 兜底）
    dept_rows = (
        await db.execute(
            text(
                """
                SELECT COALESCE(d.name, '未分配部门') AS department,
                       COALESCE(SUM(tr.estimated_amount), 0) AS amount
                FROM travel_requests tr
                LEFT JOIN users u ON tr.user_id = u.id
                LEFT JOIN departments d ON u.department_id = d.id
                GROUP BY d.name
                ORDER BY amount DESC
                """
            )
        )
    ).all()
    department_expense = [
        {
            "name": r.department,
            "value": (v := round(float(r.amount or 0), 2)),
            "percentage": _percentage(v, total_amount),
        }
        for r in dept_rows
    ]

    # ③ 月度趋势：generate_series 生成近 6 个月轴，LEFT JOIN 补缺月为 0
    trend_rows = (
        await db.execute(
            text(
                """
                SELECT to_char(m.month, 'YYYY-MM') AS month,
                       COUNT(tr.id)::int AS trips,
                       COALESCE(SUM(tr.estimated_amount), 0) AS amount
                FROM generate_series(
                         date_trunc('month', NOW()) - make_interval(months => :months - 1),
                         date_trunc('month', NOW()),
                         interval '1 month'
                     ) AS m(month)
                LEFT JOIN travel_requests tr ON date_trunc('month', tr.start_date) = m.month
                GROUP BY m.month
                ORDER BY m.month
                """
            ),
            {"months": _TREND_MONTHS},
        )
    ).all()
    monthly_trend = [
        {"month": r.month, "trips": int(r.trips), "amount": round(float(r.amount or 0), 2)}
        for r in trend_rows
    ]

    # ④ 费用类型占比（trip_type 中文名映射）
    type_rows = (
        await db.execute(
            text(
                """
                SELECT trip_type, COALESCE(SUM(estimated_amount), 0) AS amount
                FROM travel_requests
                GROUP BY trip_type
                ORDER BY amount DESC
                """
            )
        )
    ).all()
    expense_by_type = [
        {
            "name": _TRIP_TYPE_LABELS.get(r.trip_type, r.trip_type or "其他"),
            "value": (v := round(float(r.amount or 0), 2)),
            "percentage": _percentage(v, total_amount),
        }
        for r in type_rows
    ]

    # ⑤ 报销单状态分布（会话 B 请求：首页五类固定，缺类补 0）
    rb_status_rows = (
        await db.execute(
            text("SELECT status, COUNT(*) AS cnt FROM reimbursements GROUP BY status")
        )
    ).all()
    rb_counts = {r.status: int(r.cnt) for r in rb_status_rows}
    reimbursement_status = [
        {"name": label, "value": rb_counts.get(key, 0)}
        for key, label in _REIMB_STATUS_LABELS.items()
    ]

    logger.info("stats.dashboard_queried", trips=row.trips, amount=total_amount,
                trend_months=len(monthly_trend), types=len(expense_by_type),
                reimb_statuses=len(reimbursement_status))

    return {
        "summary": {
            "total_trips": int(row.trips or 0),
            "total_amount": total_amount,
            "pending_approvals": int(row.pending or 0),
            "month_new_trips": int(row.month_new or 0),
        },
        "department_expense": department_expense,
        "monthly_trend": monthly_trend,
        "expense_by_type": expense_by_type,
        "reimbursement_status": reimbursement_status,
    }


if __name__ == "__main__":
    # 离线自测：真库建表 + 种子数据 + httpx 直调接口（不经过网络层）
    # 前提：.env.local 指向可用的 PG（可用环境变量覆盖 DB_USER/DB_PASSWORD）
    import asyncio
    import json
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    from sqlalchemy import text as sql_text

    from backend.config import get_settings
    from backend.db.migrations import run_migrations

    async def _seed(db) -> None:
        """自测种子：只清 travel_requests（CASCADE 连带清 reimbursements/approvals）。

        ⚠️ 绝不 TRUNCATE users/departments——会清掉 seed_data.py 的正式种子账号
        （2026-10-08 双会话事故：另一窗口跑本自测清空了账号表）。
        部门/演示用户用 ON CONFLICT DO NOTHING 幂等插入 + 回查 id 引用。
        """
        await db.execute(sql_text(
            "TRUNCATE travel_requests RESTART IDENTITY CASCADE"
        ))
        # 部门（幂等，回查 id）
        await db.execute(sql_text(
            "INSERT INTO departments (name) VALUES ('研发部'), ('市场部'), ('销售部') "
            "ON CONFLICT (name) DO NOTHING"
        ))
        dept_ids = {
            r.name: int(r.id)
            for r in (await db.execute(sql_text("SELECT id, name FROM departments"))).all()
        }
        # 演示员工（幂等；密码哈希占位，仅统计自测用）
        demo_users = [
            ("zhangsan", "张三", "研发部"), ("lisi", "李四", "研发部"),
            ("wangwu", "王五", "市场部"), ("sunqi", "孙七", "市场部"),
            ("zhaoliu", "赵六", "销售部"),
        ]
        for username, real_name, dept in demo_users:
            await db.execute(sql_text(
                "INSERT INTO users (username, password_hash, real_name, department_id, role) "
                "VALUES (:u, 'x', :r, :d, 'employee') ON CONFLICT (username) DO NOTHING"
            ), {"u": username, "r": real_name, "d": dept_ids[dept]})
        user_ids = {
            r.username: int(r.id)
            for r in (await db.execute(sql_text("SELECT id, username FROM users"))).all()
        }
        # 差旅申请单（user_id 用回查值，不写死；trip_type: visit/meeting/project/entertain）
        trips = [
            ("zhangsan", "拜访杭州客户", "visit", "北京", "杭州", "2026-10-12", "2026-10-14", 3200.00),
            ("zhangsan", "杭州项目驻场", "project", "北京", "杭州", "2026-11-02", "2026-11-13", 5800.00),
            ("lisi", "参加深圳技术峰会", "meeting", "北京", "深圳", "2026-10-20", "2026-10-22", 2650.00),
            ("wangwu", "上海客户招待", "entertain", "北京", "上海", "2026-10-15", "2026-10-16", 4800.00),
            ("sunqi", "广州客户答谢", "entertain", "北京", "广州", "2026-10-25", "2026-10-27", 3600.00),
            ("zhaoliu", "成都商务洽谈", "visit", "北京", "成都", "2026-10-18", "2026-10-19", 5200.00),
            ("zhaoliu", "重庆客户招待", "entertain", "北京", "重庆", "2026-11-05", "2026-11-06", 2100.00),
            ("wangwu", "杭州市场活动", "meeting", "北京", "杭州", "2026-11-08", "2026-11-10", 3100.00),
        ]
        from datetime import date as _date  # asyncpg 新版 DATE 列必须传 date 对象，str 会报错

        for username, title, ttype, dep, arr, sdate, edate, amount in trips:
            # 注意：title/reason 同值也必须分开传参，同一参数用于 VARCHAR 和 TEXT 两列会类型推断冲突
            await db.execute(sql_text(
                "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
                "start_date, end_date, reason, estimated_amount) VALUES "
                "(:uid, :title, 'approved', :ttype, :dep, :arr, :sdate, :edate, :reason, :amount)"
            ), {"uid": user_ids[username], "title": title, "ttype": ttype,
                "dep": dep, "arr": arr, "sdate": _date.fromisoformat(sdate), "edate": _date.fromisoformat(edate),
                "reason": title, "amount": amount})
        await db.commit()
        return user_ids

    async def main():
        # 审核 R-03：破坏性自测（TRUNCATE）仅允许 dev 环境，防生产误跑清库
        if get_settings().app_env != "dev":
            raise RuntimeError("本自测含 TRUNCATE，仅允许在 app_env=dev 环境运行")

        # ① 建表（幂等） + 种子
        await run_migrations()
        from backend.dependencies import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            user_ids = await _seed(db)

        # ② httpx 直调 ASGI 应用（不走网络，验证路由与响应）
        import httpx

        from backend.main import app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            print("=" * 60)
            print("GET /api/travel/stats（全部行程）")
            print("=" * 60)
            resp = await client.get("/api/travel/stats")
            data = resp.json()
            print(json.dumps(data, ensure_ascii=False, indent=2))
            assert resp.status_code == 200
            assert data["summary"]["total_trips"] == 8
            assert abs(data["summary"]["total_amount"] - 30450.0) < 0.01
            assert data["department_expense"][0]["name"] == "研发部"
            assert abs(data["department_expense"][0]["percentage"] - 38.3) < 0.1

            print("\n" + "=" * 60)
            print("GET /api/travel/stats?trip_type=entertain（只统计招待费）")
            print("=" * 60)
            resp2 = await client.get("/api/travel/stats", params={"trip_type": "entertain"})
            data2 = resp2.json()
            print(json.dumps(data2, ensure_ascii=False, indent=2))
            assert data2["summary"]["total_trips"] == 3
            assert abs(data2["summary"]["total_amount"] - 10500.0) < 0.01

            # ③ 追加 2 条待审批申请（本月出发），验证 dashboard 的 pending/趋势卡片
            async with AsyncSessionLocal() as db:
                await db.execute(sql_text(
                    "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
                    "start_date, end_date, reason, estimated_amount) VALUES "
                    "(:u1, '杭州项目二期驻场', 'pending', 'project', '北京', '杭州', CURRENT_DATE, CURRENT_DATE + 10, '项目驻场', 6800.00), "
                    "(:u2, '深圳客户拜访', 'pending', 'visit', '北京', '深圳', CURRENT_DATE, CURRENT_DATE + 2, '拜访客户', 2950.00)"
                ), {"u1": user_ids["lisi"], "u2": user_ids["sunqi"]})
                await db.commit()

            print("\n" + "=" * 60)
            print("GET /api/travel/dashboard（REQ-1：卡片 + 饼图 + 趋势 + 类型）")
            print("=" * 60)
            resp3 = await client.get("/api/travel/dashboard")
            d = resp3.json()
            print(json.dumps(d, ensure_ascii=False, indent=2))
            assert resp3.status_code == 200
            # 卡片：8 条种子 + 2 条 pending；种子 created_at 均为 NOW() → 本月新建 = 10
            assert d["summary"]["total_trips"] == 10
            assert d["summary"]["pending_approvals"] == 2
            assert d["summary"]["month_new_trips"] == 10
            # 趋势：恰好 6 个月；当月 = 种子 5 条(10月出发) + 2 条 pending = 7
            assert len(d["monthly_trend"]) == 6
            assert d["monthly_trend"][-1]["trips"] == 7
            # 类型：中文名 + 4 类（visit/meeting/project/entertain）
            names = [t["name"] for t in d["expense_by_type"]]
            assert set(names) == {"客户拜访", "会议", "项目驻场", "招待"}
            print("\n断言通过 ✅：stats 与 dashboard 返回结构与 ECharts 渲染格式一致")

    asyncio.run(main())

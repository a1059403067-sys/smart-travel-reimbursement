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

    # ② 各部门招待费占比（JOIN users → departments，未分配部门的兜底为"未分配部门"）
    rows = (
        await db.execute(
            text(
                f"""
                SELECT COALESCE(d.name, '未分配部门') AS department,
                       COALESCE(SUM(tr.estimated_amount), 0) AS amount
                FROM travel_requests tr
                JOIN users u ON tr.user_id = u.id
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
                # 占比：总额为 0 时记 0，避免除零
                "percentage": round(value * 100 / total_amount, 1) if total_amount else 0.0,
            }
        )

    logger.info("stats.travel_queried", total_trips=total_trips, total_amount=total_amount,
                departments=len(department_expense), trip_type=trip_type or "all")

    return {
        "summary": {"total_trips": total_trips, "total_amount": total_amount},
        "department_expense": department_expense,
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

    _SEED_SQL = [
        # 部门
        "INSERT INTO departments (name) VALUES ('研发部'), ('市场部'), ('销售部') "
        "ON CONFLICT (name) DO NOTHING",
        # 员工（密码哈希为占位，鉴权模块实现后替换）
        "INSERT INTO users (username, password_hash, real_name, department_id, role) VALUES "
        "('zhangsan', 'x', '张三', 1, 'employee'), "
        "('lisi', 'x', '李四', 1, 'employee'), "
        "('wangwu', 'x', '王五', 2, 'employee'), "
        "('sunqi', 'x', '孙七', 2, 'employee'), "
        "('zhaoliu', 'x', '赵六', 3, 'employee') "
        "ON CONFLICT (username) DO NOTHING",
        # 差旅申请单（trip_type: visit 拜访 / meeting 会议 / project 驻场 / entertain 招待）
        "INSERT INTO travel_requests (user_id, title, status, trip_type, departure_city, arrival_city, "
        "start_date, end_date, reason, estimated_amount) VALUES "
        "(1, '拜访杭州客户', 'approved', 'visit', '北京', '杭州', '2026-10-12', '2026-10-14', '拜访客户', 3200.00), "
        "(1, '杭州项目驻场', 'approved', 'project', '北京', '杭州', '2026-11-02', '2026-11-13', '项目驻场', 5800.00), "
        "(2, '参加深圳技术峰会', 'approved', 'meeting', '北京', '深圳', '2026-10-20', '2026-10-22', '参加会议', 2650.00), "
        "(3, '上海客户招待', 'approved', 'entertain', '北京', '上海', '2026-10-15', '2026-10-16', '客户招待', 4800.00), "
        "(4, '广州客户答谢', 'approved', 'entertain', '北京', '广州', '2026-10-25', '2026-10-27', '客户招待', 3600.00), "
        "(5, '成都商务洽谈', 'approved', 'visit', '北京', '成都', '2026-10-18', '2026-10-19', '商务洽谈', 5200.00), "
        "(5, '重庆客户招待', 'approved', 'entertain', '北京', '重庆', '2026-11-05', '2026-11-06', '客户招待', 2100.00), "
        "(3, '杭州市场活动', 'approved', 'meeting', '北京', '杭州', '2026-11-08', '2026-11-10', '市场活动', 3100.00) "
        "ON CONFLICT DO NOTHING",
    ]

    async def _seed(db) -> None:
        # 自测环境先清空三表（保证重复运行断言一致）；生产路径由 seed_data.py 幂等脚本负责
        await db.execute(sql_text(
            "TRUNCATE travel_requests, users, departments RESTART IDENTITY CASCADE"
        ))
        for sql in _SEED_SQL:
            await db.execute(sql_text(sql))
        await db.commit()

    async def main():
        # ① 建表（幂等） + 种子
        await run_migrations()
        from backend.dependencies import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await _seed(db)

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
            print("\n断言通过 ✅：接口返回结构与 ECharts 渲染格式一致")

    asyncio.run(main())

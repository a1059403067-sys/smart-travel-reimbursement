# 差旅申请管理（架构方案 P1：api/v1/travel.py —— 申请 CRUD/提交/审批）
#
# 契约见 接口契约.md REQ-6。状态机：draft → pending → approved / rejected（单级审批）。
# 实现模式与 REQ-8 报销单一致（审核已复核通过的模式）：
#   - 归属按 user_id 隔离；审批 require_role("approver", "admin")
#   - 状态变更用条件 UPDATE 原子化（rowcount=0 → 400/409，防并发双审）
#   - 审批留痕 approvals 表（biz_type='travel'，与报销共用，架构方案 biz_type 通用设计）
#   - 架构方案 A-09 审批流已并入本文件实现，不再单独建 approval.py

from __future__ import annotations

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import get_logger
from backend.dependencies import get_current_user, get_db, require_role

logger = get_logger(__name__)

router = APIRouter(prefix="/api/travel/requests", tags=["差旅申请"])

_ALLOWED_STATUS = {"draft", "pending", "approved", "rejected"}
_SUBMITABLE_STATUS = {"draft", "rejected"}
# 审核 R-26：trip_type 枚举白名单（与 analytics._TRIP_TYPE_LABELS 保持一致）
_ALLOWED_TRIP_TYPES = {"visit", "meeting", "project", "entertain"}


class TravelRequestCreate(BaseModel):
    """创建差旅申请请求体。"""

    title: str = Field(..., min_length=1, max_length=256, description="申请单标题")
    trip_type: str | None = Field(default=None, description="行程类型：visit/meeting/project/entertain")
    departure_city: str | None = Field(default=None, max_length=64)
    arrival_city: str | None = Field(default=None, max_length=64)
    start_date: str | None = Field(default=None, description="出发日期 YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="返程日期 YYYY-MM-DD")
    reason: str | None = Field(default=None, description="出差事由")
    estimated_amount: float = Field(default=0.0, ge=0, description="预估费用")


class RejectRequest(BaseModel):
    """驳回请求体。"""

    reason: str = Field(..., min_length=1, max_length=500, description="驳回原因")


def _row_to_dict(r) -> dict:
    """行 → 前端 JSON（契约 REQ-6 列表字段）。"""
    return {
        "id": int(r.id),
        "title": r.title or "",
        "status": r.status,
        "trip_type": r.trip_type or "",
        "departure_city": r.departure_city or "",
        "arrival_city": r.arrival_city or "",
        "start_date": r.start_date.isoformat() if r.start_date else "",
        "end_date": r.end_date.isoformat() if r.end_date else "",
        "reason": r.reason or "",
        "estimated_amount": round(float(r.estimated_amount or 0), 2),
        "user_id": int(r.user_id),
        "user_name": r.user_name or "",
        "department": r.department or "",
        "reject_reason": r.reject_reason or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
    }


_BASE_SELECT = """
    SELECT tr.id, tr.title, tr.status, tr.trip_type, tr.departure_city, tr.arrival_city,
           tr.start_date, tr.end_date, tr.reason, tr.estimated_amount,
           tr.user_id, u.real_name AS user_name, d.name AS department,
           tr.reject_reason, tr.created_at, tr.updated_at
    FROM travel_requests tr
    LEFT JOIN users u ON tr.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
"""


async def _fetch_one_or_404(db: AsyncSession, rid: int, current_user: dict) -> dict:
    """取单张申请（本人/admin/审批角色可见），不存在或越权一律 404。"""
    row = (await db.execute(text(_BASE_SELECT + " WHERE tr.id = :rid"), {"rid": rid})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="差旅申请不存在")
    role = current_user["role"]
    if str(row.user_id) != current_user["user_id"] and role not in ("approver", "finance", "admin"):
        raise HTTPException(status_code=404, detail="差旅申请不存在")
    return _row_to_dict(row)


@router.get("", summary="差旅申请列表（我的 / 待我审批 / 状态筛选 / 分页）")
async def list_travel_requests(
    mine: bool = Query(default=True),
    to_review: bool = Query(default=False, description="待我审批列表（approver/admin）"),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列表查询：三条筛选路径互斥，SQL 全部参数绑定（与 REQ-8 同模式）。"""
    role = current_user["role"]
    if status_filter and status_filter not in _ALLOWED_STATUS:
        raise HTTPException(status_code=422, detail=f"非法状态：{status_filter}")

    conds, params = [], {"user_id": int(current_user["user_id"])}
    if to_review:
        if role not in ("approver", "admin"):
            raise HTTPException(status_code=403, detail="仅审批人/管理员可查看待审列表")
        conds.append("tr.status = 'pending'")
    elif mine:
        conds.append("tr.user_id = :user_id")
    if status_filter:
        conds.append("tr.status = :status")
        params["status"] = status_filter
    where = " WHERE " + " AND ".join(conds) if conds else ""

    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM travel_requests tr{where}"
    ), params)).scalar() or 0
    rows = (await db.execute(text(
        _BASE_SELECT + where + " ORDER BY tr.id DESC LIMIT :limit OFFSET :offset"
    ), {**params, "limit": page_size, "offset": (page - 1) * page_size})).all()

    logger.info("travel.list_queried", user_id=current_user["user_id"], total=total, to_review=to_review)
    return {"items": [_row_to_dict(r) for r in rows], "total": int(total),
            "page": page, "page_size": page_size}


@router.get("/{rid}", summary="差旅申请详情（含审批留痕）")
async def get_travel_request(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    item = await _fetch_one_or_404(db, rid, current_user)
    approval_rows = (await db.execute(text(
        """
        SELECT a.step, a.action, a.comment, a.created_at, u.real_name AS approver_name
        FROM approvals a LEFT JOIN users u ON a.approver_id = u.id
        WHERE a.biz_type = 'travel' AND a.biz_id = :rid
        ORDER BY a.id
        """
    ), {"rid": rid})).all()
    item["approvals"] = [
        {
            "step": int(r.step), "action": r.action, "comment": r.comment or "",
            "approver_name": r.approver_name or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in approval_rows
    ]
    return item


@router.post("", summary="创建差旅申请（草稿）", status_code=status.HTTP_201_CREATED)
async def create_travel_request(
    req: TravelRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """创建申请；日期字符串 → date 对象（asyncpg 新版 DATE 列必须传 date）。"""
    # 审核 R-26：trip_type 枚举白名单，非法值 422
    if req.trip_type and req.trip_type not in _ALLOWED_TRIP_TYPES:
        raise HTTPException(status_code=422,
                            detail=f"非法行程类型 {req.trip_type}，可选：{'/'.join(sorted(_ALLOWED_TRIP_TYPES))}")
    try:
        start = date_type.fromisoformat(req.start_date) if req.start_date else None
        end = date_type.fromisoformat(req.end_date) if req.end_date else None
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式必须为 YYYY-MM-DD")
    # 审核 R-27：日期逻辑校验（返程不得早于出发）
    if start and end and end < start:
        raise HTTPException(status_code=422, detail="返程日期不能早于出发日期")

    rid = (await db.execute(text(
        """
        INSERT INTO travel_requests (user_id, title, trip_type, departure_city, arrival_city,
                                     start_date, end_date, reason, estimated_amount)
        VALUES (:user_id, :title, :trip_type, :dep, :arr, :start, :end, :reason, :amount)
        RETURNING id
        """
    ), {
        "user_id": int(current_user["user_id"]),
        "title": req.title,
        "trip_type": req.trip_type,
        "dep": req.departure_city,
        "arr": req.arrival_city,
        "start": start,
        "end": end,
        "reason": req.reason,
        "amount": req.estimated_amount,
    })).scalar()
    await db.commit()
    logger.info("travel.created", user_id=current_user["user_id"], id=rid)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/submit", summary="提交审批（draft/rejected → pending）")
async def submit_travel_request(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """条件 UPDATE 原子化（归属+状态双条件），并发重复提交只有一次生效。"""
    result = await db.execute(text(
        "UPDATE travel_requests SET status = 'pending', updated_at = NOW() "
        "WHERE id = :rid AND user_id = :uid AND status IN ('draft', 'rejected')"
    ), {"rid": rid, "uid": int(current_user["user_id"])})
    if result.rowcount == 0:
        row = (await db.execute(text(
            "SELECT user_id, status FROM travel_requests WHERE id = :rid"
        ), {"rid": rid})).one_or_none()
        if row is None or str(row.user_id) != current_user["user_id"]:
            raise HTTPException(status_code=404, detail="差旅申请不存在")
        raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不可提交")
    await db.commit()
    logger.info("travel.submitted", user_id=current_user["user_id"], id=rid)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/approve", summary="审批通过（单级：approver/admin）")
async def approve_travel_request(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("approver", "admin")),
):
    """pending → approved + 留痕。条件 UPDATE 原子化，并发双审一成一败。"""
    uid = int(current_user["user_id"])
    result = await db.execute(text(
        "UPDATE travel_requests SET status = 'approved', approver_id = :uid, updated_at = NOW() "
        "WHERE id = :rid AND status = 'pending'"
    ), {"uid": uid, "rid": rid})
    if result.rowcount == 0:
        row = (await db.execute(text(
            "SELECT status FROM travel_requests WHERE id = :rid"
        ), {"rid": rid})).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="差旅申请不存在")
        if row.status != "pending":
            raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不在审批中")
        await db.rollback()
        raise HTTPException(status_code=409, detail="单据状态已变化，请刷新后重试")

    await db.execute(text(
        "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action) "
        "VALUES ('travel', :rid, 1, :uid, 'approve')"
    ), {"rid": rid, "uid": uid})
    await db.commit()
    logger.info("travel.approved", approver_id=uid, id=rid)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/reject", summary="驳回（approver/admin）")
async def reject_travel_request(
    rid: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("approver", "admin")),
):
    """pending → rejected + reason + 留痕。"""
    uid = int(current_user["user_id"])
    result = await db.execute(text(
        "UPDATE travel_requests SET status = 'rejected', reject_reason = :reason, updated_at = NOW() "
        "WHERE id = :rid AND status = 'pending'"
    ), {"rid": rid, "reason": req.reason})
    if result.rowcount == 0:
        row = (await db.execute(text(
            "SELECT status FROM travel_requests WHERE id = :rid"
        ), {"rid": rid})).one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="差旅申请不存在")
        if row.status != "pending":
            raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不在审批中")
        await db.rollback()
        raise HTTPException(status_code=409, detail="单据状态已变化，请刷新后重试")

    await db.execute(text(
        "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
        "VALUES ('travel', :rid, 1, :uid, 'reject', :reason)"
    ), {"rid": rid, "uid": uid, "reason": req.reason})
    await db.commit()
    logger.info("travel.rejected", approver_id=uid, id=rid, reason=req.reason[:50])
    return await _fetch_one_or_404(db, rid, current_user)


if __name__ == "__main__":
    # 离线自测：完整状态机（创建→提交→审批→驳回→重新提交）+ 权限 + 筛选分页
    # 前提：.env.local 指向可用 PG（可用环境变量覆盖 DB_USER/DB_PASSWORD）
    import asyncio
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    async def _login(client, username: str, password: str) -> str:
        r = await client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, f"{username} 登录失败: {r.text}"
        return r.json()["access_token"]

    def _auth(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def main():
        import httpx

        from backend.config import get_settings
        from backend.db.migrations import run_migrations
        from backend.main import app

        # 破坏性自测（TRUNCATE）仅允许 dev 环境（审核 R-03 同款守卫）
        if get_settings().app_env != "dev":
            raise RuntimeError("本自测含 TRUNCATE，仅允许在 app_env=dev 环境运行")

        await run_migrations()
        from backend.dependencies import AsyncSessionLocal

        # 清空差旅申请保证断言一致；显式清 approvals（无 FK 不参与 CASCADE，
        # 否则旧留痕 + 序列重置后的同 id 新单会造成重复留痕）；CASCADE 连带清
        # reimbursements（travel_request_id FK），报销自测会自行重建；账号表不受影响
        async with AsyncSessionLocal() as db:
            await db.execute(text(
                "TRUNCATE travel_requests, reimbursements, approvals RESTART IDENTITY CASCADE"
            ))
            await db.commit()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            t_admin = await _login(client, "admin", "Admin@123456")
            t_emp = await _login(client, "zhangwei", "Employee@123456")
            t_appr = await _login(client, "lium", "Approver@123456")

            # 1) 员工创建申请
            r = await client.post("/api/travel/requests", json={
                "title": "拜访杭州客户", "trip_type": "visit",
                "departure_city": "北京", "arrival_city": "杭州",
                "start_date": "2026-10-20", "end_date": "2026-10-22",
                "reason": "拜访客户", "estimated_amount": 3200.0,
            }, headers=_auth(t_emp))
            r1 = r.json()
            print(f"[1 创建] {r.status_code} id={r1['id']} status={r1['status']}")
            assert r.status_code == 201 and r1["status"] == "draft"

            # 2) 日期格式校验 422
            r = await client.post("/api/travel/requests", json={"title": "x", "start_date": "2026/1/1"},
                                  headers=_auth(t_emp))
            assert r.status_code == 422
            print(f"[2 日期校验] {r.status_code}（YYYY-MM-DD 强制）")

            # 2b) trip_type 白名单 + 日期逻辑校验（R-26/R-27）
            r = await client.post("/api/travel/requests", json={"title": "x", "trip_type": "hack"},
                                  headers=_auth(t_emp))
            assert r.status_code == 422
            r = await client.post("/api/travel/requests", json={
                "title": "x", "start_date": "2026-10-20", "end_date": "2026-10-15"},
                headers=_auth(t_emp))
            assert r.status_code == 422
            print(f"[2b trip_type/日期逻辑] 非法类型 422；返程早于出发 422")

            # 3) 我的列表（分页）
            r = await client.get("/api/travel/requests?page=1&page_size=1", headers=_auth(t_emp))
            assert r.json()["total"] == 1 and len(r.json()["items"]) == 1
            print(f"[3 我的列表] total={r.json()['total']}")

            # 4) 提交 → pending
            r = await client.post(f"/api/travel/requests/{r1['id']}/submit", headers=_auth(t_emp))
            assert r.json()["status"] == "pending"
            print(f"[4 提交] status={r.json()['status']}")

            # 5) 员工审批 → 403
            r = await client.post(f"/api/travel/requests/{r1['id']}/approve", headers=_auth(t_emp))
            assert r.status_code == 403
            print(f"[5 员工审批] {r.status_code}（角色守卫）")

            # 6) 待审列表：审批人看 1 条，员工 403
            r = await client.get("/api/travel/requests?to_review=true", headers=_auth(t_appr))
            assert r.json()["total"] == 1
            r = await client.get("/api/travel/requests?to_review=true", headers=_auth(t_emp))
            assert r.status_code == 403
            print("[6 待审列表] approver=1 员工=403")

            # 7) approver 通过 → approved + 留痕
            r = await client.post(f"/api/travel/requests/{r1['id']}/approve", headers=_auth(t_appr))
            assert r.json()["status"] == "approved"
            detail = await client.get(f"/api/travel/requests/{r1['id']}", headers=_auth(t_emp))
            assert len(detail.json()["approvals"]) == 1
            print(f"[7 审批通过] status={r.json()['status']} 留痕={len(detail.json()['approvals'])} 条")

            # 8) 第二张：提交后驳回 → rejected + reason
            r = await client.post("/api/travel/requests", json={"title": "深圳会议", "estimated_amount": 2650.0},
                                  headers=_auth(t_emp))
            r2 = r.json()
            await client.post(f"/api/travel/requests/{r2['id']}/submit", headers=_auth(t_emp))
            r = await client.post(f"/api/travel/requests/{r2['id']}/reject",
                                  json={"reason": "预算超标，请缩减"}, headers=_auth(t_appr))
            assert r.json()["status"] == "rejected" and "预算超标" in r.json()["reject_reason"]
            print(f"[8 驳回] status={r.json()['status']}")

            # 9) 驳回后重新提交 → pending
            r = await client.post(f"/api/travel/requests/{r2['id']}/submit", headers=_auth(t_emp))
            assert r.json()["status"] == "pending"
            print(f"[9 重新提交] status={r.json()['status']}")

            # 10) 状态筛选 + 越权 + 无 token
            r = await client.get("/api/travel/requests?status=approved", headers=_auth(t_emp))
            assert r.json()["total"] == 1
            r = await client.get(f"/api/travel/requests/{r2['id']}", headers=_auth(t_admin))
            assert r.status_code == 200
            r = await client.get("/api/travel/requests")
            assert r.status_code == 401
            print("[10 筛选/可见性/鉴权] approved=1；admin 可见；无 token 401")

            print("\n断言通过 ✅：REQ-6 差旅申请状态机 / 单级审批 / 角色守卫 / 筛选分页全部正常")

    asyncio.run(main())

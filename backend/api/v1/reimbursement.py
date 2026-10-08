# 报销单管理（架构方案 P2 报销流：api/v1/reimbursement.py 核心部分）
#
# 契约见 接口契约.md REQ-8。状态机：
#   draft →(submit) pending(current_step=1 待经理) →(approve by approver/admin) current_step=2(待财务)
#         →(approve by finance/admin) approved →(P2 paid)
#   pending 任意级 →(reject) rejected →(重新 submit) pending
#
# 鉴权（架构方案："role 必须参与鉴权"）：
#   - 创建/列表/提交：get_current_user（登录即可），单据归属按 user_id 隔离
#   - 审批/驳回：require_role("approver", "finance", "admin")，且角色必须匹配 current_step

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import get_logger
from backend.dependencies import get_current_user, get_db, require_role

logger = get_logger(__name__)

router = APIRouter(prefix="/api/reimbursements", tags=["报销单"])

_ALLOWED_STATUS = {"draft", "pending", "approved", "rejected", "paid"}
# submit 允许的出发状态：草稿 / 驳回后重新提交
_SUBMITABLE_STATUS = {"draft", "rejected"}


class ReimbursementCreate(BaseModel):
    """创建报销单请求体。"""

    title: str = Field(..., min_length=1, max_length=256, description="报销单标题")
    total_amount: float = Field(default=0.0, ge=0, description="报销总额")
    travel_request_id: int | None = Field(default=None, description="关联差旅申请单 ID（可选）")


class RejectRequest(BaseModel):
    """驳回请求体。"""

    reason: str = Field(..., min_length=1, max_length=500, description="驳回原因")


# ──────────────────────────────────────────────────────────────
# 序列化：行 → 前端 JSON（created_at → isoformat 字符串）
# ──────────────────────────────────────────────────────────────


def _row_to_dict(r) -> dict:
    return {
        "id": int(r.id),
        "title": r.title or "",
        "status": r.status,
        "current_step": int(r.current_step or 1),
        "total_amount": round(float(r.total_amount or 0), 2),
        "user_id": int(r.user_id),
        "user_name": r.user_name or "",
        "department": r.department or "",
        "travel_request_id": r.travel_request_id,
        "travel_request_title": getattr(r, "travel_request_title", None),
        "reject_reason": r.reject_reason or "",
        "created_at": r.created_at.isoformat() if r.created_at else "",
        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
    }


_BASE_SELECT = """
    SELECT rb.id, rb.title, rb.status, rb.current_step, rb.total_amount,
           rb.user_id, u.real_name AS user_name, d.name AS department,
           rb.travel_request_id, tr.title AS travel_request_title,
           rb.reject_reason, rb.created_at, rb.updated_at
    FROM reimbursements rb
    JOIN users u ON rb.user_id = u.id
    LEFT JOIN departments d ON u.department_id = d.id
    LEFT JOIN travel_requests tr ON rb.travel_request_id = tr.id
"""


async def _fetch_one_or_404(db: AsyncSession, rid: int, current_user: dict) -> dict:
    """取单张报销单（本人/admin/审批财务角色可见），不存在或越权一律 404。"""
    row = (await db.execute(text(_BASE_SELECT + " WHERE rb.id = :rid"), {"rid": rid})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="报销单不存在")
    role = current_user["role"]
    if str(row.user_id) != current_user["user_id"] and role not in ("approver", "finance", "admin"):
        raise HTTPException(status_code=404, detail="报销单不存在")
    return _row_to_dict(row)


# ──────────────────────────────────────────────────────────────
# 接口
# ──────────────────────────────────────────────────────────────


@router.get("", summary="报销单列表（我的 / 待我审批 / 状态筛选 / 分页）")
async def list_reimbursements(
    mine: bool = Query(default=True, description="True=我的报销单；False 需配合 to_review"),
    to_review: bool = Query(default=False, description="待我审批列表（approver/finance/admin）"),
    status_filter: str | None = Query(default=None, alias="status", description="状态筛选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """列表查询：三条筛选路径互斥，SQL 全部参数绑定。"""
    role = current_user["role"]
    if status_filter and status_filter not in _ALLOWED_STATUS:
        raise HTTPException(status_code=422, detail=f"非法状态：{status_filter}")

    conds, params = [], {"user_id": int(current_user["user_id"])}
    if to_review:
        if role not in ("approver", "finance", "admin"):
            raise HTTPException(status_code=403, detail="仅审批人/财务/管理员可查看待审列表")
        # approver 看一级待审；finance 看二级待审；admin 两级都看
        step_conds = ["rb.status = 'pending'"]
        if role == "approver":
            step_conds.append("rb.current_step = 1")
        elif role == "finance":
            step_conds.append("rb.current_step = 2")
        conds.append("(" + " AND ".join(step_conds) + ")")
    elif mine:
        conds.append("rb.user_id = :user_id")
    if status_filter:
        conds.append("rb.status = :status")
        params["status"] = status_filter
    where = " WHERE " + " AND ".join(conds) if conds else ""

    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM reimbursements rb{where}"
    ), params)).scalar() or 0
    rows = (await db.execute(text(
        _BASE_SELECT + where + " ORDER BY rb.id DESC LIMIT :limit OFFSET :offset"
    ), {**params, "limit": page_size, "offset": (page - 1) * page_size})).all()

    logger.info("reimb.list_queried", user_id=current_user["user_id"], total=total, to_review=to_review)
    return {"items": [_row_to_dict(r) for r in rows], "total": int(total),
            "page": page, "page_size": page_size}


@router.get("/{rid}", summary="报销单详情（含审批留痕）")
async def get_reimbursement(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    item = await _fetch_one_or_404(db, rid, current_user)
    approval_rows = (await db.execute(text(
        """
        SELECT a.step, a.action, a.comment, a.created_at, u.real_name AS approver_name
        FROM approvals a LEFT JOIN users u ON a.approver_id = u.id
        WHERE a.biz_type = 'reimbursement' AND a.biz_id = :rid
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


@router.post("", summary="创建报销单（草稿）", status_code=status.HTTP_201_CREATED)
async def create_reimbursement(
    req: ReimbursementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rid = (await db.execute(text(
        """
        INSERT INTO reimbursements (user_id, title, total_amount, travel_request_id)
        VALUES (:user_id, :title, :amount, :tr_id)
        RETURNING id
        """
    ), {
        "user_id": int(current_user["user_id"]),
        "title": req.title,
        "amount": req.total_amount,
        "tr_id": req.travel_request_id,
    })).scalar()
    await db.commit()
    logger.info("reimb.created", user_id=current_user["user_id"], id=rid)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/submit", summary="提交审批（draft/rejected → pending）")
async def submit_reimbursement(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # 审核 R-20：条件 UPDATE 原子化（归属+状态双条件），并发重复提交只有一次生效
    result = await db.execute(text(
        "UPDATE reimbursements SET status = 'pending', current_step = 1, updated_at = NOW() "
        "WHERE id = :rid AND user_id = :uid AND status IN ('draft', 'rejected')"
    ), {"rid": rid, "uid": int(current_user["user_id"])})
    if result.rowcount == 0:
        # 区分三种失败：不存在（404）/非本人（404）/状态不可提交（400）
        row = (await db.execute(text(
            "SELECT user_id, status FROM reimbursements WHERE id = :rid"
        ), {"rid": rid})).one_or_none()
        if row is None or str(row.user_id) != current_user["user_id"]:
            raise HTTPException(status_code=404, detail="报销单不存在")
        raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不可提交")
    await db.commit()
    logger.info("reimb.submitted", user_id=current_user["user_id"], id=rid)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/approve", summary="审批通过（按角色推进一级）")
async def approve_reimbursement(
    rid: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("approver", "finance", "admin")),
):
    row = (await db.execute(text(
        "SELECT user_id, status, current_step FROM reimbursements WHERE id = :rid"
    ), {"rid": rid})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不在审批中")

    role, uid, step = current_user["role"], int(current_user["user_id"]), int(row.current_step)
    # 角色与级别匹配：一级只能 approver/admin 审；二级只能 finance/admin 审
    # 审核 R-20：条件 UPDATE 原子化（status+current_step 双条件），
    # 并发审批只有一个请求 rowcount=1 并留痕，另一个 rowcount=0 → 409
    if step == 1 and role in ("approver", "admin"):
        result = await db.execute(text(
            "UPDATE reimbursements SET current_step = 2, approver_id = :uid, updated_at = NOW() "
            "WHERE id = :rid AND status = 'pending' AND current_step = 1"
        ), {"uid": uid, "rid": rid})
        new_step = 2
    elif step == 2 and role in ("finance", "admin"):
        result = await db.execute(text(
            "UPDATE reimbursements SET status = 'approved', finance_reviewer_id = :uid, updated_at = NOW() "
            "WHERE id = :rid AND status = 'pending' AND current_step = 2"
        ), {"uid": uid, "rid": rid})
        new_step = 2  # 终审通过，留痕仍记 step=2
    else:
        raise HTTPException(status_code=403, detail=f"您的角色 {role} 不能审批第 {step} 级")

    if result.rowcount == 0:
        # 条件不满足 = 被并发改过（他人已审/已驳回），返回冲突并放弃留痕
        await db.rollback()
        raise HTTPException(status_code=409, detail="单据状态已变化，请刷新后重试")

    await db.execute(text(
        "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action) "
        "VALUES ('reimbursement', :rid, :step, :uid, 'approve')"
    ), {"rid": rid, "step": new_step, "uid": uid})
    await db.commit()
    logger.info("reimb.approved", approver_id=uid, id=rid, step=new_step)
    return await _fetch_one_or_404(db, rid, current_user)


@router.post("/{rid}/reject", summary="驳回（任意审批角色，pending → rejected）")
async def reject_reimbursement(
    rid: int,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("approver", "finance", "admin")),
):
    row = (await db.execute(text(
        "SELECT status, current_step FROM reimbursements WHERE id = :rid"
    ), {"rid": rid})).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {row.status} 不在审批中")

    # 审核 R-20：条件 UPDATE 原子化，与 approve 并发时只有一方生效
    uid = int(current_user["user_id"])
    result = await db.execute(text(
        "UPDATE reimbursements SET status = 'rejected', reject_reason = :reason, updated_at = NOW() "
        "WHERE id = :rid AND status = 'pending'"
    ), {"rid": rid, "reason": req.reason})
    if result.rowcount == 0:
        await db.rollback()
        raise HTTPException(status_code=409, detail="单据状态已变化，请刷新后重试")

    await db.execute(text(
        "INSERT INTO approvals (biz_type, biz_id, step, approver_id, action, comment) "
        "VALUES ('reimbursement', :rid, :step, :uid, 'reject', :reason)"
    ), {"rid": rid, "step": int(row.current_step), "uid": uid, "reason": req.reason})
    await db.commit()
    logger.info("reimb.rejected", approver_id=uid, id=rid, reason=req.reason[:50])
    return await _fetch_one_or_404(db, rid, current_user)


if __name__ == "__main__":
    # 离线自测：完整状态机（创建→提交→两级审批→驳回→重新提交）+ 权限 + 筛选分页
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

        # 审核 R-03：破坏性自测（TRUNCATE）仅允许 dev 环境
        if get_settings().app_env != "dev":
            raise RuntimeError("本自测含 TRUNCATE，仅允许在 app_env=dev 环境运行")

        await run_migrations()
        from backend.dependencies import AsyncSessionLocal

        # 清空报销数据（保留账号/差旅申请），保证断言一致
        async with AsyncSessionLocal() as db:
            await db.execute(text("TRUNCATE reimbursements, approvals RESTART IDENTITY CASCADE"))
            await db.commit()

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            t_admin = await _login(client, "admin", "Admin@123456")
            t_emp = await _login(client, "zhangwei", "Employee@123456")
            t_appr = await _login(client, "lium", "Approver@123456")
            t_fin = await _login(client, "wangcai", "Finance@123456")

            # 1) 员工创建两张报销单
            r = await client.post("/api/reimbursements", json={"title": "杭州出差报销", "total_amount": 5530.0},
                                  headers=_auth(t_emp))
            r1 = r.json()
            print(f"[1 创建] {r.status_code} id={r1['id']} status={r1['status']} step={r1['current_step']}")
            assert r.status_code == 201 and r1["status"] == "draft"

            r = await client.post("/api/reimbursements", json={"title": "深圳会议报销", "total_amount": 2650.0},
                                  headers=_auth(t_emp))
            r2 = r.json()

            # 2) 我的列表（分页）
            r = await client.get("/api/reimbursements?page=1&page_size=1", headers=_auth(t_emp))
            assert r.json()["total"] == 2 and len(r.json()["items"]) == 1
            print(f"[2 我的列表] total={r.json()['total']} items={len(r.json()['items'])}（page_size=1）")

            # 3) 提交第一张 → pending step=1
            r = await client.post(f"/api/reimbursements/{r1['id']}/submit", headers=_auth(t_emp))
            assert r.json()["status"] == "pending" and r.json()["current_step"] == 1
            print(f"[3 提交] {r.json()['status']} step={r.json()['current_step']}")

            # 4) 员工调审批 → 403
            r = await client.post(f"/api/reimbursements/{r1['id']}/approve", headers=_auth(t_emp))
            assert r.status_code == 403
            print(f"[4 员工审批] {r.status_code}（角色守卫生效）")

            # 5) approver 一级通过 → step=2
            r = await client.post(f"/api/reimbursements/{r1['id']}/approve", headers=_auth(t_appr))
            assert r.json()["current_step"] == 2
            print(f"[5 经理通过] step→{r.json()['current_step']}")

            # 6) approver 再审二级 → 403（角色不匹配）
            r = await client.post(f"/api/reimbursements/{r1['id']}/approve", headers=_auth(t_appr))
            assert r.status_code == 403
            print(f"[6 经理审二级] {r.status_code}（需财务）")

            # 7) finance 二级通过 → approved，留痕 2 条
            r = await client.post(f"/api/reimbursements/{r1['id']}/approve", headers=_auth(t_fin))
            assert r.json()["status"] == "approved"
            detail = await client.get(f"/api/reimbursements/{r1['id']}", headers=_auth(t_emp))
            assert len(detail.json()["approvals"]) == 2
            print(f"[7 财务通过] status={r.json()['status']} 留痕={len(detail.json()['approvals'])} 条")

            # 8) 第二张提交后驳回 → rejected + reason，留痕
            await client.post(f"/api/reimbursements/{r2['id']}/submit", headers=_auth(t_emp))
            r = await client.post(f"/api/reimbursements/{r2['id']}/reject",
                                  json={"reason": "发票不合规，请补充"}, headers=_auth(t_appr))
            assert r.json()["status"] == "rejected" and "发票不合规" in r.json()["reject_reason"]
            print(f"[8 驳回] status={r.json()['status']} reason={r.json()['reject_reason'][:20]}...")

            # 9) 驳回后重新提交 → pending
            r = await client.post(f"/api/reimbursements/{r2['id']}/submit", headers=_auth(t_emp))
            assert r.json()["status"] == "pending"
            print(f"[9 重新提交] status={r.json()['status']}")

            # 10) 待审列表：经理看一级 1 条；财务看二级 0 条；员工 403
            r = await client.get("/api/reimbursements?to_review=true", headers=_auth(t_appr))
            assert r.json()["total"] == 1
            r = await client.get("/api/reimbursements?to_review=true", headers=_auth(t_fin))
            assert r.json()["total"] == 0
            r = await client.get("/api/reimbursements?to_review=true", headers=_auth(t_emp))
            assert r.status_code == 403
            print("[10 待审列表] 经理=1 财务=0 员工=403")

            # 11) 状态筛选 + 越权访问
            r = await client.get("/api/reimbursements?status=approved", headers=_auth(t_emp))
            assert r.json()["total"] == 1
            r = await client.get(f"/api/reimbursements/{r2['id']}", headers=_auth(t_admin))
            assert r.status_code == 200
            print("[11 筛选/可见性] approved=1；admin 可见他人单据")

            # 12) 并发审批（审核 R-20 验证）：两个财务并发通过同一张二级单据
            #     → 一个成功；另一个按竞态交错返回 400（读到已审批）或 409（条件更新落空），
            #     留痕始终只有 2 条（无双重留痕）
            r = await client.post("/api/reimbursements", json={"title": "并发审批验证单", "total_amount": 100.0},
                                  headers=_auth(t_emp))
            r3 = r.json()
            await client.post(f"/api/reimbursements/{r3['id']}/submit", headers=_auth(t_emp))
            await client.post(f"/api/reimbursements/{r3['id']}/approve", headers=_auth(t_appr))
            codes = await asyncio.gather(
                client.post(f"/api/reimbursements/{r3['id']}/approve", headers=_auth(t_fin)),
                client.post(f"/api/reimbursements/{r3['id']}/approve", headers=_auth(t_fin)),
            )
            code_set = sorted(c.status_code for c in codes)
            assert code_set in ([200, 400], [200, 409]), f"并发审批应一成一败，实际 {code_set}"
            detail = await client.get(f"/api/reimbursements/{r3['id']}", headers=_auth(t_emp))
            assert len(detail.json()["approvals"]) == 2  # 经理 1 条 + 成功财务 1 条
            print(f"[12 并发审批] codes={code_set} 留痕={len(detail.json()['approvals'])} 条（无双重留痕）")

            print("\n断言通过 ✅：REQ-8 报销单状态机 / 两级审批 / 角色守卫 / 筛选分页 / 并发安全全部正常")

    asyncio.run(main())

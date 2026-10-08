# 发票上传与解析（架构方案 P2 报销流入口：api/v1/invoice.py）
# backend/api/v1/invoice.py
#
# POST /api/invoice/upload（契约 REQ-7）：
#   multipart 上传 PDF/JPG/PNG → 后缀/大小白名单校验 → 落临时文件
#   → 调 agents.reimbursement.graph.parse_invoice_file（LLM 结构化 + 校验）
#   → 返回 JSON（invoice 四字段 + needs_human_review/problems/fallback_used/source）
#
# 架构方案口径：DB 只存路径、invoices 表 P2 建立；本接口解析后暂不落库，
# 前端拿到结果后走 REQ-8 报销单创建挂接。

from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.agents.reimbursement.graph import parse_invoice_file
from backend.core.logger import get_logger
from backend.dependencies import get_current_user

logger = get_logger(__name__)

router = APIRouter(prefix="/api/invoice", tags=["发票"])

_ALLOWED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB（架构方案：大小+后缀白名单）

# 审核 R-29：魔数校验（文件头字节），防后缀伪装文件；解析端仍保留降级兜底
_MAGIC_BYTES = {
    ".pdf": b"%PDF",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}


@router.post("/upload", summary="上传发票并解析（PDF/JPG/PNG → 结构化 JSON）")
async def upload_invoice(
    file: UploadFile = File(..., description="发票文件：PDF/JPG/PNG，≤10MB"),
    current_user: dict = Depends(get_current_user),
):
    """上传 → 校验 → 临时落盘 → parse_invoice_file 解析 → 返回 JSON。

    解析失败不抛 5xx：parse_invoice_file 内部静默降级，
    返回 needs_human_review=True + 空结构（转人工核验语义）。
    """
    filename = file.filename or ""
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件类型 {suffix or '(无后缀)'}，仅支持 PDF/JPG/PNG",
        )

    # 流式读入并限大小（避免大文件占满内存）
    content = await file.read(_MAX_FILE_SIZE + 1)
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件超过 {_MAX_FILE_SIZE // (1024 * 1024)}MB 上限",
        )
    if not content:
        raise HTTPException(status_code=422, detail="文件内容为空")
    # 魔数校验：文件头字节必须与后缀类型一致（R-29）
    magic = _MAGIC_BYTES.get(suffix, b"")
    if magic and not content.startswith(magic):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="文件内容与扩展名不符，请上传真实的发票文件",
        )

    # 临时落盘（解析后立即删除；P2 invoices 表建立后改为持久化存储路径）
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)

        logger.info("invoice.upload_received", user_id=current_user["user_id"],
                    filename=filename, size=len(content))
        result = await parse_invoice_file(
            tmp_path,
            user_id=current_user["user_id"],
            tenant_id=current_user["tenant_id"],
        )
        return result
    finally:
        try:
            os.unlink(tmp_path)  # 无论成败都清理临时文件
        except OSError:
            pass


if __name__ == "__main__":
    # 离线自测：生成模拟发票 PDF → multipart 上传 → 断言解析结果
    # （LLM 真实调用；DB 不需要）
    import asyncio
    import io
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    def _make_invoice_pdf(with_text: bool) -> bytes:
        """生成模拟发票 PDF 字节（with_text=False 为空白页，模拟扫描件）。"""
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page()
        if with_text:
            text = (
                "增值税电子普通发票\n"
                "发票代码：044032100211\n"
                "发票号码：12345678\n"
                "开票日期：2026年10月08日\n"
                "销售方名称：杭州云启科技有限公司\n"
                "价税合计（大写）伍佰伍拾叁圆整（小写）¥553.00\n"
            )
            # fontname="china-s"：内置简体中文字体（默认字体不渲染中文）
            page.insert_text((72, 72), text, fontsize=12, fontname="china-s")
        buf = doc.tobytes()
        doc.close()
        return buf

    async def main():
        import httpx

        from backend.main import app

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/auth/login", json={"username": "zhangwei", "password": "Employee@123456"})
            token = r.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # 1) 电子发票 PDF → 4 字段全识别
            files = {"file": ("invoice.pdf", io.BytesIO(_make_invoice_pdf(True)), "application/pdf")}
            r = await client.post("/api/invoice/upload", files=files, headers=headers)
            data = r.json()
            print(f"[1 电子发票] {r.status_code} {data['invoice']}")
            assert r.status_code == 200
            assert data["invoice"]["invoice_code"] == "044032100211"
            assert abs(data["invoice"]["amount"] - 553.0) < 0.01
            assert data["invoice"]["seller_name"] == "杭州云启科技有限公司"
            assert data["needs_human_review"] is False

            # 2) 扫描件（空白页）→ 降级转人工
            files = {"file": ("scanned.pdf", io.BytesIO(_make_invoice_pdf(False)), "application/pdf")}
            r = await client.post("/api/invoice/upload", files=files, headers=headers)
            data = r.json()
            print(f"[2 扫描件] {r.status_code} source={data['source']} review={data['needs_human_review']}")
            assert data["needs_human_review"] is True and data["source"] == "ocr_needed"

            # 3) 非法后缀 → 415
            files = {"file": ("evil.txt", b"hello", "text/plain")}
            r = await client.post("/api/invoice/upload", files=files, headers=headers)
            print(f"[3 非法后缀] {r.status_code} {r.json()['detail']}")
            assert r.status_code == 415

            # 3b) 后缀伪装（.pdf 但内容是文本）→ 415 魔数拦截（R-29）
            files = {"file": ("fake.pdf", b"this is not a pdf", "application/pdf")}
            r = await client.post("/api/invoice/upload", files=files, headers=headers)
            print(f"[3b 魔数校验] {r.status_code} {r.json()['detail']}")
            assert r.status_code == 415

            # 4) 空文件 → 422
            files = {"file": ("empty.pdf", b"", "application/pdf")}
            r = await client.post("/api/invoice/upload", files=files, headers=headers)
            print(f"[4 空文件] {r.status_code}")
            assert r.status_code == 422

            # 5) 无 Token → 401
            files = {"file": ("invoice.pdf", io.BytesIO(_make_invoice_pdf(True)), "application/pdf")}
            r = await client.post("/api/invoice/upload", files=files)
            print(f"[5 无Token] {r.status_code}")
            assert r.status_code == 401

            print("\n断言通过 ✅：REQ-7 发票上传（校验/解析/降级/鉴权）全部正常")

    asyncio.run(main())

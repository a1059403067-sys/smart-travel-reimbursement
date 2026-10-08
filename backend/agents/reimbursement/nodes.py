"""发票解析工作流节点实现。

节点约定（参考 EduAgent resume/nodes.py 与 travel/nodes.py）：
- async def xxx_node(state) -> dict，只返回增量字段
- 文件解析失败一律静默降级（fallback_used + needs_human_review），绝不阻断主流程——
  报销场景的降级语义是"转人工审核"，不是报错
- LLM 结构化提取：get_structured_llm（function_calling）+ 判空重试 2 次 + 兜底空结构
  （EduAgent resume/nodes.py:146-210 同款模式）

管线说明（架构方案.md 模块 5 的精简版）：
    上传落盘 → ① pymupdf 提取文本层（扫描件无文本层 → 标 needs_ocr 待 P2 PaddleOCR）
             → ② LLM 结构化（Prompt + function_calling，见 prompts.py）
             → ③ 轻量校验（金额/代码/日期格式），失败字段标 needs_human_review
             → ④ 输出 JSON（structured_output，可直接 json.dumps）
DeepSeek 的 deepseek-chat 不支持图片多模态，故走"OCR/文本层 + LLM 文本结构化"路线；
将来换支持视觉的模型（Qwen-VL/Claude）时，仅需在 extract 节点加图片直传分支。
"""

from __future__ import annotations

import re
from datetime import datetime

from langchain_core.messages import AIMessage

from backend.agents.reimbursement.prompts import INVOICE_EXTRACT_PROMPT, INVOICE_RESULT_SUMMARY
from backend.agents.reimbursement.state import InvoiceInfo, InvoiceState
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger

logger = get_logger(__name__)

# 后缀白名单（架构方案：大小+后缀白名单，落 tempfile 由 API 层负责）
SUPPORTED_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png"}

# 发票代码格式：10 位（纸质票）或 12 位（电子票）
_INVOICE_CODE_RE = re.compile(r"^\d{10}$|^\d{12}$")

# LLM 结构化提取的最大尝试次数（判空重试，EduAgent 同款）
MAX_EXTRACT_ATTEMPTS = 2


# ──────────────────────────────────────────────────────────────
# 节点 1：加载文件（pymupdf 提取文本层）
# ──────────────────────────────────────────────────────────────


async def load_file_node(state: InvoiceState) -> dict:
    """读取上传的 PDF/图片，提取文本层内容；失败/扫描件静默降级，不阻断。"""
    file_path = state["file_path"]
    suffix = ("." + file_path.rsplit(".", 1)[-1].lower()) if "." in file_path else ""

    if suffix not in SUPPORTED_SUFFIXES:
        logger.warning("invoice.unsupported_type", file_path=file_path, suffix=suffix)
        return {
            "raw_text": "",
            "needs_ocr": False,
            "fallback_used": True,
            "needs_human_review": True,
            "messages": [AIMessage(content=f"暂不支持 {suffix or '该'} 格式的发票文件，请上传 PDF/JPG/PNG，或转交人工核验。")],
        }

    try:
        import pymupdf  # 延迟导入，避免未安装时影响其它模块

        doc = pymupdf.open(file_path)
        try:
            raw_text = "\n".join(page.get_text() for page in doc).strip()
        finally:
            doc.close()
    except Exception as exc:
        logger.warning("invoice.load_failed", file_path=file_path, error=str(exc))
        return {
            "raw_text": "",
            "needs_ocr": False,
            "fallback_used": True,
            "needs_human_review": True,
            "messages": [AIMessage(content="发票文件读取失败，请确认文件未损坏，或转交人工核验。")],
        }

    if not raw_text:
        # 无文本层 = 扫描件/拍照件：P2 接入 PaddleOCR（架构方案难点②），当前转人工
        logger.warning("invoice.no_text_layer", file_path=file_path)
        return {
            "raw_text": "",
            "needs_ocr": True,
            "fallback_used": True,
            "needs_human_review": True,
            "messages": [AIMessage(content="该文件为扫描件/图片且无文本层，OCR 能力暂未接入，已转人工核验。")],
        }

    return {"raw_text": raw_text, "needs_ocr": False, "file_type": suffix.lstrip(".")}


# ──────────────────────────────────────────────────────────────
# 节点 2：LLM 结构化提取 + 正则规则兜底
# ──────────────────────────────────────────────────────────────


def _regex_fill(raw_text: str, info: InvoiceInfo) -> InvoiceInfo:
    """LLM 未识别字段的规则兜底（正则直提，架构方案："别信 LLM 一次输出"）。

    优先级：LLM 结果 > 正则补全 > 空默认值。正则只覆盖规范标签写法，
    两路都兜不住的字段由校验节点标 needs_human_review。
    """
    data = info.model_dump()

    if not data["invoice_date"]:
        m = re.search(r"开票日期[:：]\s*(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})日?", raw_text)
        if m:
            data["invoice_date"] = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    if not data["invoice_code"]:
        m = re.search(r"发票代码[:：]\s*(\d{10,12})\b", raw_text)
        if m:
            data["invoice_code"] = m.group(1)

    if not data["seller_name"]:
        m = re.search(r"(?:销方|销售方)名称[:：]\s*([^\n，,]{4,40})", raw_text)
        if m:
            data["seller_name"] = m.group(1).strip()

    if data["amount"] <= 0:
        # 优先"价税合计…¥xx"，退而求其次任意 ¥ 金额
        m = re.search(r"价税合计[^\n]{0,20}?[¥￥]\s*([\d,]+\.?\d*)", raw_text) or re.search(
            r"[¥￥]\s*([\d,]+\.?\d*)", raw_text
        )
        if m:
            data["amount"] = float(m.group(1).replace(",", ""))

    return InvoiceInfo(**data)


async def extract_invoice_node(state: InvoiceState) -> dict:
    """用结构化 LLM 提取发票字段；判空重试 2 次，兜底空结构（不阻断）。"""
    raw_text = state.get("raw_text", "")
    if not raw_text:
        # load 节点已降级（扫描件/读取失败），本节点跳过
        return {"structured_output": None}

    # 控制长度：发票文本不会超 4000 字，截断兜底防超限
    text_for_llm = raw_text[:4000] if len(raw_text) > 4000 else raw_text
    prompt = INVOICE_EXTRACT_PROMPT.format(ocr_text=text_for_llm)

    info: InvoiceInfo | None = None
    last_error: Exception | None = None
    for attempt in range(MAX_EXTRACT_ATTEMPTS):
        try:
            llm = get_structured_llm("reimbursement", InvoiceInfo)
            result = await llm.ainvoke(prompt)
            if result is None:
                # with_structured_output 偶发返回 None（EduAgent 踩坑），判空重试
                last_error = ValueError("structured output 返回 None")
                logger.warning("invoice.extract_none", attempt=attempt)
            else:
                info = result
                break
        except Exception as exc:
            last_error = exc
            logger.warning("invoice.extract_error", attempt=attempt, error=str(exc))

    if info is None:
        # structured_output 置 None：校验节点据此走降级透出分支，与 load 失败路径语义一致
        logger.warning("invoice.extract_fallback", last_error=str(last_error))
        return {
            "structured_output": None,
            "fallback_used": True,
            "needs_human_review": True,
            "messages": [AIMessage(content="发票信息识别失败，已转人工核验。")],
        }

    # LLM 未识别的字段用正则规则补全（双路互备，降低单点漏提取）
    info = _regex_fill(text_for_llm, info)
    return {"structured_output": info.model_dump()}


# ──────────────────────────────────────────────────────────────
# 节点 3：轻量校验 + 组装 JSON 出口
# ──────────────────────────────────────────────────────────────


def _validate_invoice(info: InvoiceInfo) -> list[str]:
    """字段级校验，返回需人工复核的问题列表（架构方案校验层精简版）。

    金额勾稽（价税合计 vs 金额+税额）与发票号码查重属 P2 全量校验层，
    需 DB 唯一索引配合，不在本节点实现。
    """
    problems: list[str] = []

    if info.amount <= 0:
        problems.append("金额未识别或为 0")
    else:
        # 金额保留两位小数（发票价税合计无三位以上小数）
        if round(info.amount, 2) != info.amount:
            problems.append(f"金额 {info.amount} 小数位数异常")

    if info.invoice_date:
        try:
            datetime.strptime(info.invoice_date, "%Y-%m-%d")
        except ValueError:
            problems.append(f"开票日期 {info.invoice_date} 格式不合法")
    else:
        problems.append("开票日期未识别")

    if info.invoice_code and not _INVOICE_CODE_RE.match(info.invoice_code):
        problems.append(f"发票代码 {info.invoice_code} 不符合 10/12 位数字格式")

    if not info.seller_name:
        problems.append("销售方名称未识别")

    return problems


async def validate_invoice_node(state: InvoiceState) -> dict:
    """校验提取结果并组装最终 JSON 出口（structured_output）。"""
    extracted = state.get("structured_output") or {}
    info = InvoiceInfo(**extracted) if extracted else InvoiceInfo()

    # 前置节点已降级（扫描件/读取失败/识别失败）时不重复校验，直接透出空结构
    if state.get("fallback_used") and not extracted:
        return {
            "structured_output": {
                "invoice": info.model_dump(),
                "needs_human_review": True,
                "fallback_used": True,
                "source": "ocr_needed" if state.get("needs_ocr") else "parse_failed",
            }
        }

    problems = _validate_invoice(info)
    needs_review = bool(problems) or state.get("needs_human_review", False)

    # 结构化出口（JSON 可直接序列化；API 层返回给前端/落 DB）
    structured = {
        "invoice": info.model_dump(),
        "needs_human_review": needs_review,
        "problems": problems,
        "fallback_used": state.get("fallback_used", False),
        "source": "text_layer",
    }

    if needs_review:
        content = "发票信息已提取，但存在以下问题需人工复核：" + "；".join(problems)
    else:
        content = INVOICE_RESULT_SUMMARY.format(
            invoice_date=info.invoice_date or "未识别",
            amount=info.amount,
            invoice_code=info.invoice_code or "未识别",
            seller_name=info.seller_name or "未识别",
        )
    return {
        "structured_output": structured,
        "needs_human_review": needs_review,
        "messages": [AIMessage(content=content)],
    }


if __name__ == "__main__":
    # 离线自测：校验函数纯逻辑（不调 LLM）
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    ok = InvoiceInfo(invoice_date="2026-10-08", amount=553.0,
                     invoice_code="044032100211", seller_name="杭州云启科技有限公司")
    bad = InvoiceInfo(invoice_date="2026/10/08", amount=0.0,
                      invoice_code="ABC", seller_name="")
    print(f"[合法发票] 问题数: {len(_validate_invoice(ok))}")
    print(f"[非法发票] 问题: {_validate_invoice(bad)}")

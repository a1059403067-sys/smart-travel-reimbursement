"""发票解析工作流 Graph 定义。

拓扑（直线，无分支）：

    START → load_file → extract_invoice → validate_invoice → END

约定（参考 EduAgent graph.py）：
- build 工厂返回 compile 后的图；parse_invoice_file 为对外唯一入口（API 层调用）
- 入口套 with_retry(agent_type="reimbursement")：LLM 超时等可恢复错误自动重试，
  耗尽后走业务降级"转人工审核"（core/retry.py _fallback_reimbursement）
- 节点内部各自静默降级，图永不向调用方抛业务异常
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from backend.agents.reimbursement.nodes import (
    extract_invoice_node,
    load_file_node,
    validate_invoice_node,
)
from backend.agents.reimbursement.state import InvoiceState
from backend.core.retry import with_retry


def build_invoice_graph():
    builder = StateGraph(InvoiceState)
    builder.add_node("load_file", load_file_node)
    builder.add_node("extract_invoice", extract_invoice_node)
    builder.add_node("validate_invoice", validate_invoice_node)

    builder.add_edge(START, "load_file")
    builder.add_edge("load_file", "extract_invoice")
    builder.add_edge("extract_invoice", "validate_invoice")
    builder.add_edge("validate_invoice", END)
    return builder.compile()


@with_retry(agent_type="reimbursement")
async def parse_invoice_file(
    file_path: str,
    user_id: str = "",
    tenant_id: str = "",
    session_id: str = "",
) -> dict:
    """对外唯一入口：接收上传的发票 PDF/图片路径，返回 JSON（可直接 json.dumps）。

    返回结构（成功）：
        {
            "invoice": {"invoice_date", "amount", "invoice_code", "seller_name"},
            "needs_human_review": bool,
            "problems": [...],
            "fallback_used": bool,
            "source": "text_layer",
        }
    降级路径（LLM 重试耗尽）返回 core/retry.py 的 _fallback_reimbursement 结构，
    同为 dict 可序列化，needs_human_review=True 语义一致。
    """
    graph = build_invoice_graph()
    # 首轮必须传全量 State（EduAgent 传参纪律）
    initial_state: InvoiceState = {
        "messages": [HumanMessage(content=f"请解析发票文件：{file_path}")],
        "user_id": user_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
        "file_path": file_path,
        "file_type": "",
        "raw_text": "",
        "needs_ocr": False,
        "fallback_used": False,
        "needs_human_review": False,
        "structured_output": None,
    }
    result = await graph.ainvoke(initial_state)
    return result["structured_output"]


if __name__ == "__main__":
    # 离线自测：真实 LLM + 程序生成的模拟发票 PDF（场景 2 模拟扫描件降级）
    import asyncio
    import json
    import sys
    import tempfile
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    def _make_sample_invoice_pdf(path: Path, with_text: bool) -> None:
        """用 pymupdf 生成测试文件：with_text=True 带模拟发票文本层，False 为空白页（模拟扫描件）。"""
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
                "购买方名称：北京智行科技有限公司\n"
                "价税合计（大写）伍佰伍拾叁圆整（小写）¥553.00\n"
                "校验码：12345 67890 12345 67890\n"
            )
            # fontname="china-s"：pymupdf 内置简体中文字体（默认字体不渲染中文，提取全是占位符）
            page.insert_text((72, 72), text, fontsize=12, fontname="china-s")
        doc.save(str(path))
        doc.close()

    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            # 场景 1：有文本层 PDF → 提取出 4 个字段
            print("=" * 60)
            print("场景 1：电子发票 PDF（真实 LLM 提取）")
            print("=" * 60)
            pdf = tmp_dir / "invoice_digital.pdf"
            _make_sample_invoice_pdf(pdf, with_text=True)
            result = await parse_invoice_file(str(pdf))
            print(json.dumps(result, ensure_ascii=False, indent=2))

            # 场景 2：无文本层（模拟扫描件）→ 应降级转人工，不调 LLM
            print("\n" + "=" * 60)
            print("场景 2：扫描件 PDF 无文本层（应降级转人工，不调 LLM）")
            print("=" * 60)
            scanned = tmp_dir / "invoice_scanned.pdf"
            _make_sample_invoice_pdf(scanned, with_text=False)
            result2 = await parse_invoice_file(str(scanned))
            print(json.dumps(result2, ensure_ascii=False, indent=2))
            assert result2["needs_human_review"] is True
            assert result2["source"] == "ocr_needed"
            print("断言通过：扫描件 → needs_human_review=True, source=ocr_needed")

    asyncio.run(main())

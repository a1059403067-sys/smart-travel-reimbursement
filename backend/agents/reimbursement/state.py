"""发票解析工作流 State 定义。

约定（参考 EduAgent 四文件模板，与 travel 包一致）：
- 首部：messages + user_id/tenant_id/session_id 三件套（编排层注入，节点只读）
- 中间：按数据流阶段分组，顺序与图执行顺序一致
- 尾部：fallback_used / needs_human_review / structured_output 统一收尾字段
        （structured_output 为 API 层读取的对外出口，可直接 json.dumps）
- 唯一 reducer 是 add_messages，其余字段默认覆盖语义
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class InvoiceInfo(BaseModel):
    """LLM 结构化输出目标：发票关键字段。

    金额统一为纯数字（价税合计）；日期统一 YYYY-MM-DD；未识别字段留默认值，
    绝不臆造——低置信/缺失由校验节点标 needs_human_review。
    """

    invoice_date: str = Field(default="", description="开票日期，格式 YYYY-MM-DD")
    amount: float = Field(default=0.0, description="价税合计金额，纯数字，不含货币符号")
    invoice_code: str = Field(default="", description="发票代码，10 或 12 位数字（注意与发票号码区分）")
    seller_name: str = Field(default="", description="销售方名称（开票企业全称）")


class InvoiceState(TypedDict):
    # ── ① 请求上下文 ──
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    tenant_id: str
    session_id: str

    # ── ② 文件输入（API 层上传落盘后注入）──
    file_path: str
    file_type: str  # pdf | jpg | png（后缀白名单校验后归一化）

    # ── ③ 中间结果（load → extract 节点产出）──
    raw_text: str       # pymupdf 提取的文本层内容（扫描件为空）
    needs_ocr: bool     # True = 无文本层扫描件，待 P2 PaddleOCR 接入

    # ── ④ 最终结果 ──
    fallback_used: bool
    needs_human_review: bool
    structured_output: dict | None


if __name__ == "__main__":
    # 离线自测：校验 State 必填键与 Pydantic 模型
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    keys = list(InvoiceState.__annotations__)
    print(f"[State] 共 {len(keys)} 个字段: {keys}")
    sample = InvoiceInfo(
        invoice_date="2026-10-08", amount=553.0,
        invoice_code="044032100211", seller_name="杭州云启科技有限公司",
    )
    print(f"[InvoiceInfo] {sample.model_dump()}")
    empty = InvoiceInfo()
    print(f"[InvoiceInfo 空实例] {empty.model_dump()}")

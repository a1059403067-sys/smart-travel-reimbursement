<template>
  <div class="invoice-parse">
    <el-card shadow="never" class="upload-card">
      <template #header>发票解析（OCR + LLM 结构化）</template>
      <el-upload
        drag
        :auto-upload="false"
        :limit="1"
        accept=".pdf,.jpg,.jpeg,.png"
        :on-change="handleFileChange"
        :on-remove="handleRemove"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽发票文件到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip">支持 PDF / JPG / PNG，文件大小不超过 10MB</div>
        </template>
      </el-upload>

      <div class="action-row">
        <el-button
          type="primary"
          :loading="parsing"
          :disabled="!currentFile"
          @click="handleParse"
        >
          开始解析
        </el-button>
      </div>
    </el-card>

    <!-- 解析结果 -->
    <el-card v-if="result" shadow="never" class="result-card">
      <template #header>解析结果</template>

      <el-alert
        v-if="result.needs_human_review"
        type="warning"
        :closable="false"
        show-icon
        :title="sourceLabel(result.source)"
        class="review-alert"
      />

      <el-descriptions :column="2" border>
        <el-descriptions-item label="开票日期">{{ result.invoice.invoice_date }}</el-descriptions-item>
        <el-descriptions-item label="金额">
          <span class="amount">￥{{ result.invoice.amount }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="发票代码">{{ result.invoice.invoice_code }}</el-descriptions-item>
        <el-descriptions-item label="销售方">{{ result.invoice.seller_name }}</el-descriptions-item>
      </el-descriptions>

      <template v-if="result.problems?.length">
        <div class="problems-title">识别问题</div>
        <ul class="problems">
          <li v-for="(p, i) in result.problems" :key="i">{{ p }}</li>
        </ul>
      </template>

      <div class="result-actions">
        <el-button type="primary" @click="handleCreateFromInvoice">用此发票新建报销单</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import { invoiceApi } from '@/api/invoice'
import type { InvoiceParseResult } from '@/types'

const router = useRouter()
const parsing = ref(false)
const currentFile = ref<File | null>(null)
const result = ref<InvoiceParseResult | null>(null)

// REQ-7 source 字段文案：text_layer 电子发票 / ocr_needed 扫描件转人工 / parse_failed
const sourceLabel = (s: string) =>
  s === 'ocr_needed' ? '扫描件无文本层，已转人工核验（OCR 规划中）' : '识别置信度较低，建议人工核对'

function handleFileChange(file: UploadFile) {
  currentFile.value = (file.raw as File) ?? null
}

function handleRemove() {
  currentFile.value = null
}

async function handleParse() {
  const file = currentFile.value
  if (!file) return
  parsing.value = true
  try {
    const { data } = await invoiceApi.upload(file)
    result.value = data
    if (data.needs_human_review) {
      ElMessage.warning('识别置信度较低，请人工核对解析结果')
    } else {
      ElMessage.success('解析完成')
    }
  } catch {
    result.value = null
  } finally {
    parsing.value = false
  }
}

function handleCreateFromInvoice() {
  // TODO: 携带解析结果跳转新增报销单页
  router.push({ path: '/reimbursements/new', query: { from_invoice: '1' } })
}
</script>

<style scoped>
.invoice-parse {
  max-width: 800px;
}
.pending-alert {
  margin-bottom: 16px;
}
.upload-card {
  margin-bottom: 16px;
}
.action-row {
  margin-top: 16px;
}
.result-card {
  margin-bottom: 16px;
}
.review-alert {
  margin-bottom: 16px;
}
.amount {
  color: #fa8c16;
  font-weight: 600;
}
.problems-title {
  margin-top: 16px;
  font-size: 14px;
  font-weight: 600;
}
.problems {
  margin: 8px 0 0;
  padding-left: 20px;
  color: #fa8c16;
  font-size: 13px;
}
.result-actions {
  margin-top: 16px;
}
</style>

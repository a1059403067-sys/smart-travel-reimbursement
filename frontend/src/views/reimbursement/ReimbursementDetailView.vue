<template>
  <div class="reimbursement-detail" v-if="detail">
    <el-button :icon="Back" @click="router.back()" style="margin-bottom: 16px">返回</el-button>

    <!-- 出差信息 -->
    <el-card shadow="never" class="section-card">
      <template #header>报销单详情</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="报销单号">{{ detail.code }}</el-descriptions-item>
        <el-descriptions-item label="出差事由">{{ detail.reason }}</el-descriptions-item>
        <el-descriptions-item label="目的地">{{ detail.destination }}</el-descriptions-item>
        <el-descriptions-item label="申请人">{{ detail.applicant }}（{{ detail.department }}）</el-descriptions-item>
        <el-descriptions-item label="开始日期">{{ detail.start_date }}</el-descriptions-item>
        <el-descriptions-item label="结束日期">{{ detail.end_date }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(detail.status)">{{ statusLabel(detail.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="提交时间">{{ detail.submitted_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <!-- 费用明细 -->
    <el-card shadow="never" class="section-card">
      <template #header>费用明细</template>
      <el-table :data="detail.items ?? []" border>
        <el-table-column prop="expense_type" label="费用类型" width="120" />
        <el-table-column label="金额" width="120">
          <template #default="{ row }">￥{{ row.amount.toLocaleString() }}</template>
        </el-table-column>
        <el-table-column prop="expense_date" label="费用日期" width="140" />
        <el-table-column prop="remark" label="备注" min-width="120" />
        <el-table-column label="发票附件" width="120">
          <template #default="{ row }">
            <el-button v-if="row.invoice_attachment" link type="primary">查看附件</el-button>
            <span v-else class="muted">无</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="total-amount">合计金额：<span>￥{{ totalAmount.toLocaleString() }}</span></div>
    </el-card>

    <!-- 审批信息 -->
    <el-card v-if="detail.approval" shadow="never" class="section-card">
      <template #header>审批信息</template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="审批人">{{ detail.approval.approver }}</el-descriptions-item>
        <el-descriptions-item label="审批时间">{{ detail.approval.approved_at }}</el-descriptions-item>
        <el-descriptions-item label="审批状态">
          <el-tag :type="detail.approval.status === 'approved' ? 'success' : 'danger'">
            {{ detail.approval.status === 'approved' ? '已通过' : '已驳回' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="审批意见">{{ detail.approval.comment || '无' }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import type { Reimbursement, ReimbursementStatus } from '@/types'
import { mockReimbursements } from '@/mock/reimbursements'

const route = useRoute()
const router = useRouter()

// TODO(F13): 后端 REIM-2 就绪后，替换为 reimbursementApi.detail(route.params.id)
const detail = ref<Reimbursement | null>(
  mockReimbursements.find(r => r.id === route.params.id) ?? null
)

const totalAmount = computed(() =>
  (detail.value?.items ?? []).reduce((sum, i) => sum + i.amount, 0)
)

const statusLabel = (s: ReimbursementStatus) =>
  ({ draft: '草稿', pending: '待审批', approved: '已通过', rejected: '已驳回' })[s] ?? s

const statusTagType = (s: ReimbursementStatus) =>
  ({ draft: 'info', pending: 'warning', approved: 'success', rejected: 'danger' })[s] as
    'info' | 'warning' | 'success' | 'danger'
</script>

<style scoped>
.reimbursement-detail {
  max-width: 1000px;
}
.section-card {
  margin-bottom: 16px;
}
.total-amount {
  margin-top: 16px;
  text-align: right;
  font-size: 15px;
  color: #595959;
}
.total-amount span {
  color: #fa8c16;
  font-size: 18px;
  font-weight: 600;
}
.muted {
  color: #c0c4cc;
}
</style>

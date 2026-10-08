<template>
  <div class="reimbursement-detail" v-loading="loading">
    <el-button :icon="Back" @click="router.back()" style="margin-bottom: 16px">返回</el-button>

    <template v-if="detail">
      <!-- 报销信息 -->
      <el-card shadow="never" class="section-card">
        <template #header>报销单详情</template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="报销标题">{{ detail.title }}</el-descriptions-item>
          <el-descriptions-item label="报销金额">
            <span class="amount">￥{{ detail.total_amount.toLocaleString() }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="申请人">{{ detail.user_name }}（{{ detail.department }}）</el-descriptions-item>
          <el-descriptions-item label="关联差旅申请">{{ detail.travel_request_title ?? '无' }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(detail.status)">{{ statusLabel(detail) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ detail.created_at }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.reject_reason" label="驳回原因" :span="2">
            <span class="reject-reason">{{ detail.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 审批留痕 -->
      <el-card v-if="detail.approvals?.length" shadow="never" class="section-card">
        <template #header>审批信息</template>
        <el-table :data="detail.approvals" border>
          <el-table-column label="审批级" width="80">
            <template #default="{ row }">{{ row.step === 2 ? '二级·财务' : '一级·经理' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-tag :type="row.action === 'approve' ? 'success' : 'danger'" size="small">
                {{ row.action === 'approve' ? '通过' : '驳回' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="comment" label="审批意见" min-width="160" />
          <el-table-column prop="approver_name" label="审批人" width="110" />
          <el-table-column prop="created_at" label="审批时间" min-width="170" />
        </el-table>
      </el-card>

      <!-- 操作区 -->
      <el-card v-if="canAct" shadow="never" class="section-card">
        <template #header>操作</template>
        <div class="actions">
          <template v-if="detail.status === 'draft'">
            <el-button type="primary" :loading="acting" @click="handleSubmit">提交审批</el-button>
          </template>
          <template v-else-if="detail.status === 'pending' && roleMatchesStep">
            <el-button type="success" :loading="acting" @click="handleApprove">通过</el-button>
            <el-button type="danger" :loading="acting" @click="handleReject">驳回</el-button>
          </template>
          <span v-else class="muted">当前状态无需操作</span>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import type { Reimbursement, ReimbursementStatus } from '@/types'
import { reimbursementApi } from '@/api/reimbursement'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const acting = ref(false)
const detail = ref<Reimbursement | null>(null)

// 审批角色与当前步骤匹配（REQ-8）：step1 需 approver/admin，step2 需 finance/admin
const roleMatchesStep = computed(() => {
  const d = detail.value
  if (!d || d.status !== 'pending') return false
  if (d.current_step === 1) return auth.user?.role === 'approver' || auth.user?.role === 'admin'
  if (d.current_step === 2) return auth.user?.role === 'finance' || auth.user?.role === 'admin'
  return false
})

const canAct = computed(() => {
  const d = detail.value
  if (!d) return false
  return d.status === 'draft' || (d.status === 'pending' && roleMatchesStep.value)
})

function statusLabel(row: Reimbursement) {
  if (row.status === 'pending') {
    return row.current_step === 2 ? '待审批·财务' : '待审批·经理'
  }
  return ({ draft: '草稿', approved: '已通过', rejected: '已驳回', paid: '已打款' })[row.status] ?? row.status
}

const statusTagType = (s: ReimbursementStatus) =>
  ({ draft: 'info', pending: 'warning', approved: 'success', rejected: 'danger', paid: 'success' })[s] as
    'info' | 'warning' | 'success' | 'danger'

async function load() {
  loading.value = true
  try {
    const { data } = await reimbursementApi.detail(route.params.id as string)
    detail.value = data
  } catch {
    detail.value = null
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  if (!detail.value) return
  acting.value = true
  try {
    await reimbursementApi.submit(detail.value.id)
    ElMessage.success('已提交审批')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    acting.value = false
  }
}

async function handleApprove() {
  if (!detail.value) return
  acting.value = true
  try {
    await reimbursementApi.approve(detail.value.id)
    ElMessage.success('已通过')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    acting.value = false
  }
}

async function handleReject() {
  if (!detail.value) return
  const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回确认', {
    type: 'warning',
    inputValidator: v => (v?.trim() ? true : '驳回原因不能为空'),
  })
  acting.value = true
  try {
    await reimbursementApi.reject(detail.value.id, value)
    ElMessage.success('已驳回')
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    acting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.reimbursement-detail {
  max-width: 1000px;
}
.section-card {
  margin-bottom: 16px;
}
.amount {
  color: #fa8c16;
  font-weight: 600;
}
.reject-reason {
  color: #f56c6c;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.muted {
  color: #c0c4cc;
}
</style>

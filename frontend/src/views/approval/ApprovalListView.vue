<template>
  <div class="approval-list">
    <el-card shadow="never" class="filter-card">
      <el-form inline @submit.prevent>
        <el-form-item label="业务类型">
          <el-select v-model="query.bizType" placeholder="全部" clearable style="width: 160px">
            <el-option label="差旅申请" value="travel" />
            <el-option label="报销单" value="reimbursement" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" clearable style="width: 140px">
            <el-option label="待审批" value="pending" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
          <el-button :icon="Refresh" @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <!-- TODO(F13): A-08/A-09 就绪后对接 GET /api/travel/requests 与 approve/reject；当前 mock 渲染 -->
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="title" label="事由/标题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="applicant" label="申请人" width="100" />
        <el-table-column prop="department" label="部门" width="110" />
        <el-table-column label="金额" width="110">
          <template #default="{ row }">
            <span class="amount">￥{{ row.amount.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" min-width="170" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending'">
              <el-button link type="success" @click="handleApprove(row)">通过</el-button>
              <el-button link type="danger" @click="handleReject(row)">驳回</el-button>
            </template>
            <span v-else class="muted">已处理</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh } from '@element-plus/icons-vue'

interface ApprovalRow {
  id: string
  title: string
  applicant: string
  department: string
  amount: number
  status: 'pending' | 'approved' | 'rejected'
  submitted_at: string
}

const loading = ref(false)

const query = reactive({
  bizType: '',
  status: '' as ApprovalRow['status'] | '',
})

// TODO(F13): mock 占位，接口就绪后移除
const items = ref<ApprovalRow[]>([
  {
    id: 'a1',
    title: '成都客户拜访',
    applicant: '李四',
    department: '技术部',
    amount: 2680,
    status: 'pending',
    submitted_at: '2026-05-11 11:20:00',
  },
  {
    id: 'a2',
    title: '广州市场调研',
    applicant: '王五',
    department: '市场部',
    amount: 1980,
    status: 'pending',
    submitted_at: '2026-03-08 16:40:00',
  },
])

const statusLabel = (s: ApprovalRow['status']) =>
  ({ pending: '待审批', approved: '已通过', rejected: '已驳回' })[s] ?? s

const statusTagType = (s: ApprovalRow['status']) =>
  ({ pending: 'warning', approved: 'success', rejected: 'danger' })[s] as
    'warning' | 'success' | 'danger'

function handleSearch() {
  // TODO(F13): 真实分页查询
}

function handleReset() {
  query.bizType = ''
  query.status = ''
}

async function handleApprove(row: ApprovalRow) {
  // TODO(F13): POST /api/travel/requests/{id}/approve（契约 4 节）
  row.status = 'approved'
  ElMessage.success(`已通过「${row.title}」`)
}

async function handleReject(row: ApprovalRow) {
  const { value } = await ElMessageBox.prompt('请输入驳回意见', '驳回确认', {
    type: 'warning',
    inputValidator: v => (v?.trim() ? true : '驳回意见不能为空'),
  })
  // TODO(F13): POST /api/travel/requests/{id}/reject，comment=value
  row.status = 'rejected'
  ElMessage.success('已驳回')
}
</script>

<style scoped>
.approval-list {
  max-width: 1200px;
}
.filter-card {
  margin-bottom: 16px;
}
.amount {
  color: #fa8c16;
  font-weight: 600;
}
.muted {
  color: #c0c4cc;
}
</style>

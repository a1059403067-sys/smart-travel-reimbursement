<template>
  <div class="reimbursement-list">
    <!-- 搜索区 -->
    <el-card shadow="never" class="search-card">
      <el-form inline @submit.prevent>
        <el-form-item label="报销单号">
          <el-input
            v-model="query.code"
            placeholder="请输入报销单号"
            clearable
            style="width: 220px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" clearable style="width: 140px">
            <el-option label="草稿" value="draft" />
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
      <el-button type="primary" :icon="Plus" @click="router.push('/reimbursements/new')">
        新增报销单
      </el-button>
    </el-card>

    <!-- 表格 -->
    <el-card shadow="never">
      <el-table :data="pagedItems" v-loading="loading" stripe>
        <el-table-column prop="code" label="报销单号" min-width="130" />
        <el-table-column prop="reason" label="出差事由" min-width="150" show-overflow-tooltip />
        <el-table-column prop="destination" label="目的地" width="90" />
        <el-table-column label="出差日期" min-width="190">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="报销金额" width="110">
          <template #default="{ row }">
            <span class="amount">￥{{ row.amount.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="applicant" label="申请人" width="90" />
        <el-table-column prop="department" label="部门" width="100" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="submitted_at" label="提交时间" min-width="170" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/reimbursements/${row.id}`)">
              详情
            </el-button>
            <template v-if="canEdit(row)">
              <el-button link type="primary" @click="handleEdit(row)">编辑</el-button>
              <el-button link type="success" @click="handleSubmit(row)">提交</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination">
        <span class="total-text">共 {{ filteredItems.length }} 条</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="filteredItems.length"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next, jumper"
          @size-change="handleSearch"
          @current-change="handleSearch"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import type { Reimbursement, ReimbursementStatus } from '@/types'
import { mockReimbursements } from '@/mock/reimbursements'

const router = useRouter()
const loading = ref(false)

// TODO(F13): 后端 REIM-1 就绪后，将 mock 替换为 reimbursementApi.list 真实分页查询
const items = ref<Reimbursement[]>(mockReimbursements)

const query = reactive({
  code: '',
  status: '' as ReimbursementStatus | '',
  page: 1,
  page_size: 10,
})

const filteredItems = computed(() =>
  items.value.filter(i =>
    (!query.code || i.code.includes(query.code)) &&
    (!query.status || i.status === query.status)
  )
)

const pagedItems = computed(() => {
  const start = (query.page - 1) * query.page_size
  return filteredItems.value.slice(start, start + query.page_size)
})

const statusLabel = (s: ReimbursementStatus) =>
  ({ draft: '草稿', pending: '待审批', approved: '已通过', rejected: '已驳回' })[s] ?? s

const statusTagType = (s: ReimbursementStatus) =>
  ({ draft: 'info', pending: 'warning', approved: 'success', rejected: 'danger' })[s] as
    'info' | 'warning' | 'success' | 'danger'

// 草稿/已驳回可编辑与重新提交
const canEdit = (row: Reimbursement) => row.status === 'draft' || row.status === 'rejected'

function handleSearch() {
  query.page = 1
}

function handleReset() {
  query.code = ''
  query.status = ''
  query.page = 1
}

function handleEdit(row: Reimbursement) {
  router.push(`/reimbursements/${row.id}?edit=1`)
}

async function handleSubmit(row: Reimbursement) {
  await ElMessageBox.confirm(`确认提交报销单 ${row.code} 进入审批流程？`, '提交确认', {
    type: 'warning',
  })
  // TODO(F13): 调用 reimbursementApi.submit(row.id)
  row.status = 'pending'
  ElMessage.success('已提交审批')
}

onMounted(handleSearch)
</script>

<style scoped>
.reimbursement-list {
  max-width: 1400px;
}
.search-card {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.amount {
  color: #fa8c16;
  font-weight: 600;
}
.pagination {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}
.total-text {
  font-size: 13px;
  color: #8c8c8c;
}
</style>

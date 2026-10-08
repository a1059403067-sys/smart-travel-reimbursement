<template>
  <div class="reimbursement-list">
    <!-- 搜索区 -->
    <el-card shadow="never" class="search-card">
      <el-form inline @submit.prevent>
        <el-form-item label="状态">
          <el-select v-model="query.status" placeholder="全部" clearable style="width: 160px" @change="handleSearch">
            <el-option label="草稿" value="draft" />
            <el-option label="待审批" value="pending" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
            <el-option label="已打款" value="paid" />
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
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="title" label="报销标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="报销金额" width="120">
          <template #default="{ row }">
            <span class="amount">￥{{ row.total_amount.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="user_name" label="申请人" width="100" />
        <el-table-column prop="department" label="部门" width="110" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="170" />
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/reimbursements/${row.id}`)">
              详情
            </el-button>
            <el-button v-if="row.status === 'draft'" link type="success" @click="handleSubmit(row)">
              提交
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页（服务端分页，契约 REQ-8 的 page/page_size） -->
      <div class="pagination">
        <span class="total-text">共 {{ total }} 条</span>
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="sizes, prev, pager, next, jumper"
          @size-change="handleSearch"
          @current-change="load"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Refresh, Plus } from '@element-plus/icons-vue'
import type { Reimbursement, ReimbursementStatus } from '@/types'
import { reimbursementApi } from '@/api/reimbursement'

const router = useRouter()
const loading = ref(false)

const items = ref<Reimbursement[]>([])
const total = ref(0)

const query = reactive({
  status: '' as ReimbursementStatus | '',
  page: 1,
  page_size: 10,
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
    const { data } = await reimbursementApi.list({
      mine: true,
      page: query.page,
      page_size: query.page_size,
      status: query.status || undefined,
    })
    items.value = data.items ?? []
    total.value = data.total ?? 0
  } catch {
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  load()
}

function handleReset() {
  query.status = ''
  handleSearch()
}

async function handleSubmit(row: Reimbursement) {
  try {
    await ElMessageBox.confirm(`确认提交报销单「${row.title}」进入审批流程？`, '提交确认', {
      type: 'warning',
    })
  } catch {
    return // 用户取消
  }
  try {
    await reimbursementApi.submit(row.id)
    ElMessage.success('已提交审批')
    await load()
  } catch { /* 拦截器已提示 */ }
}

onMounted(load)
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

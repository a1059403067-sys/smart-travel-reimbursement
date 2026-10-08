<template>
  <div class="approval-list">
    <!-- R-31 修复：审批中心 to_review 固定待审批语义，去掉状态筛选（选"已通过"等恒为空） -->
    <el-card shadow="never" class="filter-card">
      <span class="filter-tip">审批中心：展示待您审批的差旅申请</span>
      <el-button :icon="Refresh" @click="load">刷新</el-button>
    </el-card>

    <el-card shadow="never">
      <!-- REQ-6：GET /api/travel/requests?to_review=true（approver/admin 看待审批列表） -->
      <el-table :data="items" v-loading="loading" stripe>
        <el-table-column prop="title" label="申请标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="行程" min-width="180">
          <template #default="{ row }">
            {{ row.departure_city }} → {{ row.arrival_city }}
            <span class="muted">（{{ row.start_date }} ~ {{ row.end_date }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ tripTypeLabel(row.trip_type) }}</template>
        </el-table-column>
        <el-table-column label="预估金额" width="120">
          <template #default="{ row }">
            <span class="amount">￥{{ row.estimated_amount.toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="user_name" label="申请人" width="100" />
        <el-table-column prop="department" label="部门" width="110" />
        <el-table-column prop="created_at" label="提交时间" min-width="170" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="showDetail(row)">详情</el-button>
            <template v-if="row.status === 'pending'">
              <el-button link type="success" @click="handleApprove(row)">通过</el-button>
              <el-button link type="danger" @click="handleReject(row)">驳回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>

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

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="差旅申请详情" width="640px">
      <template v-if="current">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="标题" :span="2">{{ current.title }}</el-descriptions-item>
          <el-descriptions-item label="行程">{{ current.departure_city }} → {{ current.arrival_city }}</el-descriptions-item>
          <el-descriptions-item label="类型">{{ tripTypeLabel(current.trip_type) }}</el-descriptions-item>
          <el-descriptions-item label="日期">{{ current.start_date }} ~ {{ current.end_date }}</el-descriptions-item>
          <el-descriptions-item label="预估金额">￥{{ current.estimated_amount.toLocaleString() }}</el-descriptions-item>
          <el-descriptions-item label="事由" :span="2">{{ current.reason }}</el-descriptions-item>
          <el-descriptions-item label="申请人">{{ current.user_name }}（{{ current.department }}）</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(current.status)">{{ statusLabel(current.status) }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item v-if="current.reject_reason" label="驳回原因" :span="2">
            <span class="reject-reason">{{ current.reject_reason }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 审批留痕 -->
        <template v-if="current.approvals?.length">
          <div class="approvals-title">审批留痕</div>
          <el-table :data="current.approvals" border size="small">
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-tag :type="row.action === 'approve' ? 'success' : 'danger'" size="small">
                  {{ row.action === 'approve' ? '通过' : '驳回' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="comment" label="意见" min-width="140" />
            <el-table-column prop="approver_name" label="审批人" width="100" />
            <el-table-column prop="created_at" label="时间" min-width="160" />
          </el-table>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import type { TravelRequest, TravelRequestStatus } from '@/types'
import { travelApi } from '@/api/travel'

const loading = ref(false)
const items = ref<TravelRequest[]>([])
const total = ref(0)
const detailVisible = ref(false)
const current = ref<TravelRequest | null>(null)

const query = reactive({
  page: 1,
  page_size: 10,
})

// trip_type 中文映射（契约未声明枚举，R-26 待补；此处兜底映射）
const tripTypeLabel = (t: string) =>
  ({ visit: '客户拜访', meeting: '会议', project: '项目驻场', entertain: '招待', other: '其他' })[t] ?? t

const statusLabel = (s: TravelRequestStatus) =>
  ({ draft: '草稿', pending: '待审批', approved: '已通过', rejected: '已驳回' })[s] ?? s

const statusTagType = (s: TravelRequestStatus) =>
  ({ draft: 'info', pending: 'warning', approved: 'success', rejected: 'danger' })[s] as
    'info' | 'warning' | 'success' | 'danger'

async function load() {
  loading.value = true
  try {
    const { data } = await travelApi.requests({
      to_review: true,
      page: query.page,
      page_size: query.page_size,
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

async function showDetail(row: TravelRequest) {
  detailVisible.value = true
  try {
    const { data } = await travelApi.requestDetail(row.id)
    current.value = data
  } catch {
    current.value = row // 详情接口失败时降级展示列表行数据
  }
}

async function handleApprove(row: TravelRequest) {
  try {
    await ElMessageBox.confirm(`确认通过「${row.title}」？`, '审批确认', { type: 'warning' })
  } catch {
    return // 用户取消
  }
  try {
    await travelApi.requestApprove(row.id)
    ElMessage.success('已通过')
    await load()
  } catch { /* 拦截器已提示 */ }
}

async function handleReject(row: TravelRequest) {
  let reason: string
  try {
    const ret = await ElMessageBox.prompt('请输入驳回原因', '驳回确认', {
      type: 'warning',
      inputValidator: v => (v?.trim() ? true : '驳回原因不能为空'),
    })
    reason = ret.value
  } catch {
    return // 用户取消
  }
  try {
    await travelApi.requestReject(row.id, reason)
    ElMessage.success('已驳回')
    await load()
  } catch { /* 拦截器已提示 */ }
}

onMounted(load)
</script>

<style scoped>
.approval-list {
  max-width: 1400px;
}
.filter-card {
  margin-bottom: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-tip {
  font-size: 13px;
  color: #8c8c8c;
}
.amount {
  color: #fa8c16;
  font-weight: 600;
}
.muted {
  color: #c0c4cc;
  font-size: 12px;
}
.reject-reason {
  color: #f56c6c;
}
.approvals-title {
  margin: 16px 0 8px;
  font-size: 14px;
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

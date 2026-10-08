<template>
  <div class="reimbursement-edit">
    <el-button :icon="Back" @click="router.back()" style="margin-bottom: 16px">返回</el-button>

    <el-card shadow="never" class="section-card">
      <template #header>{{ isEdit ? '编辑报销单' : '新增报销单' }}</template>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="出差事由" prop="reason">
              <el-input v-model="form.reason" placeholder="例如：杭州技术研讨会" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="目的地" prop="destination">
              <el-input v-model="form.destination" placeholder="例如：杭州" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="开始日期" prop="start_date">
              <el-date-picker
                v-model="form.start_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择开始日期"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="结束日期" prop="end_date">
              <el-date-picker
                v-model="form.end_date"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择结束日期"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="items-header">
          <span>费用明细</span>
          <el-button size="small" type="primary" plain :icon="Plus" @click="addItem">
            添加费用
          </el-button>
        </div>
      </template>

      <el-table :data="form.items" border>
        <el-table-column label="费用类型" width="130">
          <template #default="{ row }">
            <el-select v-model="row.expense_type" placeholder="选择类型">
              <el-option v-for="t in expenseTypes" :key="t" :label="t" :value="t" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="金额（元）" width="150">
          <template #default="{ row }">
            <el-input-number v-model="row.amount" :min="0" :precision="2" style="width: 100%" />
          </template>
        </el-table-column>
        <el-table-column label="费用日期" width="170">
          <template #default="{ row }">
            <el-date-picker
              v-model="row.expense_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择日期"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="备注" min-width="140">
          <template #default="{ row }">
            <el-input v-model="row.remark" placeholder="备注（选填）" />
          </template>
        </el-table-column>
        <el-table-column label="发票附件" width="120">
          <template #default="{ row }">
            <el-upload
              :auto-upload="false"
              :limit="1"
              accept=".pdf,.jpg,.jpeg,.png"
              :on-change="(f: UploadFile) => (row.invoice_attachment = (f.raw as File)?.name)"
            >
              <el-button link type="primary">上传</el-button>
            </el-upload>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70">
          <template #default="{ $index }">
            <el-button link type="danger" :disabled="form.items.length <= 1" @click="removeItem($index)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="total-amount">合计金额：<span>￥{{ totalAmount.toLocaleString() }}</span></div>
    </el-card>

    <div class="form-actions">
      <el-button size="large" @click="handleSaveDraft">保存草稿</el-button>
      <el-button size="large" type="primary" :loading="submitting" @click="handleSubmit">
        提交审批
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Back, Plus } from '@element-plus/icons-vue'
import type { UploadFile } from 'element-plus'
import type { ExpenseItem } from '@/types'

const route = useRoute()
const router = useRouter()
const isEdit = computed(() => route.path !== '/reimbursements/new')

const expenseTypes = ['交通费', '住宿费', '餐饮费', '其他']

const formRef = ref<FormInstance>()
const submitting = ref(false)

interface ItemForm extends ExpenseItem {
  expense_type: string
  amount: number
  expense_date: string
}

const emptyItem = (): ItemForm => ({
  expense_type: '',
  amount: 0,
  expense_date: '',
  remark: '',
})

const form = reactive({
  reason: '',
  destination: '',
  start_date: '',
  end_date: '',
  items: [emptyItem()] as ItemForm[],
})

const rules: FormRules = {
  reason: [{ required: true, message: '请输入出差事由', trigger: 'blur' }],
  destination: [{ required: true, message: '请输入目的地', trigger: 'blur' }],
  start_date: [{ required: true, message: '请选择开始日期', trigger: 'change' }],
  end_date: [{ required: true, message: '请选择结束日期', trigger: 'change' }],
}

const totalAmount = computed(() => form.items.reduce((sum, i) => sum + (i.amount || 0), 0))

function addItem() {
  form.items.push(emptyItem())
}

function removeItem(index: number) {
  form.items.splice(index, 1)
}

async function validate(): Promise<boolean> {
  try {
    await formRef.value?.validate()
    const hasInvalidItem = form.items.some(
      i => !i.expense_type || !i.expense_date || i.amount <= 0
    )
    if (hasInvalidItem) {
      ElMessage.warning('请完整填写费用明细（类型/金额/日期）')
      return false
    }
    return true
  } catch {
    return false
  }
}

async function handleSaveDraft() {
  if (!(await validate())) return
  // TODO(F13): 契约补充报销单 API 后对接（保存为 draft）
  ElMessage.info('保存接口待后端契约补充（当前为演示占位）')
  router.push('/reimbursements')
}

async function handleSubmit() {
  if (!(await validate())) return
  submitting.value = true
  try {
    // TODO(F13): 契约补充报销单 API 后对接（status → pending）
    await new Promise(r => setTimeout(r, 400))
    ElMessage.success('已提交审批')
    router.push('/reimbursements')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.reimbursement-edit {
  max-width: 1100px;
}
.section-card {
  margin-bottom: 16px;
}
.items-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
.form-actions {
  text-align: right;
}
</style>

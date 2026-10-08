<template>
  <div class="reimbursement-edit">
    <el-button :icon="Back" @click="router.back()" style="margin-bottom: 16px">返回</el-button>

    <el-card shadow="never" class="section-card">
      <template #header>新增报销单</template>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="报销标题" prop="title">
          <el-input v-model="form.title" placeholder="例如：杭州出差报销" />
        </el-form-item>
        <el-form-item label="报销金额" prop="total_amount">
          <el-input-number v-model="form.total_amount" :min="0" :precision="2" style="width: 220px" />
          <span class="amount-hint">元</span>
        </el-form-item>
        <el-form-item label="关联差旅申请">
          <el-input-number v-model="form.travel_request_id" :min="1" :precision="0" placeholder="选填" style="width: 220px" />
          <span class="field-hint">差旅申请 ID，选填</span>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="form-actions">
      <el-button size="large" :loading="acting" @click="handleSaveDraft">保存草稿</el-button>
      <el-button size="large" type="primary" :loading="acting" @click="handleCreateAndSubmit">
        创建并提交
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Back } from '@element-plus/icons-vue'
import { reimbursementApi } from '@/api/reimbursement'

const router = useRouter()

const formRef = ref<FormInstance>()
const acting = ref(false)

const form = reactive({
  title: '',
  total_amount: 0,
  travel_request_id: undefined as number | undefined,
})

const rules: FormRules = {
  title: [{ required: true, message: '请输入报销标题', trigger: 'blur' }],
  total_amount: [{ required: true, message: '请输入报销金额', trigger: 'blur' }],
}

async function validate(): Promise<boolean> {
  try {
    await formRef.value?.validate()
    return true
  } catch {
    return false
  }
}

async function create(): Promise<number | string | null> {
  const { data } = await reimbursementApi.create({
    title: form.title.trim(),
    total_amount: form.total_amount,
    travel_request_id: form.travel_request_id,
  })
  return data.id
}

async function handleSaveDraft() {
  if (!(await validate())) return
  acting.value = true
  try {
    await create()
    ElMessage.success('已保存草稿')
    router.push('/reimbursements')
  } catch { /* 拦截器已提示 */ } finally {
    acting.value = false
  }
}

async function handleCreateAndSubmit() {
  if (!(await validate())) return
  acting.value = true
  try {
    const id = await create()
    if (id != null) await reimbursementApi.submit(id)
    ElMessage.success('已提交审批')
    router.push('/reimbursements')
  } catch { /* 拦截器已提示 */ } finally {
    acting.value = false
  }
}
</script>

<style scoped>
.reimbursement-edit {
  max-width: 700px;
}
.section-card {
  margin-bottom: 16px;
}
.amount-hint {
  margin-left: 8px;
  color: #595959;
}
.field-hint {
  margin-left: 8px;
  color: #c0c4cc;
  font-size: 12px;
}
.form-actions {
  text-align: right;
}
</style>

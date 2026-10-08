<template>
  <div class="analytics">
    <!-- 维度切换 -->
    <el-card shadow="never" class="filter-card">
      <el-radio-group v-model="tripType" @change="loadStats">
        <el-radio-button value="">全部差旅</el-radio-button>
        <el-radio-button value="entertain">招待类</el-radio-button>
      </el-radio-group>
    </el-card>

    <template v-if="stats">
      <!-- 汇总卡片 -->
      <el-row :gutter="16" class="stat-row">
        <el-col :span="12">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">差旅总次数</div>
            <div class="stat-value">{{ stats.summary.total_trips }}</div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-label">差旅总金额</div>
            <div class="stat-value">￥{{ stats.summary.total_amount.toLocaleString() }}</div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 部门费用占比 -->
      <el-row>
        <el-col :span="24">
          <el-card shadow="hover">
            <template #header>部门费用占比</template>
            <div ref="pieRef" class="chart" />
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else-if="loadError" :description="loadError" />
    <div v-else class="loading-box" v-loading="true" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/composables/useECharts'
import { travelApi } from '@/api/travel'
import type { TravelStats } from '@/types'

const tripType = ref('')
const stats = ref<TravelStats | null>(null)
const loadError = ref<string | null>(null)

const pieRef = ref<HTMLElement>()
const pieChart = useECharts(pieRef)

const palette = ['#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2']

async function loadStats() {
  loadError.value = null
  try {
    const { data } = await travelApi.stats(tripType.value ? { trip_type: tripType.value } : undefined)
    stats.value = data
    renderPie(data)
  } catch {
    // 拦截器已弹出错误提示；此处保留空态
    stats.value = null
    loadError.value = '统计数据加载失败，请确认后端已启动（http://localhost:8006）'
  }
}

function renderPie(data: TravelStats) {
  const option: EChartsOption = {
    tooltip: { trigger: 'item', formatter: '{b}: ￥{c}（{d}%）' },
    legend: { bottom: 0 },
    color: palette,
    series: [
      {
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['50%', '45%'],
        label: { formatter: '{b}\n￥{c}' },
        data: data.department_expense,
      },
    ],
  }
  pieChart.setOption(option)
}

onMounted(loadStats)
</script>

<style scoped>
.analytics {
  max-width: 1000px;
}
.filter-card {
  margin-bottom: 16px;
}
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  text-align: center;
}
.stat-label {
  font-size: 13px;
  color: #8c8c8c;
}
.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: #1677ff;
  margin-top: 6px;
}
.chart {
  height: 380px;
}
.loading-box {
  height: 300px;
}
</style>

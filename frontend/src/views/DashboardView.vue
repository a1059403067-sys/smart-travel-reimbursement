<template>
  <div class="dashboard">
    <template v-if="data">
      <!-- 统计卡片 -->
      <el-row :gutter="16" class="stat-row">
        <el-col :span="6" v-for="card in statCards" :key="card.label">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-body">
              <div class="stat-icon" :style="{ background: card.color }">{{ card.icon }}</div>
              <div>
                <div class="stat-label">{{ card.label }}</div>
                <div class="stat-value">{{ card.value }}</div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- 图表行 1：费用类型占比 + 部门费用占比 -->
      <el-row :gutter="16" class="chart-row">
        <el-col :span="12">
          <el-card shadow="hover">
            <template #header>费用类型占比</template>
            <div ref="typePieRef" class="chart" />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="hover">
            <template #header>部门费用占比</template>
            <div ref="deptPieRef" class="chart" />
          </el-card>
        </el-col>
      </el-row>

      <!-- 图表行 2：近 6 个月趋势 -->
      <el-row class="chart-row">
        <el-col :span="24">
          <el-card shadow="hover">
            <template #header>近 6 个月差旅趋势</template>
            <div ref="trendRef" class="chart chart-lg" />
          </el-card>
        </el-col>
      </el-row>
    </template>

    <el-empty v-else-if="loadError" :description="loadError" />
    <div v-else class="loading-box" v-loading="true" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/composables/useECharts'
import { travelApi } from '@/api/travel'
import type { DashboardData } from '@/types'

const data = ref<DashboardData | null>(null)
const loadError = ref<string | null>(null)

const statCards = computed(() => {
  const s = data.value!.summary
  return [
    { label: '差旅总次数', value: String(s.total_trips), icon: '📄', color: '#e6f4ff' },
    { label: '差旅总金额', value: `￥${s.total_amount.toLocaleString()}`, icon: '💰', color: '#f0f5ff' },
    { label: '待审批', value: String(s.pending_approvals ?? 0), icon: '⏳', color: '#fff7e6' },
    { label: '本月新增', value: String(s.month_new_trips ?? 0), icon: '🆕', color: '#f6ffed' },
  ]
})

// ── 图表 ──
const typePieRef = ref<HTMLElement>()
const deptPieRef = ref<HTMLElement>()
const trendRef = ref<HTMLElement>()
const typePieChart = useECharts(typePieRef)
const deptPieChart = useECharts(deptPieRef)
const lineChart = useECharts(trendRef)

const palette = ['#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2']

function pieOption(items: Array<{ name: string; value: number }>): EChartsOption {
  return {
    tooltip: { trigger: 'item', formatter: '{b}: ￥{c}（{d}%）' },
    legend: { bottom: 0 },
    color: palette,
    series: [
      {
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['50%', '45%'],
        label: { formatter: '{b}\n￥{c}' },
        data: items,
      },
    ],
  }
}

function renderCharts(d: DashboardData) {
  typePieChart.setOption(pieOption(d.expense_by_type ?? []))
  deptPieChart.setOption(pieOption(d.department_expense ?? []))

  const trend = d.monthly_trend ?? []
  const lineOption: EChartsOption = {
    tooltip: { trigger: 'axis' },
    legend: { data: ['差旅次数', '金额'] },
    grid: { left: 60, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', boundaryGap: false, data: trend.map(i => i.month) },
    yAxis: [{ type: 'value', name: '次数', minInterval: 1 }, { type: 'value', name: '金额' }],
    series: [
      {
        name: '差旅次数',
        type: 'line',
        smooth: true,
        itemStyle: { color: '#1677ff' },
        data: trend.map(i => i.trips),
      },
      {
        name: '金额',
        type: 'line',
        smooth: true,
        yAxisIndex: 1,
        itemStyle: { color: '#fa8c16' },
        areaStyle: { opacity: 0.1, color: '#fa8c16' },
        data: trend.map(i => i.amount),
      },
    ],
  }
  lineChart.setOption(lineOption)
}

onMounted(async () => {
  try {
    const { data: d } = await travelApi.dashboard()
    data.value = d
    renderCharts(d)
  } catch {
    loadError.value = '数据加载失败，请确认后端已启动（http://localhost:8006）'
  }
})
</script>

<style scoped>
.dashboard {
  max-width: 1200px;
}
.stat-row {
  margin-bottom: 16px;
}
.stat-card {
  cursor: default;
}
.stat-body {
  display: flex;
  align-items: center;
  gap: 14px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;
}
.stat-label {
  font-size: 13px;
  color: #8c8c8c;
}
.stat-value {
  font-size: 22px;
  font-weight: 600;
  color: #1a1a1a;
  margin-top: 2px;
}
.chart-row {
  margin-bottom: 16px;
}
.chart {
  height: 320px;
}
.chart-lg {
  height: 300px;
}
.loading-box {
  height: 300px;
}
</style>

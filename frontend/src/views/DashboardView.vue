<template>
  <div class="dashboard">
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

    <!-- 图表行 1：费用类型占比 + 状态分布 -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>费用类型占比</template>
          <div ref="typePieRef" class="chart" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="hover">
          <template #header>报销单状态分布</template>
          <div ref="statusBarRef" class="chart" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表行 2：近 6 个月趋势 -->
    <el-row class="chart-row">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>近 6 个月报销趋势</template>
          <div ref="trendRef" class="chart chart-lg" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { EChartsOption } from 'echarts'
import { useECharts } from '@/composables/useECharts'

// TODO(F13): B8 聚合接口就绪后，将以下 mock 数据替换为 GET /analytics/dashboard 真实返回
const summary = {
  total_count: 7,
  pending_count: 2,
  approved_count: 3,
  total_amount: 6420,
}
const expenseTypeDistribution = [
  { name: '交通费', value: 6270 },
  { name: '住宿费', value: 5570 },
  { name: '餐饮费', value: 1160 },
]
const statusDistribution = [
  { name: '草稿', value: 0 },
  { name: '待审批', value: 2 },
  { name: '已通过', value: 3 },
  { name: '已驳回', value: 2 },
]
const monthlyTrend = [
  { month: '2026-01', amount: 2850 },
  { month: '2026-02', amount: 3200 },
  { month: '2026-03', amount: 3540 },
  { month: '2026-04', amount: 2680 },
  { month: '2026-05', amount: 2900 },
  { month: '2026-06', amount: 4330 },
]

const statCards = computed(() => [
  { label: '报销单总数', value: String(summary.total_count), icon: '📄', color: '#e6f4ff' },
  { label: '待审批', value: String(summary.pending_count), icon: '⏳', color: '#fff7e6' },
  { label: '已通过', value: String(summary.approved_count), icon: '✅', color: '#f6ffed' },
  { label: '报销总额', value: `￥${summary.total_amount.toLocaleString()}`, icon: '💰', color: '#f0f5ff' },
])

// ── 图表 ──
const typePieRef = ref<HTMLElement>()
const statusBarRef = ref<HTMLElement>()
const trendRef = ref<HTMLElement>()
const pieChart = useECharts(typePieRef)
const barChart = useECharts(statusBarRef)
const lineChart = useECharts(trendRef)

const palette = ['#1677ff', '#52c41a', '#faad14', '#ff4d4f', '#722ed1', '#13c2c2']

const pieOption: EChartsOption = {
  tooltip: { trigger: 'item', formatter: '{b}: ￥{c}（{d}%）' },
  legend: { bottom: 0 },
  color: palette,
  series: [
    {
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '45%'],
      label: { formatter: '{b}\n￥{c}' },
      data: expenseTypeDistribution,
    },
  ],
}

const barOption: EChartsOption = {
  tooltip: { trigger: 'axis' },
  grid: { left: 40, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', data: statusDistribution.map(i => i.name) },
  yAxis: { type: 'value', minInterval: 1 },
  series: [
    {
      type: 'bar',
      barWidth: 36,
      itemStyle: { color: '#1677ff', borderRadius: [4, 4, 0, 0] },
      label: { show: true, position: 'top' },
      data: statusDistribution.map(i => i.value),
    },
  ],
}

const lineOption: EChartsOption = {
  tooltip: { trigger: 'axis' },
  grid: { left: 60, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', boundaryGap: false, data: monthlyTrend.map(i => i.month) },
  yAxis: { type: 'value' },
  series: [
    {
      type: 'line',
      smooth: true,
      itemStyle: { color: '#1677ff' },
      areaStyle: { opacity: 0.12, color: '#1677ff' },
      data: monthlyTrend.map(i => i.amount),
    },
  ],
}

onMounted(() => {
  pieChart.setOption(pieOption)
  barChart.setOption(barOption)
  lineChart.setOption(lineOption)
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
</style>

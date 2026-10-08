import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'

// ECharts 生命周期封装：挂载时 init、卸载时 dispose、窗口缩放自动 resize
// 修复 R-01：图表容器常在 v-if 内晚于 onMounted 出现（首次渲染 elRef 为空）。
// 处理方式：watch elRef 出现即 init；chart 未就绪时 setOption 先缓存 pendingOption，
// init 完成后自动应用，调用方无需感知挂载时序。
export function useECharts(elRef: Ref<HTMLElement | undefined>) {
  let chart: echarts.ECharts | null = null
  let pendingOption: echarts.EChartsOption | null = null

  const resize = () => chart?.resize()

  function init() {
    if (chart || !elRef.value) return
    chart = echarts.init(elRef.value)
    window.addEventListener('resize', resize)
    if (pendingOption) {
      chart.setOption(pendingOption)
      pendingOption = null
    }
  }

  onMounted(init)
  // flush: 'post' 保证 v-if 渲染出的 DOM 已挂到 elRef 后再 init
  watch(elRef, () => init(), { flush: 'post' })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    chart?.dispose()
    chart = null
  })

  function setOption(option: echarts.EChartsOption) {
    if (chart) {
      chart.setOption(option)
    } else {
      pendingOption = option
    }
  }

  return { setOption }
}

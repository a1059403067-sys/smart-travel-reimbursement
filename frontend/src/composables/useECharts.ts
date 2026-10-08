import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, type Ref } from 'vue'

// ECharts 生命周期封装：挂载时 init、卸载时 dispose、窗口缩放自动 resize
export function useECharts(elRef: Ref<HTMLElement | undefined>) {
  let chart: echarts.ECharts | null = null

  const resize = () => chart?.resize()

  onMounted(() => {
    if (elRef.value) {
      chart = echarts.init(elRef.value)
      window.addEventListener('resize', resize)
    }
  })

  onBeforeUnmount(() => {
    window.removeEventListener('resize', resize)
    chart?.dispose()
    chart = null
  })

  function setOption(option: echarts.EChartsOption) {
    chart?.setOption(option)
  }

  return { setOption }
}

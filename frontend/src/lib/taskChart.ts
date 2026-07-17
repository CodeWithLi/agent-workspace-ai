import { PieChart } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([PieChart, TooltipComponent, CanvasRenderer])

export interface TaskChart {
  resize(): void
  dispose(): void
}

export function renderTaskChart(
  element: HTMLDivElement,
  data: Array<{ name: string; value: number }>
): TaskChart {
  const chart = echarts.getInstanceByDom(element) || echarts.init(element)
  chart.setOption({
    color: ['#94a3b8', '#2563eb', '#16a34a', '#dc2626'],
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'pie',
        radius: ['56%', '78%'],
        center: ['50%', '48%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#ffffff', borderWidth: 3 },
        label: { show: false },
        emphasis: { scale: false },
        data
      }
    ]
  })
  return chart
}

import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import type { TraceTrendPoint } from '../api/types'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

export interface TraceTrendChart {
  resize(): void
  dispose(): void
}

export function renderTraceTrendChart(
  element: HTMLDivElement,
  points: TraceTrendPoint[]
): TraceTrendChart {
  const chart = echarts.getInstanceByDom(element) || echarts.init(element)
  chart.setOption({
    animationDuration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 220,
    color: ['#2563eb', '#b91c1c', '#64748b'],
    grid: { left: 8, right: 12, top: 34, bottom: 8, containLabel: true },
    legend: { show: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#111827',
      borderWidth: 0,
      textStyle: { color: '#ffffff', fontSize: 12 }
    },
    xAxis: {
      type: 'category',
      boundaryGap: true,
      data: points.map((point) => point.bucket.slice(5)),
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisTick: { show: false },
      axisLabel: { color: '#6b7280', fontSize: 11, hideOverlap: true }
    },
    yAxis: [
      {
        type: 'value',
        minInterval: 1,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 11 },
        splitLine: { lineStyle: { color: '#eef0f3' } }
      },
      {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: '#6b7280',
          fontSize: 11,
          formatter: (value: number) => (value >= 1000 ? `${Math.round(value / 1000)}k` : String(value))
        },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '完成运行',
        type: 'bar',
        stack: 'runs',
        barMaxWidth: 22,
        data: points.map((point) => point.completed),
        itemStyle: { borderRadius: [2, 2, 0, 0] }
      },
      {
        name: '失败运行',
        type: 'bar',
        stack: 'runs',
        barMaxWidth: 22,
        data: points.map((point) => point.failed)
      },
      {
        name: 'Token',
        type: 'line',
        yAxisIndex: 1,
        smooth: 0.24,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { width: 2 },
        data: points.map((point) => point.total_tokens)
      }
    ]
  })
  return chart
}

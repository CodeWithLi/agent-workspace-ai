import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { PrototypeComponentSpec, PrototypeSpecification } from '../api/types'
import PrototypeCanvas from './PrototypeCanvas.vue'

function component(overrides: Partial<PrototypeComponentSpec> & Pick<PrototypeComponentSpec, 'id' | 'type'>): PrototypeComponentSpec {
  return {
    label: '',
    text: '',
    placeholder: '',
    value: '',
    variant: 'default',
    required: false,
    disabled: false,
    options: [],
    items: [],
    columns: [],
    steps: [],
    active_step: 1,
    ...overrides
  }
}

const specification: PrototypeSpecification = {
  product_name: '测试产品',
  summary: '验证原型交互',
  start_screen_id: 'start',
  theme: {
    primary: '#1F2937',
    accent: '#2563EB',
    background: '#F7F8FA',
    surface: '#FFFFFF',
    foreground: '#111827',
    radius: 'soft'
  },
  screens: [
    {
      id: 'start',
      name: '开始页',
      description: '填写手机号',
      layout: 'auth',
      sections: [{
        id: 'start-form',
        title: '注册',
        description: '',
        width: 'narrow',
        components: [
          component({ id: 'phone', type: 'input', label: '手机号', required: true }),
          component({ id: 'submit', type: 'button', label: '提交', variant: 'primary', action: { type: 'submit' } }),
          component({ id: 'detail-link', type: 'link', label: '查看详情', action: { type: 'navigate', target: 'detail' } })
        ]
      }]
    },
    {
      id: 'detail',
      name: '详情页',
      description: '返回上一界面',
      layout: 'app',
      sections: [{
        id: 'detail-content',
        title: '详情',
        description: '',
        width: 'medium',
        components: [component({ id: 'back', type: 'button', label: '返回', action: { type: 'back' } })]
      }]
    }
  ]
}

function buttonByText(wrapper: ReturnType<typeof mount>, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text() === text)
  if (!button) throw new Error(`Button not found: ${text}`)
  return button
}

describe('PrototypeCanvas', () => {
  it('blocks submit until required fields are complete', async () => {
    const wrapper = mount(PrototypeCanvas, {
      props: { spec: specification, screenId: 'start', deviceMode: 'desktop' }
    })

    await buttonByText(wrapper, '提交').trigger('click')
    expect(wrapper.get('input').attributes('aria-invalid')).toBe('true')
    expect(wrapper.text()).toContain('请先完成必填项')

    await wrapper.get('input').setValue('13800138000')
    await buttonByText(wrapper, '提交').trigger('click')
    expect(wrapper.get('input').attributes('aria-invalid')).toBeUndefined()
    const interactions = wrapper.emitted('interaction') || []
    expect(interactions[interactions.length - 1]).toEqual(['提交成功'])
  })

  it('emits safe in-prototype navigation and back events', async () => {
    const wrapper = mount(PrototypeCanvas, {
      props: { spec: specification, screenId: 'start', deviceMode: 'desktop' }
    })

    await buttonByText(wrapper, '查看详情').trigger('click')
    expect(wrapper.emitted('navigate')).toEqual([['detail']])

    await wrapper.setProps({ screenId: 'detail' })
    await buttonByText(wrapper, '返回').trigger('click')
    expect(wrapper.emitted('back')).toEqual([[]])
  })
})

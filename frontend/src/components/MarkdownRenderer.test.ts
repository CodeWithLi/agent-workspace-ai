import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MarkdownRenderer from './MarkdownRenderer.vue'

describe('MarkdownRenderer', () => {
  it('renders supported code highlighting and blocks raw HTML', () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '# 标题\n\n```json\n{"ok": true}\n```\n<script>window.evil = true</script>' }
    })

    expect(wrapper.find('h1').text()).toBe('标题')
    expect(wrapper.find('code.hljs').exists()).toBe(true)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.html()).toContain('&lt;script&gt;')
  })
})

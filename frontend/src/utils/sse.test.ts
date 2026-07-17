import { describe, expect, it } from 'vitest'
import { parseSseChunk } from './sse'

describe('parseSseChunk', () => {
  it('keeps incomplete events between network chunks', () => {
    const first = parseSseChunk('', 'event: speaker_start\ndata: {"agent_name":"AI产品')
    expect(first.events).toEqual([])

    const second = parseSseChunk(first.buffer, '经理"}\n\nevent: token\ndata: {"content":"方案"}\n\n')
    expect(second.buffer).toBe('')
    expect(second.events).toEqual([
      { type: 'speaker_start', data: { agent_name: 'AI产品经理' } },
      { type: 'token', data: { content: '方案' } }
    ])
  })

  it('ignores comments and malformed events', () => {
    const result = parseSseChunk('', ': heartbeat\n\nevent: token\ndata: invalid\n\n')
    expect(result.events).toEqual([])
  })
})

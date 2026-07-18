import { describe, expect, it } from 'vitest'
import { flushSseBuffer, parseSseChunk } from './sse'

describe('parseSseChunk', () => {
  it('keeps incomplete events between arbitrary network chunks', () => {
    const first = parseSseChunk('', 'event: speaker_start\ndata: {"agent_name":"product')
    expect(first.events).toEqual([])

    const second = parseSseChunk(first.buffer, ' manager"}\n\nevent: token\ndata: {"content":"plan"}\n\n')
    expect(second.buffer).toBe('')
    expect(second.events).toEqual([
      { type: 'speaker_start', data: { agent_name: 'product manager' } },
      { type: 'token', data: { content: 'plan' } }
    ])
  })

  it('parses CRLF, ids, retry directives, and multiline JSON data', () => {
    const result = parseSseChunk('', [
      'id: 42',
      'retry: 1500',
      'event: job_updated',
      'data: {',
      'data:   "status": "RUNNING",',
      'data:   "progress_percent": 40',
      'data: }',
      '',
      ''
    ].join('\r\n'))

    expect(result).toEqual({
      events: [{
        type: 'job_updated',
        id: '42',
        retry: 1500,
        data: { status: 'RUNNING', progress_percent: 40 }
      }],
      buffer: '',
      lastEventId: '42',
      retry: 1500
    })
  })

  it('ignores comments and supports the default message event', () => {
    const result = parseSseChunk('', ': heartbeat\n\ndata: {"ready":true}\n\n')
    expect(result.events).toEqual([{ type: 'message', data: { ready: true } }])
  })

  it('does not emit malformed JSON or advance its event cursor', () => {
    const result = parseSseChunk('', 'id: 9\nevent: job_updated\ndata: invalid\n\n')
    expect(result.events).toEqual([])
    expect(result.lastEventId).toBeUndefined()
    expect(result.buffer).toBe('')
  })

  it('retains an incomplete CRLF boundary across chunks', () => {
    const first = parseSseChunk('', 'event: token\r\ndata: {"content":"ok"}\r\n\r')
    expect(first.events).toEqual([])

    const second = parseSseChunk(first.buffer, '\n')
    expect(second.events).toEqual([{ type: 'token', data: { content: 'ok' } }])
    expect(second.buffer).toBe('')
  })

  it('flushes a final event when the stream ends without a blank line', () => {
    const pending = parseSseChunk('', 'id: 12\nevent: done\ndata: {"ok":true}')
    expect(pending.events).toEqual([])

    const flushed = flushSseBuffer(pending.buffer)
    expect(flushed.events).toEqual([{ type: 'done', id: '12', data: { ok: true } }])
    expect(flushed.lastEventId).toBe('12')
    expect(flushed.buffer).toBe('')
  })

  it('accepts retry-only control blocks without producing an event', () => {
    const result = parseSseChunk('', 'retry: 2500\n\n')
    expect(result.events).toEqual([])
    expect(result.retry).toBe(2500)
  })
})

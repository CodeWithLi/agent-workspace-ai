import { describe, expect, it, vi } from 'vitest'
import type { WorkflowEvent } from '../api/types'
import {
  useWorkflowEventStream,
  type WorkflowConnectionState
} from './useWorkflowEventStream'

function workflowEvent(id: number, eventType = 'NODE_COMPLETED'): WorkflowEvent {
  return {
    id,
    workflow_id: 88,
    node: eventType === 'COMPLETED' ? 'completed' : 'product',
    event_type: eventType,
    message: `event ${id}`,
    payload: {},
    created_at: '2026-07-18T00:00:00Z'
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    body: null,
    json: async () => body
  } as Response
}

function streamResponse(chunks: string[]): Response {
  const encoded = chunks.map((chunk) => new TextEncoder().encode(chunk))
  let index = 0
  return {
    ok: true,
    status: 200,
    json: async () => ({}),
    body: {
      getReader: () => ({
        read: async () => index < encoded.length
          ? { done: false, value: encoded[index++] }
          : { done: true, value: undefined },
        cancel: async () => undefined
      })
    }
  } as unknown as Response
}

function sseEvent(event: WorkflowEvent): string {
  return `id: ${event.id}\nevent: workflow\ndata: ${JSON.stringify(event)}\n\n`
}

describe('useWorkflowEventStream', () => {
  it('resumes from Last-Event-ID and ignores duplicate or out-of-order events', async () => {
    const observed: number[] = []
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return streamResponse([
        sseEvent(workflowEvent(3)),
        sseEvent(workflowEvent(5)),
        sseEvent(workflowEvent(5)),
        sseEvent(workflowEvent(6, 'COMPLETED'))
      ])
    })
    const stream = useWorkflowEventStream({
      fetcher,
      getAccessToken: () => 'access-token',
      onEvent: (event) => {
        observed.push(event.id)
        return event.event_type !== 'COMPLETED'
      }
    })

    stream.start({ eventsUrl: '/workflow/88/events', lastEventId: 4 })
    await vi.waitFor(() => expect(stream.connectionState.value).toBe('closed'))

    expect(observed).toEqual([5, 6])
    expect(stream.lastEventId.value).toBe(6)
    expect(fetcher).toHaveBeenCalledOnce()
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers)
    expect(headers.get('Last-Event-ID')).toBe('4')
    expect(headers.get('Authorization')).toBe('Bearer access-token')
  })

  it('refreshes an expired access token before consuming events', async () => {
    let token = 'expired-token'
    const refreshToken = vi.fn(async () => {
      token = 'fresh-token'
      return token
    })
    const responses = [
      jsonResponse({}, 401),
      streamResponse([sseEvent(workflowEvent(2, 'COMPLETED'))])
    ]
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return responses.shift() as Response
    })
    const stream = useWorkflowEventStream({
      fetcher,
      refreshToken,
      getAccessToken: () => token,
      onEvent: () => false
    })

    stream.start({ eventsUrl: '/workflow/88/events', lastEventId: 1 })
    await vi.waitFor(() => expect(stream.connectionState.value).toBe('closed'))

    expect(refreshToken).toHaveBeenCalledOnce()
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(new Headers(fetcher.mock.calls[1][1]?.headers).get('Authorization')).toBe('Bearer fresh-token')
  })

  it('reconnects with exponential backoff and preserves the cursor', async () => {
    const reconnects: number[] = []
    const states: WorkflowConnectionState[] = []
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return streamResponse([])
    })
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(streamResponse([]))
      .mockResolvedValueOnce(streamResponse([sseEvent(workflowEvent(2, 'COMPLETED'))]))
    const stream = useWorkflowEventStream({
      fetcher,
      getAccessToken: () => null,
      baseReconnectDelayMs: 5,
      maxReconnectDelayMs: 20,
      onEvent: () => false,
      onConnectionState: (state, detail) => {
        states.push(state)
        if (state === 'reconnecting') reconnects.push(detail.retryInMs)
      }
    })

    stream.start({ eventsUrl: '/workflow/88/events', lastEventId: 1 })
    await vi.waitFor(() => expect(stream.connectionState.value).toBe('closed'))

    expect(reconnects).toEqual([5, 10])
    expect(states).toContain('connected')
    expect(fetcher).toHaveBeenCalledTimes(3)
    expect(new Headers(fetcher.mock.calls[2][1]?.headers).get('Last-Event-ID')).toBe('1')
  })

  it('replays an event when the consumer fails before acknowledging it', async () => {
    let attempts = 0
    const event = workflowEvent(2, 'COMPLETED')
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      void _input
      void _init
      return streamResponse([sseEvent(event)])
    })
    const stream = useWorkflowEventStream({
      fetcher,
      getAccessToken: () => null,
      baseReconnectDelayMs: 1,
      maxReconnectDelayMs: 1,
      onEvent: () => {
        attempts += 1
        if (attempts === 1) throw new Error('snapshot refresh failed')
        return false
      }
    })

    stream.start({ eventsUrl: '/workflow/88/events', lastEventId: 1 })
    await vi.waitFor(() => expect(stream.connectionState.value).toBe('closed'))

    expect(attempts).toBe(2)
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(stream.lastEventId.value).toBe(2)
  })

  it('aborts an active request when disposed', async () => {
    const signals: AbortSignal[] = []
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal)
      return new Promise<Response>(() => undefined)
    })
    const stream = useWorkflowEventStream({
      fetcher,
      getAccessToken: () => null,
      onEvent: () => undefined
    })

    stream.start({ eventsUrl: '/workflow/88/events' })
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
    stream.dispose()

    expect(signals[0]?.aborted).toBe(true)
    expect(stream.connectionState.value).toBe('disposed')
  })
})

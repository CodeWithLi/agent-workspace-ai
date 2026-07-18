import { describe, expect, it, vi } from 'vitest'
import type { PrototypeGenerationJob, PrototypeGenerationJobStatus } from '../api/types'
import {
  usePrototypeGenerationStream,
  type PrototypeGenerationConnectionState
} from './usePrototypeGenerationStream'

function generationJob(
  status: PrototypeGenerationJobStatus,
  latestEventId: number,
  values: Partial<PrototypeGenerationJob> = {}
): PrototypeGenerationJob {
  return {
    job_id: 21,
    operation: 'CREATE',
    project_id: 3,
    title: 'Growth prototype',
    prototype_id: null,
    status,
    stage: status === 'SUCCEEDED' ? 'completed' : 'architecture',
    stage_history: [],
    progress_percent: status === 'SUCCEEDED' ? 100 : 40,
    attempt_count: 1,
    max_attempts: 3,
    latest_event_id: latestEventId,
    retryable: status === 'FAILED',
    error_code: null,
    error_message: null,
    result_prototype_id: status === 'SUCCEEDED' ? 41 : null,
    result_version: status === 'SUCCEEDED' ? 1 : null,
    created_at: '2026-07-18T00:00:00Z',
    updated_at: '2026-07-18T00:00:00Z',
    ...values
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

function sseEvent(id: number, job: PrototypeGenerationJob, event = 'job_updated'): string {
  return `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(job)}\n\n`
}

describe('usePrototypeGenerationStream', () => {
  it('loads a snapshot, resumes with Last-Event-ID, and ignores duplicate or out-of-order events', async () => {
    const running = generationJob('RUNNING', 4)
    const progressed = generationJob('RUNNING', 5, { progress_percent: 70, stage: 'quality_review' })
    const completed = generationJob('SUCCEEDED', 6)
    const responses = [
      jsonResponse(running),
      streamResponse([
        sseEvent(3, generationJob('RUNNING', 3)),
        sseEvent(5, progressed),
        sseEvent(5, progressed),
        sseEvent(6, completed, 'job_completed')
      ])
    ]
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input
      void init
      return responses.shift() as Response
    })
    const observed: PrototypeGenerationJob[] = []
    const stream = usePrototypeGenerationStream({
      fetcher,
      getAccessToken: () => 'access-token',
      onJob: (job) => observed.push(job)
    })

    await stream.start({ snapshotUrl: '/jobs/21', eventsUrl: '/jobs/21/events' })
    await vi.waitFor(() => expect(stream.job.value?.status).toBe('SUCCEEDED'))

    expect(observed.map((job) => job.latest_event_id)).toEqual([4, 5, 6])
    expect(stream.lastEventId.value).toBe(6)
    expect(stream.connectionState.value).toBe('closed')
    expect(fetcher).toHaveBeenCalledTimes(2)
    const snapshotInit = fetcher.mock.calls[0][1]
    const eventInit = fetcher.mock.calls[1][1]
    expect(snapshotInit?.credentials).toBe('include')
    expect(eventInit?.credentials).toBe('include')
    expect(new Headers(eventInit?.headers).get('Last-Event-ID')).toBe('4')
    expect(new Headers(eventInit?.headers).get('Authorization')).toBe('Bearer access-token')
  })

  it('refreshes authentication for both snapshot and event requests', async () => {
    let token = 'expired-token'
    let refreshCount = 0
    const refreshToken = vi.fn(async () => {
      refreshCount += 1
      token = `fresh-token-${refreshCount}`
      return token
    })
    const responses = [
      jsonResponse({}, 401),
      jsonResponse(generationJob('RUNNING', 1)),
      jsonResponse({}, 401),
      streamResponse([sseEvent(2, generationJob('SUCCEEDED', 2), 'job_completed')])
    ]
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      void input
      void init
      return responses.shift() as Response
    })
    const stream = usePrototypeGenerationStream({ fetcher, refreshToken, getAccessToken: () => token })

    await stream.start({ snapshotUrl: '/jobs/21', eventsUrl: '/jobs/21/events' })
    await vi.waitFor(() => expect(stream.job.value?.status).toBe('SUCCEEDED'))

    expect(refreshToken).toHaveBeenCalledTimes(2)
    expect(fetcher).toHaveBeenCalledTimes(4)
    expect(new Headers(fetcher.mock.calls[1][1]?.headers).get('Authorization')).toBe('Bearer fresh-token-1')
    expect(new Headers(fetcher.mock.calls[3][1]?.headers).get('Authorization')).toBe('Bearer fresh-token-2')
  })

  it('reconnects an active stream with exponential backoff and stops at a terminal event', async () => {
    const reconnects: number[] = []
    const states: PrototypeGenerationConnectionState[] = []
    const fetcher = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input
      void init
      return Promise.resolve(streamResponse([]))
    })
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(streamResponse([]))
      .mockResolvedValueOnce(streamResponse([
        sseEvent(2, generationJob('SUCCEEDED', 2), 'job_completed')
      ]))
    const stream = usePrototypeGenerationStream({
      fetcher,
      getAccessToken: () => null,
      baseReconnectDelayMs: 5,
      maxReconnectDelayMs: 20,
      onConnectionState: (state, detail) => {
        states.push(state)
        if (state === 'reconnecting') reconnects.push(detail.retryInMs)
      }
    })

    await stream.start({
      snapshotUrl: '/jobs/21',
      eventsUrl: '/jobs/21/events',
      initialSnapshot: generationJob('RUNNING', 1)
    })
    await vi.waitFor(() => expect(stream.job.value?.status).toBe('SUCCEEDED'))

    expect(reconnects).toEqual([5, 10])
    expect(states).toContain('connected')
    expect(states[states.length - 1]).toBe('closed')
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('aborts an active request on dispose', async () => {
    const signals: AbortSignal[] = []
    const fetcher = vi.fn((_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal) signals.push(init.signal)
      return new Promise<Response>(() => undefined)
    })
    const stream = usePrototypeGenerationStream({ fetcher, getAccessToken: () => null })

    await stream.start({
      snapshotUrl: '/jobs/21',
      eventsUrl: '/jobs/21/events',
      initialSnapshot: generationJob('RUNNING', 1)
    })
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledOnce())
    stream.dispose()

    expect(signals[0]?.aborted).toBe(true)
    expect(stream.connectionState.value).toBe('disposed')
  })

  it('clears the completed job and resume cursor for page dismissal', async () => {
    const stream = usePrototypeGenerationStream()
    await stream.start({
      snapshotUrl: '/jobs/21',
      eventsUrl: '/jobs/21/events',
      initialSnapshot: generationJob('SUCCEEDED', 8)
    })
    expect(stream.lastEventId.value).toBe(8)

    stream.clear()

    expect(stream.job.value).toBeNull()
    expect(stream.lastEventId.value).toBe(0)
    expect(stream.connectionState.value).toBe('idle')
  })
})

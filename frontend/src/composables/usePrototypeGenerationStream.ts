import { getCurrentScope, onScopeDispose, readonly, ref, shallowRef } from 'vue'
import { refreshAccessToken } from '../api/client'
import type { PrototypeGenerationJob, PrototypeGenerationJobStatus } from '../api/types'
import { flushSseBuffer, parseSseChunk, type SseEvent } from '../utils/sse'

export type PrototypeGenerationConnectionState =
  | 'idle'
  | 'loading_snapshot'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'closed'
  | 'disposed'

export interface PrototypeGenerationConnectionDetail {
  attempt: number
  retryInMs: number
}

export interface PrototypeGenerationStreamOptions {
  onJob?: (job: PrototypeGenerationJob) => void
  onConnectionState?: (
    state: PrototypeGenerationConnectionState,
    detail: PrototypeGenerationConnectionDetail
  ) => void
  onError?: (error: Error) => void
  fetcher?: typeof fetch
  refreshToken?: () => Promise<string>
  getAccessToken?: () => string | null
  baseReconnectDelayMs?: number
  maxReconnectDelayMs?: number
}

export interface StartPrototypeGenerationStreamInput {
  snapshotUrl: string
  eventsUrl: string
  initialSnapshot?: PrototypeGenerationJob
}

const terminalStatuses = new Set<PrototypeGenerationJobStatus>([
  'SUCCEEDED',
  'FAILED',
  'CANCELLED'
])

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && 'name' in error && error.name === 'AbortError')
}

function asError(error: unknown, fallback: string): Error {
  return error instanceof Error ? error : new Error(fallback)
}

function isGenerationJob(value: unknown): value is PrototypeGenerationJob {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Partial<PrototypeGenerationJob>
  return Number.isInteger(candidate.job_id)
    && typeof candidate.status === 'string'
    && typeof candidate.latest_event_id === 'number'
}

function jobFromEvent(event: SseEvent): PrototypeGenerationJob | null {
  const candidate = event.data.job ?? event.data
  return isGenerationJob(candidate) ? candidate : null
}

async function responseError(response: Response, fallback: string): Promise<Error> {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = payload?.detail
  return new Error(typeof detail === 'string' ? detail : `${fallback} (${response.status})`)
}

export function usePrototypeGenerationStream(options: PrototypeGenerationStreamOptions = {}) {
  const job = shallowRef<PrototypeGenerationJob | null>(null)
  const connectionState = ref<PrototypeGenerationConnectionState>('idle')
  const lastEventId = ref(0)
  const reconnectDelayMs = ref(0)
  const error = shallowRef<Error | null>(null)

  const fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
  const refreshToken = options.refreshToken ?? refreshAccessToken
  const getAccessToken = options.getAccessToken ?? (() => localStorage.getItem('token'))
  const baseReconnectDelay = Math.max(1, options.baseReconnectDelayMs ?? 500)
  const maxReconnectDelay = Math.max(baseReconnectDelay, options.maxReconnectDelayMs ?? 15_000)

  let activeController: AbortController | null = null
  let session = 0
  let disposed = false
  let serverRetryMs: number | null = null

  function notifyJob(value: PrototypeGenerationJob) {
    try {
      options.onJob?.(value)
    } catch {
      // Consumer callbacks must not terminate the transport loop.
    }
  }

  function setConnectionState(
    state: PrototypeGenerationConnectionState,
    attempt = 0,
    retryInMs = 0
  ) {
    connectionState.value = state
    reconnectDelayMs.value = retryInMs
    try {
      options.onConnectionState?.(state, { attempt, retryInMs })
    } catch {
      // Consumer callbacks must not terminate the transport loop.
    }
  }

  function reportError(value: unknown, fallback: string): Error {
    const nextError = asError(value, fallback)
    error.value = nextError
    try {
      options.onError?.(nextError)
    } catch {
      // Consumer callbacks must not terminate the transport loop.
    }
    return nextError
  }

  function haltTransport() {
    session += 1
    activeController?.abort()
    activeController = null
  }

  function stop() {
    if (disposed) return
    haltTransport()
    setConnectionState('closed')
  }

  function clear() {
    if (disposed) return
    haltTransport()
    job.value = null
    lastEventId.value = 0
    reconnectDelayMs.value = 0
    error.value = null
    serverRetryMs = null
    setConnectionState('idle')
  }

  function dispose() {
    if (disposed) return
    haltTransport()
    disposed = true
    setConnectionState('disposed')
  }

  function authHeaders(init?: HeadersInit): Headers {
    const headers = new Headers(init)
    const token = getAccessToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    return headers
  }

  async function authenticatedFetch(url: string, init: RequestInit): Promise<Response> {
    const request = () => fetcher(url, {
      ...init,
      credentials: 'include',
      headers: authHeaders(init.headers)
    })
    let response = await request()
    if (response.status === 401) {
      await refreshToken()
      response = await request()
    }
    return response
  }

  function applyJob(nextJob: PrototypeGenerationJob, cursor: number, force = false): boolean {
    if (!force) {
      if (job.value && nextJob.job_id !== job.value.job_id) return false
      if (!Number.isInteger(cursor) || cursor <= lastEventId.value) return false
    }
    job.value = nextJob
    lastEventId.value = Math.max(lastEventId.value, cursor, nextJob.latest_event_id)
    notifyJob(nextJob)
    return true
  }

  function applyEvent(event: SseEvent): boolean {
    const nextJob = jobFromEvent(event)
    if (!nextJob) return false
    const eventCursor = event.id === undefined ? nextJob.latest_event_id : Number(event.id)
    return applyJob(nextJob, eventCursor)
  }

  function processParsedEvents(parsed: ReturnType<typeof parseSseChunk>): boolean {
    if (parsed.retry !== undefined && Number.isFinite(parsed.retry)) {
      serverRetryMs = Math.min(maxReconnectDelay, Math.max(1, parsed.retry))
    }
    let applied = false
    for (const event of parsed.events) applied = applyEvent(event) || applied
    return applied
  }

  async function waitForReconnect(delay: number, signal: AbortSignal): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, delay)
      signal.addEventListener('abort', () => {
        window.clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      }, { once: true })
    })
  }

  async function consumeEventStream(eventsUrl: string, currentSession: number) {
    let reconnectAttempt = 0
    while (!disposed && currentSession === session && !terminalStatuses.has(job.value?.status as PrototypeGenerationJobStatus)) {
      const controller = new AbortController()
      activeController = controller
      try {
        setConnectionState('connecting', reconnectAttempt)
        const headers = new Headers({ Accept: 'text/event-stream' })
        if (lastEventId.value > 0) headers.set('Last-Event-ID', String(lastEventId.value))
        const response = await authenticatedFetch(eventsUrl, { headers, signal: controller.signal })
        if (!response.ok || !response.body) throw await responseError(response, '原型生成进度连接失败')
        if (currentSession !== session || disposed) return

        setConnectionState('connected')
        error.value = null
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let receivedEvent = false
        while (currentSession === session && !disposed) {
          const { done, value } = await reader.read()
          if (done) break
          const parsed = parseSseChunk(buffer, decoder.decode(value, { stream: true }))
          buffer = parsed.buffer
          if (processParsedEvents(parsed)) {
            receivedEvent = true
            reconnectAttempt = 0
          }
          if (job.value && terminalStatuses.has(job.value.status)) {
            await reader.cancel()
            setConnectionState('closed')
            return
          }
        }

        const final = flushSseBuffer(`${buffer}${decoder.decode()}`)
        if (processParsedEvents(final)) {
          receivedEvent = true
          reconnectAttempt = 0
        }
        if (job.value && terminalStatuses.has(job.value.status)) {
          setConnectionState('closed')
          return
        }
        if (receivedEvent) reconnectAttempt = 0
        throw new Error('原型生成进度连接已中断')
      } catch (streamError) {
        if (isAbortError(streamError) || currentSession !== session || disposed) return
        reportError(streamError, '原型生成进度连接失败')
        reconnectAttempt += 1
        const reconnectBase = serverRetryMs ?? baseReconnectDelay
        const delay = Math.min(maxReconnectDelay, reconnectBase * (2 ** (reconnectAttempt - 1)))
        setConnectionState('reconnecting', reconnectAttempt, delay)
        try {
          await waitForReconnect(delay, controller.signal)
        } catch (waitError) {
          if (isAbortError(waitError)) return
          throw waitError
        }
      }
    }
    if (!disposed && currentSession === session) setConnectionState('closed')
  }

  async function start(input: StartPrototypeGenerationStreamInput): Promise<PrototypeGenerationJob> {
    if (disposed) throw new Error('Prototype generation stream has been disposed')
    haltTransport()
    const currentSession = session
    job.value = null
    lastEventId.value = 0
    reconnectDelayMs.value = 0
    error.value = null
    serverRetryMs = null

    let snapshot = input.initialSnapshot
    try {
      if (!snapshot) {
        setConnectionState('loading_snapshot')
        const controller = new AbortController()
        activeController = controller
        const response = await authenticatedFetch(input.snapshotUrl, {
          headers: { Accept: 'application/json' },
          signal: controller.signal
        })
        if (!response.ok) throw await responseError(response, '原型生成任务加载失败')
        const payload: unknown = await response.json()
        if (!isGenerationJob(payload)) throw new Error('原型生成任务响应格式无效')
        snapshot = payload
      }
      if (currentSession !== session || disposed) throw new DOMException('Aborted', 'AbortError')
      applyJob(snapshot, snapshot.latest_event_id, true)
      activeController = null
      if (terminalStatuses.has(snapshot.status)) {
        setConnectionState('closed')
      } else {
        void consumeEventStream(input.eventsUrl, currentSession)
      }
      return snapshot
    } catch (startError) {
      if (currentSession === session && !disposed && !isAbortError(startError)) {
        reportError(startError, '原型生成任务加载失败')
        setConnectionState('closed')
      }
      throw startError
    }
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return {
    job: readonly(job),
    connectionState: readonly(connectionState),
    lastEventId: readonly(lastEventId),
    reconnectDelayMs: readonly(reconnectDelayMs),
    error: readonly(error),
    start,
    stop,
    clear,
    dispose
  }
}

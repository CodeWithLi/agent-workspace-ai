import { getCurrentScope, onScopeDispose, readonly, ref, shallowRef } from 'vue'
import { refreshAccessToken } from '../api/client'
import type { WorkflowEvent } from '../api/types'
import { flushSseBuffer, parseSseChunk, type SseEvent } from '../utils/sse'

export type WorkflowConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'closed'
  | 'disposed'

export interface WorkflowConnectionDetail {
  attempt: number
  retryInMs: number
}

export interface WorkflowEventStreamOptions {
  onEvent: (event: WorkflowEvent) => boolean | void | Promise<boolean | void>
  onConnectionState?: (state: WorkflowConnectionState, detail: WorkflowConnectionDetail) => void
  onError?: (error: Error) => void
  fetcher?: typeof fetch
  refreshToken?: () => Promise<string>
  getAccessToken?: () => string | null
  baseReconnectDelayMs?: number
  maxReconnectDelayMs?: number
}

export interface StartWorkflowEventStreamInput {
  eventsUrl: string
  lastEventId?: number
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && 'name' in error && error.name === 'AbortError')
}

function asError(error: unknown, fallback: string): Error {
  return error instanceof Error ? error : new Error(fallback)
}

function workflowEventFromSse(event: SseEvent): WorkflowEvent | null {
  const candidate = event.data
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return null
  const value = candidate as Partial<WorkflowEvent>
  if (
    !Number.isInteger(value.id)
    || !Number.isInteger(value.workflow_id)
    || typeof value.node !== 'string'
    || typeof value.event_type !== 'string'
    || typeof value.message !== 'string'
    || typeof value.created_at !== 'string'
    || !value.payload
    || typeof value.payload !== 'object'
    || Array.isArray(value.payload)
  ) return null
  return value as WorkflowEvent
}

async function responseError(response: Response): Promise<Error> {
  const payload = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = payload?.detail
  return new Error(typeof detail === 'string' ? detail : `工作流进度连接失败 (${response.status})`)
}

export function useWorkflowEventStream(options: WorkflowEventStreamOptions) {
  const connectionState = ref<WorkflowConnectionState>('idle')
  const lastEventId = ref(0)
  const reconnectDelayMs = ref(0)
  const error = shallowRef<Error | null>(null)

  const fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
  const refreshToken = options.refreshToken ?? refreshAccessToken
  const getAccessToken = options.getAccessToken ?? (() => localStorage.getItem('token'))
  const baseReconnectDelay = Math.max(1, options.baseReconnectDelayMs ?? 500)
  const maxReconnectDelay = Math.max(baseReconnectDelay, options.maxReconnectDelayMs ?? 15_000)

  let activeController: AbortController | null = null
  let activeEventsUrl = ''
  let session = 0
  let disposed = false
  let serverRetryMs: number | null = null

  function setConnectionState(
    state: WorkflowConnectionState,
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

  function reportError(value: unknown): Error {
    const nextError = asError(value, '工作流进度连接失败')
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
    activeEventsUrl = ''
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

  async function waitForReconnect(delay: number, signal: AbortSignal): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, delay)
      signal.addEventListener('abort', () => {
        window.clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      }, { once: true })
    })
  }

  async function processParsedEvents(parsed: ReturnType<typeof parseSseChunk>): Promise<{
    received: boolean
    stop: boolean
  }> {
    if (parsed.retry !== undefined && Number.isFinite(parsed.retry)) {
      serverRetryMs = Math.min(maxReconnectDelay, Math.max(1, parsed.retry))
    }
    let received = false
    for (const parsedEvent of parsed.events) {
      const workflowEvent = workflowEventFromSse(parsedEvent)
      if (!workflowEvent) continue
      const cursor = Number(parsedEvent.id ?? workflowEvent.id)
      if (!Number.isInteger(cursor) || cursor <= lastEventId.value) continue
      const keepOpen = await options.onEvent(workflowEvent)
      lastEventId.value = cursor
      received = true
      if (keepOpen === false) return { received, stop: true }
    }
    return { received, stop: false }
  }

  async function consumeEventStream(eventsUrl: string, currentSession: number) {
    let reconnectAttempt = 0
    while (!disposed && currentSession === session) {
      const controller = new AbortController()
      activeController = controller
      try {
        setConnectionState('connecting', reconnectAttempt)
        const headers = new Headers({ Accept: 'text/event-stream' })
        if (lastEventId.value > 0) headers.set('Last-Event-ID', String(lastEventId.value))
        const response = await authenticatedFetch(eventsUrl, { headers, signal: controller.signal })
        if (!response.ok || !response.body) throw await responseError(response)
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
          const processed = await processParsedEvents(parsed)
          if (processed.received) {
            receivedEvent = true
            reconnectAttempt = 0
          }
          if (processed.stop) {
            await reader.cancel()
            setConnectionState('closed')
            return
          }
        }

        const final = await processParsedEvents(flushSseBuffer(`${buffer}${decoder.decode()}`))
        if (final.stop) {
          setConnectionState('closed')
          return
        }
        if (final.received || receivedEvent) reconnectAttempt = 0
        throw new Error('工作流进度连接已中断')
      } catch (streamError) {
        if (isAbortError(streamError) || currentSession !== session || disposed) return
        reportError(streamError)
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

  function start(input: StartWorkflowEventStreamInput) {
    if (disposed) throw new Error('Workflow event stream has been disposed')
    haltTransport()
    const currentSession = session
    activeEventsUrl = input.eventsUrl
    lastEventId.value = Math.max(0, input.lastEventId ?? 0)
    reconnectDelayMs.value = 0
    error.value = null
    serverRetryMs = null
    void consumeEventStream(activeEventsUrl, currentSession)
  }

  function restart() {
    if (!activeEventsUrl) return
    start({ eventsUrl: activeEventsUrl, lastEventId: lastEventId.value })
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return {
    connectionState: readonly(connectionState),
    lastEventId: readonly(lastEventId),
    reconnectDelayMs: readonly(reconnectDelayMs),
    error: readonly(error),
    start,
    restart,
    stop,
    clear,
    dispose
  }
}

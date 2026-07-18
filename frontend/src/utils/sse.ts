export interface SseEvent<T extends Record<string, any> = Record<string, any>> {
  type: string
  data: T
  id?: string
  retry?: number
}

export interface ParseSseOptions {
  flush?: boolean
}

export interface ParseSseResult {
  events: SseEvent[]
  buffer: string
  lastEventId?: string
  retry?: number
}

// A blank SSE line may use CRLF, LF, or CR independently.
const eventBoundary = /\r\n\r\n|\r\n\r|\r\n\n|\r\r\n|\n\r\n|\r\r|\n\n/

function parseEventBlock(block: string): {
  event?: SseEvent
  retry?: number
} {
  let type = 'message'
  let id: string | undefined
  let retry: number | undefined
  const dataLines: string[] = []

  const lines = block.replace(/^\uFEFF/, '').split(/\r\n|\r|\n/)
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    let value = separator === -1 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') type = value || 'message'
    else if (field === 'data') dataLines.push(value)
    else if (field === 'id' && !value.includes('\0')) id = value
    else if (field === 'retry' && /^\d+$/.test(value)) retry = Number(value)
  }

  if (!dataLines.length) return { retry }
  try {
    const event: SseEvent = {
      type,
      data: JSON.parse(dataLines.join('\n'))
    }
    if (id !== undefined) event.id = id
    if (retry !== undefined) event.retry = retry
    return { event, retry }
  } catch {
    // A malformed payload is not an event. In particular, its id must not
    // become a resume cursor because the server needs to replay it.
    return { retry }
  }
}

export function parseSseChunk(
  buffer: string,
  chunk: string,
  options: ParseSseOptions = {}
): ParseSseResult {
  let input = `${buffer}${chunk}`
  let deferredCarriageReturn = ''
  if (!options.flush && input.endsWith('\r')) {
    input = input.slice(0, -1)
    deferredCarriageReturn = '\r'
  }
  const blocks = input.split(eventBoundary)
  let remainder = `${blocks.pop() || ''}${deferredCarriageReturn}`
  if (options.flush && remainder) {
    blocks.push(remainder)
    remainder = ''
  }

  const result: ParseSseResult = { events: [], buffer: remainder }
  for (const block of blocks) {
    if (!block) continue
    const parsed = parseEventBlock(block)
    if (parsed.retry !== undefined) result.retry = parsed.retry
    if (!parsed.event) continue
    result.events.push(parsed.event)
    if (parsed.event.id !== undefined) result.lastEventId = parsed.event.id
  }
  return result
}

export function flushSseBuffer(buffer: string): ParseSseResult {
  return parseSseChunk(buffer, '', { flush: true })
}

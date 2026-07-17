export interface SseEvent {
  type: string
  data: Record<string, any>
}

export function parseSseChunk(buffer: string, chunk: string): { events: SseEvent[]; buffer: string } {
  const blocks = `${buffer}${chunk}`.split(/\r?\n\r?\n/)
  const remainder = blocks.pop() || ''
  const events: SseEvent[] = []
  for (const block of blocks) {
    if (!block || block.startsWith(':')) continue
    const type = block.match(/^event:\s*(.+)$/m)?.[1]?.trim()
    const dataLines = block.split(/\r?\n/)
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
    if (!type || !dataLines.length) continue
    try {
      events.push({ type, data: JSON.parse(dataLines.join('\n')) })
    } catch {
      continue
    }
  }
  return { events, buffer: remainder }
}

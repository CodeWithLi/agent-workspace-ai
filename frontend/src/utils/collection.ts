export function containsQuery(query: string, ...values: unknown[]): boolean {
  const normalized = query.trim().toLocaleLowerCase()
  if (!normalized) return true
  return values.some((value) => String(value ?? '').toLocaleLowerCase().includes(normalized))
}

export function paginate<T>(items: T[], page: number, pageSize: number): T[] {
  const safePage = Math.max(1, Math.trunc(page) || 1)
  const safePageSize = Math.max(1, Math.trunc(pageSize) || 1)
  const start = (safePage - 1) * safePageSize
  return items.slice(start, start + safePageSize)
}

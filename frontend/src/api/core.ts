// API infrastructure: error handling, query builder, dedup, and the base fetch wrapper.

export const BASE = ''
export const DEFAULT_TIMEOUT = 30_000

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export function buildQuery(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      sp.set(key, String(val))
    }
  }
  return sp.toString()
}

const inFlightRequests = new Map<string, Promise<unknown>>()

export function dedup<T>(key: string, factory: () => Promise<T>): Promise<T> {
  const existing = inFlightRequests.get(key)
  if (existing) return existing as Promise<T>
  const promise = factory().finally(() => inFlightRequests.delete(key))
  inFlightRequests.set(key, promise)
  return promise
}

export async function apiFetch<T>(url: string, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT)

  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true })
  }

  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) {
      let message = `Request failed: ${res.statusText}`
      try {
        const data = await res.json()
        if (data.detail) message = data.detail
      } catch { /* ignore non-JSON error body */ }
      throw new ApiError(res.status, message)
    }
    return res.json()
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') {
      throw e
    }
    if (e instanceof ApiError) throw e
    throw new ApiError(0, e instanceof Error ? e.message : 'Network error')
  } finally {
    clearTimeout(timeoutId)
  }
}

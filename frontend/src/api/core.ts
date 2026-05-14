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

/**
 * Build a fully-qualified URL for a GET endpoint that the browser opens
 * directly (e.g. file downloads). Unlike `buildQuery`, every non-undefined
 * param is encoded — including empty strings and `0` — because export
 * endpoints treat `max_size=0` as "no resize". Returns a string, not a
 * Promise: callers stick it in an `<a href>`, not a `fetch()`.
 */
export function buildExportUrl(
  endpoint: string,
  params: Record<string, string | number | undefined>,
): string {
  const sp = new URLSearchParams()
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined) {
      sp.set(key, String(val))
    }
  }
  const qs = sp.toString()
  return qs ? `${BASE}${endpoint}?${qs}` : `${BASE}${endpoint}`
}

const inFlightRequests = new Map<string, Promise<unknown>>()

export function dedup<T>(key: string, factory: () => Promise<T>): Promise<T> {
  const existing = inFlightRequests.get(key)
  if (existing) return existing as Promise<T>
  const promise = factory().finally(() => inFlightRequests.delete(key))
  inFlightRequests.set(key, promise)
  return promise
}

export type HttpMethod = 'GET' | 'POST' | 'DELETE' | 'PUT' | 'PATCH'

export interface ApiRequestOptions {
  body?: unknown
  signal?: AbortSignal
  dedupKey?: string
  timeoutMs?: number
}

async function rawRequest<T>(method: HttpMethod, url: string, opts: ApiRequestOptions): Promise<T> {
  const { body, signal, timeoutMs = DEFAULT_TIMEOUT } = opts
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
  if (signal) {
    signal.addEventListener('abort', () => controller.abort(), { once: true })
  }
  try {
    const init: RequestInit = { method, signal: controller.signal }
    if (body !== undefined) {
      init.headers = { 'Content-Type': 'application/json' }
      init.body = JSON.stringify(body)
    }
    const res = await fetch(url, init)
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
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    if (e instanceof ApiError) throw e
    throw new ApiError(0, e instanceof Error ? e.message : 'Network error')
  } finally {
    clearTimeout(timeoutId)
  }
}

/**
 * Single unified entrypoint for HTTP requests.
 * - GET-like calls: omit `body`.
 * - POST/PUT/PATCH: pass `body` (will be JSON-encoded with Content-Type header).
 * - `dedupKey` opts in to in-flight request merging.
 */
export function apiRequest<T>(method: HttpMethod, url: string, opts: ApiRequestOptions = {}): Promise<T> {
  if (opts.dedupKey) {
    return dedup(opts.dedupKey, () => rawRequest<T>(method, url, opts))
  }
  return rawRequest<T>(method, url, opts)
}

// Thin backwards-compatible wrappers. 51 call sites already use these names;
// keeping them as one-liners avoids churn while routing all logic through apiRequest.

export function apiFetch<T>(url: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>('GET', url, { signal })
}

export function apiPost<T>(url: string, body: unknown = {}, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>('POST', url, { body, signal })
}

export function apiDelete<T>(url: string, signal?: AbortSignal): Promise<T> {
  return apiRequest<T>('DELETE', url, { signal })
}

import type {
  LabelerNextResponse,
  LabelerStats,
  LabeledImage,
  LabelerHistoryResponse,
} from '../types'
import { BASE, buildQuery, buildExportUrl, apiFetch, apiPost, apiDelete, dedup } from './core'

// Re-export for backwards compat with existing `import { ..., type LabeledImage } from '../api'` sites.
export type { LabelerNextResponse, LabelerStats, LabeledImage, LabelerHistoryResponse }

export async function fetchLabelerNext(params?: {
  source?: string
  media?: string
}, signal?: AbortSignal): Promise<LabelerNextResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/labeler/next${qs ? '?' + qs : ''}`, signal)
}

export async function labelImage(imageId: number, verdict: string, tags: string[] = []): Promise<{ ok: boolean }> {
  return apiPost(`${BASE}/api/labeler/${imageId}`, { verdict, tags })
}

export async function unlabelImage(imageId: number): Promise<{ ok: boolean }> {
  return apiDelete(`${BASE}/api/labeler/${imageId}`)
}

export async function fetchLabelerStats(signal?: AbortSignal): Promise<LabelerStats> {
  return dedup('labeler-stats', () => apiFetch(`${BASE}/api/labeler/stats`, signal))
}

export async function fetchLabelerHistory(params?: {
  verdict?: string
  tag?: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<LabelerHistoryResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/labeler/history?${qs}`, signal)
}

export function getExportUrl(verdict = 'liked', tag?: string, maxSize?: number): string {
  return buildExportUrl('/api/labeler/export', { verdict, tag, max_size: maxSize })
}

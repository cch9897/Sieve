import { BASE, buildQuery, ApiError, apiFetch, dedup } from './core'

export interface LabelerNextResponse {
  image: {
    id: number
    source: string
    source_id: string
    file_path: string
    url: string
    created_at: string
    date: string | null
    is_video: boolean
    thumb_url: string
    vision_score: number | null
    vision_scores?: Record<string, number>
  } | null
  remaining: number
  total_labeled: number
}

export interface LabelerStats {
  total_images: number
  liked: number
  disliked: number
  skipped: number
  total_labeled: number
  remaining: number
  top_tags: { tag: string; count: number }[]
  liked_by_source: Record<string, number>
  total_by_source: Record<string, number>
  labeled_by_source: Record<string, number>
  liked_top_auto_tags: { tag: string; count: number }[]
}

export interface LabeledImage {
  id: number
  source: string
  source_id: string
  file_path: string
  url: string
  created_at: string
  date: string | null
  is_video: boolean
  thumb_url: string
  verdict: string
  tags: string[]
  vision_score?: number | null
  vision_scores?: Record<string, number>
}

export interface LabelerHistoryResponse {
  images: LabeledImage[]
  total: number
  page: number
  per_page: number
  pages: number
}

export async function fetchLabelerNext(params?: {
  source?: string
  media?: string
}, signal?: AbortSignal): Promise<LabelerNextResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/labeler/next${qs ? '?' + qs : ''}`, signal)
}

export async function labelImage(imageId: number, verdict: string, tags: string[] = []): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/labeler/${imageId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ verdict, tags }),
  })
  if (!res.ok) throw new ApiError(res.status, `Label failed: ${res.statusText}`)
  return res.json()
}

export async function unlabelImage(imageId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/labeler/${imageId}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, `Unlabel failed: ${res.statusText}`)
  return res.json()
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
  const sp = new URLSearchParams({ verdict })
  if (tag) sp.set('tag', tag)
  if (maxSize !== undefined) sp.set('max_size', String(maxSize))
  return `${BASE}/api/labeler/export?${sp}`
}

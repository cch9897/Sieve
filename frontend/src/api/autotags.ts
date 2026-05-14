import { BASE, buildQuery, apiFetch, apiPost, dedup } from './core'

export interface AutoTagsDetail {
  found: boolean
  image_id: number
  rating?: Record<string, number>
  general?: Record<string, number>
  characters?: Record<string, number>
  top_tags?: string
  model_name?: string
  threshold?: number
  created_at?: string
}

export interface AutoTagsStats {
  tagged: number
  total: number
  remaining: number
  progress_pct: number
  top_tags: { tag: string; count: number }[]
  errored: number
  errors_by_source: Record<string, number>
}

export interface AutoTagsSearchResponse {
  images: (import('../types').ImageItem & { auto_tags: string })[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface AutoTagsBatchResponse {
  tags: Record<string, { top_tags: string; rating: string }>
}

export async function fetchAutoTags(imageId: number, signal?: AbortSignal): Promise<AutoTagsDetail> {
  return apiFetch(`${BASE}/api/autotags/${imageId}`, signal)
}

export async function fetchAutoTagsStats(signal?: AbortSignal): Promise<AutoTagsStats> {
  return dedup('autotags-stats', () => apiFetch(`${BASE}/api/autotags/stats`, signal))
}

export async function searchByAutoTag(params: {
  tag: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<AutoTagsSearchResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/autotags/search?${qs}`, signal)
}

export async function fetchAutoTagsBatch(ids: number[], signal?: AbortSignal): Promise<AutoTagsBatchResponse> {
  return apiPost(`${BASE}/api/autotags/batch`, { ids }, signal)
}

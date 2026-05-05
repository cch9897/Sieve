import { BASE, buildQuery, ApiError, apiFetch, dedup } from './core'

export interface DanbooruImage {
  id: number
  ext: string
  score: number
  rating: string
  created_at: string
  file_size: number
  tags: string
  tag_categories: Record<string, string[]>
  is_video: boolean
  thumb_url: string
  preview_url: string
  video_url: string | null
  preference_score?: number
  aesthetic_score?: number
  tag_score?: number
}

export interface DanbooruLabelerNextResponse {
  image: DanbooruImage | null
  remaining: number
  total_labeled: number
}

export interface DanbooruLabelerStats {
  total_images: number
  liked: number
  disliked: number
  skipped: number
  total_labeled: number
  remaining: number
  top_tags: { tag: string; count: number }[]
  liked_by_rating: Record<string, number>
  labeled_by_rating: Record<string, number>
  rating_distribution: Record<string, Record<string, number>>
  liked_top_danbooru_tags: { tag: string; count: number }[]
}
export interface DanbooruLabeledImage {
  id: number
  ext: string
  score: number
  rating: string
  danbooru_tags: string
  is_video: boolean
  thumb_url: string
  preview_url: string
  video_url: string | null
  verdict: string
  updated_at: string
  tags: string[]
  vision_score?: number | null
}

export interface DanbooruLabelerHistoryResponse {
  images: DanbooruLabeledImage[]
  total: number
  page: number
  per_page: number
  pages: number
}

export async function fetchDanbooruLabelerNext(params?: {
  rating?: string
  min_score?: number
  media?: string
}, signal?: AbortSignal): Promise<DanbooruLabelerNextResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/danbooru/labeler/next${qs ? '?' + qs : ''}`, signal)
}

export async function danbooruLabelImage(
  imageId: number,
  verdict: string,
  tags: string[] = [],
  meta?: { ext?: string; score?: number; rating?: string; danbooru_tags?: string }
): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/danbooru/labeler/${imageId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      verdict,
      tags,
      ext: meta?.ext || '',
      score: meta?.score || 0,
      rating: meta?.rating || '',
      danbooru_tags: meta?.danbooru_tags || '',
    }),
  })
  if (!res.ok) throw new ApiError(res.status, `Label failed: ${res.statusText}`)
  return res.json()
}

export async function danbooruUnlabelImage(imageId: number): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/api/danbooru/labeler/${imageId}`, { method: 'DELETE' })
  if (!res.ok) throw new ApiError(res.status, `Unlabel failed: ${res.statusText}`)
  return res.json()
}

export async function fetchDanbooruLabelerStats(signal?: AbortSignal): Promise<DanbooruLabelerStats> {
  return dedup('danbooru-labeler-stats', () => apiFetch(`${BASE}/api/danbooru/labeler/stats`, signal))
}

export async function fetchDanbooruLabelerHistory(params?: {
  verdict?: string
  tag?: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<DanbooruLabelerHistoryResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/danbooru/labeler/history?${qs}`, signal)
}

// AI Recommended
export interface DanbooruRecommendedResponse {
  images: (DanbooruLabeledImage & { preference_score: number })[]
  total: number
  page: number
  per_page: number
  pages: number
  model_info: { auc: number; n_samples: number; model_type: string }
}

export async function fetchDanbooruRecommended(params: {
  page?: number
  per_page?: number
  min_score?: number
  rating?: string
}, signal?: AbortSignal): Promise<DanbooruRecommendedResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/danbooru/recommended?${qs}`, signal)
}

export interface HistogramBin {
  lo: number
  hi: number
  count: number
  accepted: number
  rejected: number
}

export interface CIStats {
  mean: number
  std: number
  ci95_lo: number
  ci95_hi: number
  median: number
  p25: number
  p75: number
  p10: number
  p90: number
  n: number
}

export interface DanbooruCandidatesStats {
  total: number
  pending: number
  labeled: number
  score_distribution: Record<string, number>
  rating_distribution: Record<string, number>
  avg_score: number
  top_score: number
  histogram?: HistogramBin[]
  ci_stats?: CIStats
  model_loaded: boolean
  model_auc: number
  model_samples: number
  active_model?: string | null
  vision_models?: Record<string, { model_class: string; cv_auc: number; type: string }>
}

export async function fetchDanbooruCandidatesStats(signal?: AbortSignal): Promise<DanbooruCandidatesStats> {
  return apiFetch(`${BASE}/api/danbooru/candidates/stats`, signal)
}

export async function fetchDanbooruCandidateNext(params: {
  rating?: string
  media?: string
  min_score?: number
  min_aes?: number
}, signal?: AbortSignal): Promise<DanbooruLabelerNextResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/danbooru/candidates/next?${qs}`, signal)
}

export async function markDanbooruCandidate(imageId: number): Promise<void> {
  const res = await fetch(`${BASE}/api/danbooru/candidates/${imageId}/mark`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to mark candidate')
}

export async function clearDanbooruCandidates(): Promise<{ ok: boolean; deleted: number }> {
  const res = await fetch(`${BASE}/api/danbooru/candidates/clear`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to clear candidates')
  return res.json()
}

export interface RescoreStatus {
  running: boolean
  log: string
}

export async function startCandidatesRescore(): Promise<{ status: string; model?: string }> {
  const res = await fetch(`${BASE}/api/danbooru/candidates/rescore`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start rescore')
  return res.json()
}

export async function fetchRescoreStatus(signal?: AbortSignal): Promise<RescoreStatus> {
  return apiFetch(`${BASE}/api/danbooru/candidates/rescore/status`, signal)
}

export async function stopCandidatesRescore(): Promise<{ stopped: boolean }> {
  const res = await fetch(`${BASE}/api/danbooru/candidates/rescore/stop`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to stop rescore')
  return res.json()
}

export function getDanbooruExportUrl(verdict = 'liked', tag?: string, maxSize?: number): string {
  const sp = new URLSearchParams({ verdict })
  if (tag) sp.set('tag', tag)
  if (maxSize !== undefined) sp.set('max_size', String(maxSize))
  return `${BASE}/api/danbooru/labeler/export?${sp}`
}

import type {
  DanbooruImage,
  DanbooruLabelerNextResponse,
  DanbooruLabelerStats,
  DanbooruLabeledImage,
  DanbooruLabelerHistoryResponse,
  DanbooruRecommendedResponse,
} from '../types'
import { BASE, buildQuery, buildExportUrl, apiFetch, apiPost, apiDelete, dedup } from './core'

// Re-export for backwards compat with existing barrel imports from '../api'.
export type {
  DanbooruImage,
  DanbooruLabelerNextResponse,
  DanbooruLabelerStats,
  DanbooruLabeledImage,
  DanbooruLabelerHistoryResponse,
  DanbooruRecommendedResponse,
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
  return apiPost(`${BASE}/api/danbooru/labeler/${imageId}`, {
    verdict,
    tags,
    ext: meta?.ext || '',
    score: meta?.score || 0,
    rating: meta?.rating || '',
    danbooru_tags: meta?.danbooru_tags || '',
  })
}

export async function danbooruUnlabelImage(imageId: number): Promise<{ ok: boolean }> {
  return apiDelete(`${BASE}/api/danbooru/labeler/${imageId}`)
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

export async function fetchDanbooruRecommended(params: {
  page?: number
  per_page?: number
  min_score?: number
  rating?: string
}, signal?: AbortSignal): Promise<DanbooruRecommendedResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/danbooru/recommended?${qs}`, signal)
}

// --- Candidate-screening types (kept here: only used inside the danbooru
// pre-screening UI; not part of the labeler core schema). -------------------

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
  await apiPost(`${BASE}/api/danbooru/candidates/${imageId}/mark`)
}

export async function clearDanbooruCandidates(): Promise<{ ok: boolean; deleted: number }> {
  return apiPost(`${BASE}/api/danbooru/candidates/clear`)
}

export interface RescoreStatus {
  running: boolean
  log: string
}

export async function startCandidatesRescore(): Promise<{ status: string; model?: string }> {
  return apiPost(`${BASE}/api/danbooru/candidates/rescore`)
}

export async function fetchRescoreStatus(signal?: AbortSignal): Promise<RescoreStatus> {
  return apiFetch(`${BASE}/api/danbooru/candidates/rescore/status`, signal)
}

export async function stopCandidatesRescore(): Promise<{ stopped: boolean }> {
  return apiPost(`${BASE}/api/danbooru/candidates/rescore/stop`)
}

export function getDanbooruExportUrl(verdict = 'liked', tag?: string, maxSize?: number): string {
  return buildExportUrl('/api/danbooru/labeler/export', { verdict, tag, max_size: maxSize })
}

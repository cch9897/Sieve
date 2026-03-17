import type { ImageListResponse, ImageDetail, Stats, NovelListResponse, NovelDetail } from './types'

const BASE = ''

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function apiFetch<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) {
    throw new ApiError(res.status, `Request failed: ${res.statusText}`)
  }
  return res.json()
}

export async function fetchImages(params: {
  source?: string
  date?: string
  media?: string
  sort?: string
  page?: number
  per_page?: number
}): Promise<ImageListResponse> {
  const sp = new URLSearchParams()
  if (params.source) sp.set('source', params.source)
  if (params.date) sp.set('date', params.date)
  if (params.media) sp.set('media', params.media)
  if (params.sort) sp.set('sort', params.sort)
  if (params.page) sp.set('page', String(params.page))
  if (params.per_page) sp.set('per_page', String(params.per_page))
  return apiFetch(`${BASE}/api/images?${sp}`)
}

export async function fetchImageDetail(id: number): Promise<ImageDetail> {
  return apiFetch(`${BASE}/api/images/${id}`)
}

export async function fetchStats(): Promise<Stats> {
  return apiFetch(`${BASE}/api/stats`)
}

export async function fetchDates(): Promise<{ dates: string[] }> {
  return apiFetch(`${BASE}/api/dates`)
}

export async function fetchSources(): Promise<{ sources: string[], counts: Record<string, number> }> {
  return apiFetch(`${BASE}/api/sources`)
}

// Novel APIs
export async function fetchNovels(params: {
  date?: string
  sort?: string
  search?: string
  page?: number
  per_page?: number
}): Promise<NovelListResponse> {
  const sp = new URLSearchParams()
  if (params.date) sp.set('date', params.date)
  if (params.sort) sp.set('sort', params.sort)
  if (params.search) sp.set('search', params.search)
  if (params.page) sp.set('page', String(params.page))
  if (params.per_page) sp.set('per_page', String(params.per_page))
  return apiFetch(`${BASE}/api/novels?${sp}`)
}

export async function fetchNovelDetail(id: number): Promise<NovelDetail> {
  return apiFetch(`${BASE}/api/novels/${id}`)
}

export async function fetchNovelDates(): Promise<{ dates: string[] }> {
  return apiFetch(`${BASE}/api/novels/dates`)
}

// Labeler APIs
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
}): Promise<LabelerNextResponse> {
  const sp = new URLSearchParams()
  if (params?.source) sp.set('source', params.source)
  if (params?.media) sp.set('media', params.media)
  const qs = sp.toString()
  return apiFetch(`${BASE}/api/labeler/next${qs ? '?' + qs : ''}`)
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

export async function fetchLabelerStats(): Promise<LabelerStats> {
  return apiFetch(`${BASE}/api/labeler/stats`)
}

export async function fetchLabelerHistory(params?: {
  verdict?: string
  tag?: string
  page?: number
  per_page?: number
}): Promise<LabelerHistoryResponse> {
  const sp = new URLSearchParams()
  if (params?.verdict) sp.set('verdict', params.verdict)
  if (params?.tag) sp.set('tag', params.tag)
  if (params?.page) sp.set('page', String(params.page))
  if (params?.per_page) sp.set('per_page', String(params.per_page))
  return apiFetch(`${BASE}/api/labeler/history?${sp}`)
}

export function getExportUrl(verdict = 'liked', tag?: string): string {
  const sp = new URLSearchParams({ verdict })
  if (tag) sp.set('tag', tag)
  return `${BASE}/api/labeler/export?${sp}`
}

// ==========================================================================
// Danbooru Labeler APIs
// ==========================================================================

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
}): Promise<DanbooruLabelerNextResponse> {
  const sp = new URLSearchParams()
  if (params?.rating) sp.set('rating', params.rating)
  if (params?.min_score !== undefined) sp.set('min_score', String(params.min_score))
  if (params?.media) sp.set('media', params.media)
  const qs = sp.toString()
  return apiFetch(`${BASE}/api/danbooru/labeler/next${qs ? '?' + qs : ''}`)
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

export async function fetchDanbooruLabelerStats(): Promise<DanbooruLabelerStats> {
  return apiFetch(`${BASE}/api/danbooru/labeler/stats`)
}

export async function fetchDanbooruLabelerHistory(params?: {
  verdict?: string
  tag?: string
  page?: number
  per_page?: number
}): Promise<DanbooruLabelerHistoryResponse> {
  const sp = new URLSearchParams()
  if (params?.verdict) sp.set('verdict', params.verdict)
  if (params?.tag) sp.set('tag', params.tag)
  if (params?.page) sp.set('page', String(params.page))
  if (params?.per_page) sp.set('per_page', String(params.per_page))
  return apiFetch(`${BASE}/api/danbooru/labeler/history?${sp}`)
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
}): Promise<DanbooruRecommendedResponse> {
  const sp = new URLSearchParams()
  if (params.page) sp.set('page', String(params.page))
  if (params.per_page) sp.set('per_page', String(params.per_page))
  if (params.min_score !== undefined) sp.set('min_score', String(params.min_score))
  if (params.rating) sp.set('rating', params.rating)
  return apiFetch(`${BASE}/api/danbooru/recommended?${sp}`)
}

export interface DanbooruCandidatesStats {
  total: number
  pending: number
  labeled: number
  score_distribution: Record<string, number>
  rating_distribution: Record<string, number>
  avg_score: number
  top_score: number
  model_loaded: boolean
  model_auc: number
  model_samples: number
}

export async function fetchDanbooruCandidatesStats(): Promise<DanbooruCandidatesStats> {
  return apiFetch(`${BASE}/api/danbooru/candidates/stats`)
}

export async function fetchDanbooruCandidateNext(params: {
  rating?: string
  media?: string
  min_score?: number
}): Promise<DanbooruLabelerNextResponse> {
  const sp = new URLSearchParams()
  if (params.rating) sp.set('rating', params.rating)
  if (params.media) sp.set('media', params.media)
  if (params.min_score !== undefined) sp.set('min_score', String(params.min_score))
  return apiFetch(`${BASE}/api/danbooru/candidates/next?${sp}`)
}

export async function markDanbooruCandidate(imageId: number): Promise<void> {
  await fetch(`${BASE}/api/danbooru/candidates/${imageId}/mark`, { method: 'POST' })
}

export function getDanbooruExportUrl(verdict = 'liked', tag?: string): string {
  const sp = new URLSearchParams({ verdict })
  if (tag) sp.set('tag', tag)
  return `${BASE}/api/danbooru/labeler/export?${sp}`
}

// ==========================================================================
// Auto-tags APIs
// ==========================================================================

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
  images: (import('./types').ImageItem & { auto_tags: string })[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface AutoTagsBatchResponse {
  tags: Record<string, { top_tags: string; rating: string }>
}

export async function fetchAutoTags(imageId: number): Promise<AutoTagsDetail> {
  return apiFetch(`${BASE}/api/autotags/${imageId}`)
}

export async function fetchAutoTagsStats(): Promise<AutoTagsStats> {
  return apiFetch(`${BASE}/api/autotags/stats`)
}

export interface PrefetchStatus {
  running: boolean
  message?: string
  stopped?: boolean
}

export async function fetchPrefetchStatus(): Promise<PrefetchStatus> {
  return apiFetch(`${BASE}/api/danbooru/prefetch/status`)
}

export async function startPrefetch(): Promise<PrefetchStatus> {
  const res = await fetch(`${BASE}/api/danbooru/prefetch/start`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start prefetch')
  return res.json()
}

export async function stopPrefetch(): Promise<PrefetchStatus> {
  const res = await fetch(`${BASE}/api/danbooru/prefetch/stop`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to stop prefetch')
  return res.json()
}

export async function searchByAutoTag(params: {
  tag: string
  page?: number
  per_page?: number
}): Promise<AutoTagsSearchResponse> {
  const sp = new URLSearchParams()
  sp.set('tag', params.tag)
  if (params.page) sp.set('page', String(params.page))
  if (params.per_page) sp.set('per_page', String(params.per_page))
  return apiFetch(`${BASE}/api/autotags/search?${sp}`)
}

export async function fetchAutoTagsBatch(ids: number[]): Promise<AutoTagsBatchResponse> {
  return apiFetch(`${BASE}/api/autotags/batch?ids=${ids.join(',')}`)
}

// ==========================================================================
// ML Model Management APIs
// ==========================================================================

export interface MLModelXGBoost {
  loaded: boolean
  auc: number
  n_samples: number
  n_liked: number
  n_disliked: number
  model_type: string
  vocab_size: number
}

export interface MLModelCNN {
  loaded: boolean
  model_name: string
  cv_auc: number
  n_samples: number
  input_size: number
  fold_aucs: number[]
}

export interface MLModelsInfo {
  xgboost: MLModelXGBoost | null
  cnn: MLModelCNN | null
}

export interface MLTaskStatus {
  running: boolean
  finished: boolean
  exit_code: number | null
  log: string
}

export async function fetchMLModels(): Promise<MLModelsInfo> {
  return apiFetch(`${BASE}/api/ml/models`)
}

export async function startRetrainXGBoost(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/ml/retrain-xgboost`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start retrain')
  return res.json()
}

export async function fetchRetrainStatus(): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/retrain-xgboost/status`)
}

export async function startPackDataset(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/ml/pack-dataset`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start packing')
  return res.json()
}

export async function fetchPackStatus(): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/pack-dataset/status`)
}

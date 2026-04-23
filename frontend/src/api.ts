import type { ImageListResponse, ImageDetail, Stats, NovelListResponse, NovelDetail } from './types'

const BASE = ''
const DEFAULT_TIMEOUT = 30_000

class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams()
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      sp.set(key, String(val))
    }
  }
  return sp.toString()
}

const inFlightRequests = new Map<string, Promise<unknown>>()

function dedup<T>(key: string, factory: () => Promise<T>): Promise<T> {
  const existing = inFlightRequests.get(key)
  if (existing) return existing as Promise<T>
  const promise = factory().finally(() => inFlightRequests.delete(key))
  inFlightRequests.set(key, promise)
  return promise
}

async function apiFetch<T>(url: string, signal?: AbortSignal): Promise<T> {
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

export async function fetchImages(params: {
  source?: string
  date?: string
  media?: string
  sort?: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<ImageListResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/images?${qs}`, signal)
}

export async function fetchImageDetail(id: number, signal?: AbortSignal): Promise<ImageDetail> {
  return apiFetch(`${BASE}/api/images/${id}`, signal)
}

export async function fetchStats(signal?: AbortSignal): Promise<Stats> {
  return dedup('stats', () => apiFetch(`${BASE}/api/stats`, signal))
}

export async function fetchDates(signal?: AbortSignal): Promise<{ dates: string[] }> {
  return dedup('dates', () => apiFetch(`${BASE}/api/dates`, signal))
}

export async function fetchSources(signal?: AbortSignal): Promise<{ sources: string[], counts: Record<string, number> }> {
  return dedup('sources', () => apiFetch(`${BASE}/api/sources`, signal))
}

// Novel APIs
export async function fetchNovels(params: {
  date?: string
  sort?: string
  search?: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<NovelListResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/novels?${qs}`, signal)
}

export async function fetchNovelDetail(id: number, signal?: AbortSignal): Promise<NovelDetail> {
  return apiFetch(`${BASE}/api/novels/${id}`, signal)
}

export async function fetchNovelDates(signal?: AbortSignal): Promise<{ dates: string[] }> {
  return dedup('novel-dates', () => apiFetch(`${BASE}/api/novels/dates`, signal))
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

export async function fetchAutoTags(imageId: number, signal?: AbortSignal): Promise<AutoTagsDetail> {
  return apiFetch(`${BASE}/api/autotags/${imageId}`, signal)
}

export async function fetchAutoTagsStats(signal?: AbortSignal): Promise<AutoTagsStats> {
  return dedup('autotags-stats', () => apiFetch(`${BASE}/api/autotags/stats`, signal))
}

export interface PrefetchStatus {
  running: boolean
  message?: string
  stopped?: boolean
}

export async function fetchPrefetchStatus(signal?: AbortSignal): Promise<PrefetchStatus> {
  return apiFetch(`${BASE}/api/danbooru/prefetch/status`, signal)
}

export type PrefetchMode = 'tag+vision' | 'vision-only'

export async function startPrefetch(mode: PrefetchMode = 'tag+vision', threshold?: number, model?: string): Promise<PrefetchStatus> {
  const sp = new URLSearchParams({ mode })
  if (threshold !== undefined) sp.set('threshold', String(threshold))
  if (model) sp.set('model', model)
  const res = await fetch(`${BASE}/api/danbooru/prefetch/start?${sp}`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start prefetch')
  return res.json()
}

export async function stopPrefetch(): Promise<PrefetchStatus> {
  const res = await fetch(`${BASE}/api/danbooru/prefetch/stop`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to stop prefetch')
  return res.json()
}

// GPU Inference Config
export interface GpuConfig {
  url: string
  batch_size: number
  enabled: boolean
  remote_health?: {
    model_name?: string
    device?: string
    fp16?: boolean
    cv_auc?: number
    gpu_memory_mb?: number
  } | null
}

export interface GpuTestResult {
  ok: boolean
  error?: string
  health?: {
    model_name?: string
    device?: string
    fp16?: boolean
    cv_auc?: number
    gpu_memory_mb?: number
  }
}

export async function fetchGpuConfig(signal?: AbortSignal): Promise<GpuConfig> {
  return apiFetch(`${BASE}/api/danbooru/gpu/config`, signal)
}

export async function updateGpuConfig(cfg: Partial<{ url: string; batch_size: number; enabled: boolean }>): Promise<GpuConfig> {
  const res = await fetch(`${BASE}/api/danbooru/gpu/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  })
  if (!res.ok) throw new ApiError(res.status, 'Failed to update GPU config')
  return res.json()
}

export async function testGpuConnection(): Promise<GpuTestResult> {
  const res = await fetch(`${BASE}/api/danbooru/gpu/test`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to test GPU connection')
  return res.json()
}

// Inference Mode APIs
export type InferenceMode = 'cpu' | 'local_gpu' | 'remote'

export interface InferenceStatus {
  inference_mode: InferenceMode
  current_device: string
  cuda_available: boolean
  cuda_info: {
    device_name: string
    total_memory_mb: number
    allocated_mb: number
    device_count: number
  } | null
  cnn_loaded: boolean
  cnn_model_name: string | null
  cnn_cv_auc: number | null
  remote_url: string
  remote_enabled: boolean
  remote_batch_size: number
}

export interface InferenceModeResponse {
  inference_mode: InferenceMode
  current_device: string
  cuda_info: InferenceStatus['cuda_info']
}

export async function fetchInferenceStatus(signal?: AbortSignal): Promise<InferenceStatus> {
  return apiFetch(`${BASE}/api/inference/status`, signal)
}

export async function setInferenceMode(mode: InferenceMode): Promise<InferenceModeResponse> {
  const res = await fetch(`${BASE}/api/inference/mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(res.status, data.detail || 'Failed to set inference mode')
  }
  return res.json()
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
  const res = await fetch(`${BASE}/api/autotags/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
    signal,
  })
  if (!res.ok) throw new ApiError(res.status, `Request failed: ${res.statusText}`)
  return res.json()
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

export async function fetchMLModels(signal?: AbortSignal): Promise<MLModelsInfo> {
  return dedup('ml-models', () => apiFetch(`${BASE}/api/ml/models`, signal))
}

export async function startRetrainXGBoost(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/ml/retrain-xgboost`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start retrain')
  return res.json()
}

export async function fetchRetrainStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/retrain-xgboost/status`, signal)
}

export async function startPackDataset(maxSize?: number): Promise<{ status: string }> {
  const sp = maxSize !== undefined ? `?max_size=${maxSize}` : ''
  const res = await fetch(`${BASE}/api/ml/pack-dataset${sp}`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start packing')
  return res.json()
}

export async function fetchPackStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/pack-dataset/status`, signal)
}

export async function startVisionScore(model?: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/ml/vision-score`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: model || null }),
  })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start vision scoring')
  return res.json()
}

export async function fetchVisionScoreStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/vision-score/status`, signal)
}

export async function startTagTrain(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/ml/tag-train`, { method: 'POST' })
  if (!res.ok) throw new ApiError(res.status, 'Failed to start tag train')
  return res.json()
}

export async function fetchTagTrainStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/tag-train/status`, signal)
}

// ==========================================================================
// Multi-Model APIs
// ==========================================================================

export interface VisionModelInfo {
  model_name: string
  model_class: string
  type: string
  cv_auc: number
  n_samples: number
  input_size: number | string
  fold_aucs: number[]
  is_active: boolean
}

export interface ModelsResponse {
  models: Record<string, VisionModelInfo>
  active_model: string | null
}

export async function fetchVisionModels(signal?: AbortSignal): Promise<ModelsResponse> {
  return dedup('vision-models', () => apiFetch(`${BASE}/api/models`, signal))
}

export async function setActiveModel(modelKey: string): Promise<{ active_model: string }> {
  const res = await fetch(`${BASE}/api/models/active`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_key: modelKey }),
  })
  if (!res.ok) throw new ApiError(res.status, 'Failed to set active model')
  return res.json()
}

export interface VisionScoreCompare {
  image_id: number
  scores: Record<string, { score: number; scored_at: string }>
}

export async function fetchVisionScoreCompare(imageId: number, signal?: AbortSignal): Promise<VisionScoreCompare> {
  return apiFetch(`${BASE}/api/vision-scores/compare?image_id=${imageId}`, signal)
}

export interface CompareStatsResponse {
  models: Record<string, {
    total: number
    avg_score: number | null
    min_score: number | null
    max_score: number | null
  }>
}

export async function fetchVisionScoreCompareStats(signal?: AbortSignal): Promise<CompareStatsResponse> {
  return dedup('compare-stats', () => apiFetch(`${BASE}/api/vision-scores/compare-stats`, signal))
}

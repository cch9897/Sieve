import { BASE, apiFetch, apiPost, dedup } from './core'

// Prefetch
export interface PrefetchStatus {
  running: boolean
  message?: string
  stopped?: boolean
}

export type PrefetchMode = 'tag+vision' | 'vision-only'

export async function fetchPrefetchStatus(signal?: AbortSignal): Promise<PrefetchStatus> {
  return apiFetch(`${BASE}/api/danbooru/prefetch/status`, signal)
}

export async function startPrefetch(mode: PrefetchMode = 'tag+vision', threshold?: number, model?: string): Promise<PrefetchStatus> {
  const qs = new URLSearchParams({ mode })
  if (threshold !== undefined) qs.set('threshold', String(threshold))
  if (model) qs.set('model', model)
  return apiPost(`${BASE}/api/danbooru/prefetch/start?${qs}`)
}

export async function stopPrefetch(): Promise<PrefetchStatus> {
  return apiPost(`${BASE}/api/danbooru/prefetch/stop`)
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
  return apiPost(`${BASE}/api/danbooru/gpu/config`, cfg)
}

export async function testGpuConnection(): Promise<GpuTestResult> {
  return apiPost(`${BASE}/api/danbooru/gpu/test`)
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
  return apiPost(`${BASE}/api/inference/mode`, { mode })
}

// ML Model Management APIs
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
  return apiPost(`${BASE}/api/ml/retrain-xgboost`)
}

export async function fetchRetrainStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/retrain-xgboost/status`, signal)
}

export async function startPackDataset(maxSize?: number): Promise<{ status: string }> {
  const sp = maxSize !== undefined ? `?max_size=${maxSize}` : ''
  return apiPost(`${BASE}/api/ml/pack-dataset${sp}`)
}

export async function fetchPackStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/pack-dataset/status`, signal)
}

export async function startVisionScore(model?: string): Promise<{ status: string }> {
  return apiPost(`${BASE}/api/ml/vision-score`, { model: model || null })
}

export async function fetchVisionScoreStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/vision-score/status`, signal)
}

export async function startTagTrain(): Promise<{ status: string }> {
  return apiPost(`${BASE}/api/ml/tag-train`)
}

export async function fetchTagTrainStatus(signal?: AbortSignal): Promise<MLTaskStatus> {
  return apiFetch(`${BASE}/api/ml/tag-train/status`, signal)
}

// Multi-Model APIs
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
  return apiPost(`${BASE}/api/models/active`, { model_key: modelKey })
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

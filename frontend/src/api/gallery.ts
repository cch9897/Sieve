import type { ImageListResponse, ImageDetail } from '../types'
import { BASE, buildQuery, apiFetch } from './core'

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

export async function fetchLiked(params: {
  source?: string
  date?: string
  media?: string
  sort?: string
  page?: number
  per_page?: number
}, signal?: AbortSignal): Promise<ImageListResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/liked?${qs}`, signal)
}

export async function fetchRandomLiked(params: {
  source?: string
  date?: string
  media?: string
  count?: number
}, signal?: AbortSignal): Promise<ImageListResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>)
  return apiFetch(`${BASE}/api/liked/random?${qs}`, signal)
}

export async function fetchImageDetail(id: number, signal?: AbortSignal): Promise<ImageDetail> {
  return apiFetch(`${BASE}/api/images/${id}`, signal)
}

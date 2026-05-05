import type { NovelListResponse, NovelDetail } from '../types'
import { BASE, buildQuery, apiFetch, dedup } from './core'

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

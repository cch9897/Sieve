import type { Stats } from '../types'
import { BASE, apiFetch, dedup } from './core'

export async function fetchStats(signal?: AbortSignal): Promise<Stats> {
  return dedup('stats', () => apiFetch(`${BASE}/api/stats`, signal))
}

export async function fetchDates(signal?: AbortSignal): Promise<{ dates: string[] }> {
  return dedup('dates', () => apiFetch(`${BASE}/api/dates`, signal))
}

export async function fetchSources(signal?: AbortSignal): Promise<{ sources: string[]; counts: Record<string, number> }> {
  return dedup('sources', () => apiFetch(`${BASE}/api/sources`, signal))
}

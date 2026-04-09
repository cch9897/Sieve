import { describe, it, expect } from 'vitest'
import { fetchImages, fetchStats, fetchDates, fetchSources } from '../api'

describe('fetchImages', () => {
  it('returns images list from API', async () => {
    const result = await fetchImages({})
    expect(result.images).toHaveLength(2)
    expect(result.total).toBe(2)
    expect(result.images[0].source).toBe('pixiv')
  })

  it('builds URL with source filter', async () => {
    // MSW will still return mock data, but this verifies the function runs
    const result = await fetchImages({ source: 'pixiv', page: 1, per_page: 20 })
    expect(result.images).toBeDefined()
  })
})

describe('fetchStats', () => {
  it('returns stats from API', async () => {
    const stats = await fetchStats()
    expect(stats.total).toBe(100)
    expect(stats.by_source.pixiv).toBe(60)
    expect(stats.by_source.danbooru).toBe(40)
  })
})

describe('fetchDates', () => {
  it('returns dates array', async () => {
    const result = await fetchDates()
    expect(result.dates).toContain('2024-01-01')
    expect(result.dates).toHaveLength(2)
  })
})

describe('fetchSources', () => {
  it('returns sources and counts', async () => {
    const result = await fetchSources()
    expect(result.sources).toContain('pixiv')
    expect(result.counts.pixiv).toBe(60)
  })
})

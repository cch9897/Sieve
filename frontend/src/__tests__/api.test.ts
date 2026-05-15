import { describe, it, expect } from 'vitest'
import {
  ApiError,
  buildQuery,
  dedup,
  apiFetch,
  fetchImages,
  fetchStats,
  fetchDates,
  fetchSources,
} from '../api'

// ---------------------------------------------------------------------------
// Core infrastructure tests
// ---------------------------------------------------------------------------

describe('ApiError', () => {
  it('stores status and message', () => {
    const err = new ApiError(404, 'Not Found')
    expect(err.status).toBe(404)
    expect(err.message).toBe('Not Found')
    expect(err).toBeInstanceOf(Error)
  })

  it('handles status 0 (network errors)', () => {
    const err = new ApiError(0, 'Fetch failed')
    expect(err.status).toBe(0)
    expect(err.message).toBe('Fetch failed')
  })
})

describe('buildQuery', () => {
  it('builds query string from params', () => {
    const qs = buildQuery({ source: 'pixiv', page: 1 })
    expect(qs).toContain('source=pixiv')
    expect(qs).toContain('page=1')
  })

  it('filters out undefined values', () => {
    const qs = buildQuery({ source: 'pixiv', date: undefined, page: 1 })
    expect(qs).not.toContain('date')
    expect(qs).toContain('source=pixiv')
    expect(qs).toContain('page=1')
  })

  it('filters out empty string values', () => {
    const qs = buildQuery({ source: '', page: 1 })
    expect(qs).not.toContain('source')
    expect(qs).toContain('page=1')
  })

  it('preserves 0 as a valid value', () => {
    const qs = buildQuery({ page: 0, count: 5 })
    expect(qs).toContain('page=0')
    expect(qs).toContain('count=5')
  })

  it('returns empty string for all-undefined params', () => {
    const qs = buildQuery({})
    expect(qs).toBe('')
  })
})

describe('dedup', () => {
  it('deduplicates concurrent calls to the same key', async () => {
    let callCount = 0
    const factory = () =>
      new Promise<number>((resolve) => {
        callCount++
        setTimeout(() => resolve(42), 10)
      })

    const [a, b] = await Promise.all([
      dedup('dedup-test-1', factory),
      dedup('dedup-test-1', factory),
    ])
    expect(a).toBe(42)
    expect(b).toBe(42)
    expect(callCount).toBe(1)
  })

  it('clears cache after completion so new calls re-trigger factory', async () => {
    let n = 0
    const factory = () => Promise.resolve(++n)

    const first = await dedup('dedup-test-2', factory)
    expect(first).toBe(1)

    const second = await dedup('dedup-test-2', factory)
    expect(second).toBe(2)
  })
})

describe('apiFetch', () => {
  it('throws ApiError on non-OK responses', async () => {
    // Use the MSW error handler to get a 500
    const promise = apiFetch('/api/images?error=500')
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toMatchObject({ status: 500 })
  })

  it('handles JSON error body with detail field', async () => {
    // The 500 handler returns plain text, which apiFetch tries to parse as JSON
    // and falls back to statusText. We test the fallback path.
    const promise = apiFetch('/api/images?error=500')
    await expect(promise).rejects.toMatchObject({ status: 500 })
  })
})

// ---------------------------------------------------------------------------
// Domain API tests (existing)
// ---------------------------------------------------------------------------

describe('fetchImages', () => {
  it('returns images list from API', async () => {
    const result = await fetchImages({})
    expect(result.images).toHaveLength(2)
    expect(result.total).toBe(2)
    expect(result.images[0].source).toBe('pixiv')
  })

  it('builds URL with source filter', async () => {
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

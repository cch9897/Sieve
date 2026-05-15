import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { usePersistedState } from '../hooks/usePersistedState'

const STORAGE_KEY = 'sieve-ui-state'

const novelState = { search: '', date: '', sort: 'newest', page: 1 }

function callPersist(
  fn: ReturnType<typeof usePersistedState>['persist'] | ReturnType<typeof usePersistedState>['persistNow'],
  searchQuery = 'hello',
) {
  fn(
    'gallery',
    'pixiv',
    '2024-01-01',
    '',
    'newest',
    'infinite',
    { infinite: 1, paged: 1 },
    null,
    null,
    novelState,
    searchQuery,
  )
}

describe('usePersistedState', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('returns the default initial state when localStorage is empty', () => {
    const { result } = renderHook(() => usePersistedState())
    expect(result.current.initial.view).toBe('gallery')
    expect(result.current.initial.sort).toBe('newest')
    expect(result.current.initial.galleryMode).toBe('infinite')
    expect(result.current.initial.searchQuery).toBe('')
  })

  it('reads persisted values from localStorage when shape-valid', () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ view: 'novels', selectedSource: 'pixiv', searchQuery: 'cats' }),
    )
    const { result } = renderHook(() => usePersistedState())
    expect(result.current.initial.view).toBe('novels')
    expect(result.current.initial.selectedSource).toBe('pixiv')
    expect(result.current.initial.searchQuery).toBe('cats')
  })

  it('falls back to default when localStorage contains invalid JSON', () => {
    localStorage.setItem(STORAGE_KEY, '{not valid json')
    const { result } = renderHook(() => usePersistedState())
    expect(result.current.initial.view).toBe('gallery')
    expect(result.current.initial.sort).toBe('newest')
  })

  it('rejects unknown view values and resets to default view', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ view: 'bogus', searchQuery: 'kept' }))
    const { result } = renderHook(() => usePersistedState())
    expect(result.current.initial.view).toBe('gallery')
    // Other valid keys still flow through.
    expect(result.current.initial.searchQuery).toBe('kept')
  })

  it('persist() debounces writes by 500ms', () => {
    const { result } = renderHook(() => usePersistedState())

    act(() => callPersist(result.current.persist, 'first'))
    // Before the timer elapses, nothing has been written.
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()

    act(() => {
      vi.advanceTimersByTime(500)
    })
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string).searchQuery).toBe('first')
  })

  it('persist() coalesces multiple rapid calls into a single write with the latest value', () => {
    const { result } = renderHook(() => usePersistedState())

    act(() => callPersist(result.current.persist, 'a'))
    act(() => {
      vi.advanceTimersByTime(200)
    })
    act(() => callPersist(result.current.persist, 'b'))
    act(() => callPersist(result.current.persist, 'c'))

    // Only after the full 500ms from the LAST call does the write happen.
    act(() => {
      vi.advanceTimersByTime(499)
    })
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()

    act(() => {
      vi.advanceTimersByTime(1)
    })
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string).searchQuery).toBe('c')
  })

  it('persistNow() writes synchronously without waiting for the debounce', () => {
    const { result } = renderHook(() => usePersistedState())

    act(() => callPersist(result.current.persistNow, 'immediate'))
    const raw = localStorage.getItem(STORAGE_KEY)
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string).searchQuery).toBe('immediate')
  })
})

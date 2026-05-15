import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useNovelFilters } from '../hooks/useNovelFilters'
import type { PersistedState } from '../hooks/usePersistedState'

const initial: PersistedState = {
  view: 'novels',
  selectedSource: '',
  selectedDate: '',
  selectedMedia: '',
  sort: 'newest',
  galleryMode: 'infinite',
  pageByMode: { infinite: 1, paged: 1 },
  galleryScrollY: 0,
  selectedNovelId: null,
  novelSearch: 'cats',
  novelDate: '2024-02-02',
  novelSort: 'oldest',
  novelPage: 4,
  searchQuery: '',
}

describe('useNovelFilters', () => {
  it('seeds novelState from the initial persisted values', () => {
    const { result } = renderHook(() => useNovelFilters(initial))
    expect(result.current.novelState).toEqual({
      search: 'cats',
      date: '2024-02-02',
      sort: 'oldest',
      page: 4,
    })
  })

  it('handleNovelStateChange merges a partial patch into existing state', () => {
    const { result } = renderHook(() => useNovelFilters(initial))
    act(() => {
      result.current.handleNovelStateChange({ search: 'dogs', page: 1 })
    })
    expect(result.current.novelState).toEqual({
      search: 'dogs',
      date: '2024-02-02', // untouched
      sort: 'oldest',     // untouched
      page: 1,
    })
  })

  it('successive patches accumulate independently', () => {
    const { result } = renderHook(() => useNovelFilters(initial))
    act(() => {
      result.current.handleNovelStateChange({ sort: 'newest' })
    })
    act(() => {
      result.current.handleNovelStateChange({ page: 9 })
    })
    expect(result.current.novelState.sort).toBe('newest')
    expect(result.current.novelState.page).toBe(9)
    expect(result.current.novelState.search).toBe('cats')
  })
})

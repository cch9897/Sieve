import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useGalleryFilters } from '../hooks/useGalleryFilters'
import type { PersistedState } from '../hooks/usePersistedState'

const baseInitial: PersistedState = {
  view: 'gallery',
  selectedSource: 'pixiv',
  selectedDate: '2024-05-01',
  selectedMedia: 'image',
  sort: 'oldest',
  galleryMode: 'paged',
  pageByMode: { infinite: 4, paged: 7 },
  galleryScrollY: 0,
  selectedNovelId: null,
  novelSearch: '',
  novelDate: '',
  novelSort: 'newest',
  novelPage: 1,
  searchQuery: '',
}

describe('useGalleryFilters', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('seeds state from initial persisted values', () => {
    const { result } = renderHook(() => useGalleryFilters(baseInitial))
    expect(result.current.selectedSource).toBe('pixiv')
    expect(result.current.selectedDate).toBe('2024-05-01')
    expect(result.current.selectedMedia).toBe('image')
    expect(result.current.sort).toBe('oldest')
    expect(result.current.galleryMode).toBe('paged')
    expect(result.current.pageByMode).toEqual({ infinite: 4, paged: 7 })
  })

  it('handleSourceChange updates selectedSource', () => {
    const { result } = renderHook(() => useGalleryFilters(baseInitial))
    act(() => {
      result.current.handleSourceChange('danbooru')
    })
    expect(result.current.selectedSource).toBe('danbooru')
  })

  it('handleMediaChange updates selectedMedia to the new filter', () => {
    const { result } = renderHook(() => useGalleryFilters(baseInitial))
    act(() => {
      result.current.handleMediaChange('video')
    })
    expect(result.current.selectedMedia).toBe('video')
  })

  it('handleGalleryModeChange switches mode and seeds page=1 if missing', () => {
    const init = { ...baseInitial, galleryMode: 'infinite' as const, pageByMode: { infinite: 3, paged: 0 } }
    const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const { result } = renderHook(() => useGalleryFilters(init))

    act(() => {
      result.current.handleGalleryModeChange('paged')
    })
    expect(result.current.galleryMode).toBe('paged')
    // 0 is falsy, so pageByMode.paged is rewritten to 1.
    expect(result.current.pageByMode.paged).toBe(1)
    expect(scrollSpy).toHaveBeenCalledWith({ top: 0, behavior: 'auto' })
  })

  it('handleGalleryModeChange is a no-op when already in that mode', () => {
    const scrollSpy = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
    const { result } = renderHook(() => useGalleryFilters(baseInitial))

    const prevPageByMode = result.current.pageByMode
    act(() => {
      result.current.handleGalleryModeChange('paged') // same mode
    })
    expect(result.current.galleryMode).toBe('paged')
    expect(result.current.pageByMode).toBe(prevPageByMode) // identity unchanged
    expect(scrollSpy).not.toHaveBeenCalled()
  })

  it('handleSortChange updates sort independently of other filters', () => {
    const { result } = renderHook(() => useGalleryFilters(baseInitial))
    act(() => {
      result.current.handleSortChange('random')
    })
    expect(result.current.sort).toBe('random')
    // Other filters intact.
    expect(result.current.selectedSource).toBe('pixiv')
    expect(result.current.selectedDate).toBe('2024-05-01')
  })
})

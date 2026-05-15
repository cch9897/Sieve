import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../test/handlers'
import { useGallery } from '../hooks/useGallery'
import type { GalleryMode } from '../types'

const baseImageList = [
  {
    id: 1,
    source: 'pixiv',
    source_id: '100',
    file_path: 'downloads/test1.jpg',
    url: 'https://pixiv.net/100',
    created_at: '2024-01-01',
    date: '2024-01-01',
    subfolder: null,
    is_video: false,
    thumb_url: '/api/thumb/downloads/test1.jpg',
  },
  {
    id: 2,
    source: 'danbooru',
    source_id: '200',
    file_path: 'downloads/test2.jpg',
    url: 'https://danbooru.donmai.us/200',
    created_at: '2024-01-02',
    date: '2024-01-02',
    subfolder: null,
    is_video: false,
    thumb_url: '/api/thumb/downloads/test2.jpg',
  },
]

function buildFilters(overrides: Partial<{
  galleryMode: GalleryMode
  pageByMode: Record<GalleryMode, number>
  selectedSource: string
}> = {}) {
  const setPageByMode = vi.fn()
  const filters = {
    selectedSource: overrides.selectedSource ?? '',
    selectedDate: '',
    selectedMedia: '' as const,
    sort: 'newest',
    galleryMode: overrides.galleryMode ?? ('infinite' as GalleryMode),
    pageByMode: overrides.pageByMode ?? { infinite: 1, paged: 1 },
    setPageByMode,
  }
  return { filters, setPageByMode }
}

describe('useGallery', () => {
  beforeEach(() => {
    // Default handlers come from src/test/handlers.ts via the global server.
    server.resetHandlers()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns initial state with loading=true', () => {
    const { filters } = buildFilters()
    // view=novels means the load effect is skipped — we only check initial flags.
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'novels', initialSearchQuery: '' }),
    )
    expect(result.current.images).toEqual([])
    expect(result.current.loading).toBe(true)
    expect(result.current.error).toBeNull()
    expect(result.current.searchQuery).toBe('')
  })

  it('loads images on mount when view=gallery', async () => {
    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )

    await waitFor(() => expect(result.current.loading).toBe(false))
    // The default MSW handler returns 2 images (mockImages in handlers.ts).
    expect(result.current.images).toHaveLength(2)
    expect(result.current.total).toBe(2)
  })

  it('records the loaded page via setPageByMode', async () => {
    const { filters, setPageByMode } = buildFilters()
    renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(setPageByMode).toHaveBeenCalled())
    // The updater is the prev=>{...prev, [mode]: page} form; verify by invoking it.
    const updater = setPageByMode.mock.calls[0][0]
    const next = updater({ infinite: 0, paged: 0 })
    expect(next.infinite).toBe(1)
  })

  it('filters images client-side via searchQuery on source_id', async () => {
    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(result.current.images).toHaveLength(2))

    act(() => result.current.setSearchQuery('100'))
    expect(result.current.displayImages).toHaveLength(1)
    expect(result.current.displayImages[0].source_id).toBe('100')
  })

  it('loadMore appends to images for infinite mode (hasMore=true)', async () => {
    let pageRequested: string | null = null
    server.use(
      http.get('/api/images', ({ request }) => {
        const url = new URL(request.url)
        pageRequested = url.searchParams.get('page')
        if (pageRequested === '2') {
          return HttpResponse.json({
            images: [{ ...baseImageList[0], id: 99, source_id: '999' }],
            total: 3,
            page: 2,
            per_page: 60,
            pages: 2,
          })
        }
        return HttpResponse.json({
          images: baseImageList,
          total: 3,
          page: 1,
          per_page: 60,
          pages: 2,
        })
      }),
    )

    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(result.current.images).toHaveLength(2))
    expect(result.current.hasMore).toBe(true)

    await act(async () => {
      result.current.loadMore()
    })
    await waitFor(() => expect(result.current.images).toHaveLength(3))
    expect(pageRequested).toBe('2')
    expect(result.current.images[2].id).toBe(99)
  })

  it('loadMore is a no-op when hasMore=false', async () => {
    server.use(
      http.get('/api/images', () =>
        HttpResponse.json({
          images: baseImageList,
          total: 2,
          page: 1,
          per_page: 60,
          pages: 1,
        }),
      ),
    )

    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(result.current.images).toHaveLength(2))
    expect(result.current.hasMore).toBe(false)

    await act(async () => {
      result.current.loadMore()
    })
    // Still just 2 — no second fetch happened.
    expect(result.current.images).toHaveLength(2)
  })

  it('resetAndReload clears state and resets the current mode page to 1', async () => {
    const { filters, setPageByMode } = buildFilters({
      pageByMode: { infinite: 5, paged: 3 },
    })
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(result.current.images).toHaveLength(2))

    setPageByMode.mockClear()
    act(() => {
      result.current.resetAndReload()
    })
    expect(result.current.images).toEqual([])
    expect(result.current.total).toBe(0)
    expect(result.current.pages).toBe(0)
    expect(setPageByMode).toHaveBeenCalled()
    const updater = setPageByMode.mock.calls[0][0]
    expect(updater({ infinite: 5, paged: 3 })).toEqual({ infinite: 1, paged: 3 })
  })

  it('clearListForModeSwitch wipes list without resetting page', async () => {
    const { filters, setPageByMode } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )
    await waitFor(() => expect(result.current.images).toHaveLength(2))

    setPageByMode.mockClear()
    act(() => {
      result.current.clearListForModeSwitch()
    })
    expect(result.current.images).toEqual([])
    expect(result.current.total).toBe(0)
    expect(setPageByMode).not.toHaveBeenCalled()
  })

  it('sets error message when /api/images fails', async () => {
    server.use(
      http.get('/api/images', () =>
        new HttpResponse('boom', { status: 500 }),
      ),
    )
    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'gallery', initialSearchQuery: '' }),
    )

    await waitFor(() => expect(result.current.error).not.toBeNull())
    expect(result.current.images).toEqual([])
  })

  it('uses initialSearchQuery for the first render', () => {
    const { filters } = buildFilters()
    const { result } = renderHook(() =>
      useGallery(filters, { view: 'novels', initialSearchQuery: 'preset' }),
    )
    expect(result.current.searchQuery).toBe('preset')
  })
})

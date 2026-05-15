import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fetchImages, fetchDates, fetchSources } from '../api'
import type { ImageItem, GalleryMode, MediaFilter, View } from '../types'

const GALLERY_PAGE_SIZE = 60

export interface UseGalleryFilters {
  selectedSource: string
  selectedDate: string
  selectedMedia: MediaFilter
  sort: string
  galleryMode: GalleryMode
  pageByMode: Record<GalleryMode, number>
  setPageByMode: React.Dispatch<React.SetStateAction<Record<GalleryMode, number>>>
}

export interface UseGalleryOptions {
  /** Current view; data effects only fire while view === 'gallery'. */
  view: View
  /** Initial search query (from persisted state). */
  initialSearchQuery: string
}

/**
 * Owns gallery-list data: list/totals/loading state, plus the loader
 * that fetches `/api/images` and the search-query filter applied client-side.
 *
 * Pulls filter values from `useGalleryFilters` via the `filters` arg so the
 * caller stays the single source of truth for filter writes — the hook only
 * needs `setPageByMode` to record which page just succeeded.
 */
export function useGallery(filters: UseGalleryFilters, opts: UseGalleryOptions) {
  const { selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, setPageByMode } = filters
  const { view, initialSearchQuery } = opts

  const [images, setImages] = useState<ImageItem[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({})
  const [dates, setDates] = useState<string[]>([])
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [errorKind, setErrorKind] = useState<'network' | 'empty' | null>(null)
  const [searchQuery, setSearchQuery] = useState(initialSearchQuery)

  const abortRef = useRef<AbortController | null>(null)
  const galleryFetchedRef = useRef(false)

  // Client-side search filtering — fuzzy on source_id and file_path
  const displayImages = useMemo(() => {
    if (!searchQuery.trim()) return images
    const q = searchQuery.trim().toLowerCase()
    return images.filter(img =>
      img.source_id.toLowerCase().includes(q) ||
      img.file_path.toLowerCase().includes(q)
    )
  }, [images, searchQuery])

  // One-time fetch of sources + dates metadata
  useEffect(() => {
    if (galleryFetchedRef.current) return
    galleryFetchedRef.current = true
    fetchSources()
      .then(r => {
        setSources(r.sources)
        if (r.counts) setSourceCounts(r.counts)
      })
      .catch(e => console.error('fetchSources failed:', e))
    fetchDates()
      .then(r => setDates(r.dates))
      .catch(e => console.error('fetchDates failed:', e))
  }, [])

  const loadImages = useCallback(async (targetPage: number, append = false) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    if (append) {
      setLoadingMore(true)
    } else {
      setLoading(true)
    }
    setError(null)
    setErrorKind(null)

    try {
      const data = await fetchImages({
        source: selectedSource || undefined,
        date: selectedDate || undefined,
        media: selectedMedia || undefined,
        sort,
        page: targetPage,
        per_page: GALLERY_PAGE_SIZE,
      }, controller.signal)

      if (controller.signal.aborted) return
      setImages(prev => (append ? [...prev, ...data.images] : data.images))
      setTotal(data.total)
      setPages(data.pages)
      setPageByMode(prev => ({ ...prev, [galleryMode]: targetPage }))
      if (!append && data.images.length === 0 && data.total === 0) {
        setErrorKind('empty')
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setError('图片加载失败了，刷新一下或者换个筛选再试试。')
      setErrorKind('network')
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [galleryMode, selectedSource, selectedDate, selectedMedia, sort, setPageByMode])

  // Reload when in the gallery view and the loader identity / mode changes
  useEffect(() => {
    if (view !== 'gallery') return
    loadImages(pageByMode[galleryMode], false)
    // pageByMode intentionally omitted — `loadImages` already closes over
    // the live page via `pageByMode[galleryMode]` and re-running on every
    // page write would loop with the setPageByMode call inside loadImages.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadImages, view, galleryMode])

  const currentPage = pageByMode[galleryMode]
  const hasMore = galleryMode === 'infinite' && currentPage < pages

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore) return
    loadImages(currentPage + 1, true)
  }, [hasMore, loadingMore, currentPage, loadImages])

  /**
   * Clear list state and bounce the current mode's page to 1, then scroll up.
   * Caller is responsible for kicking the actual reload by changing a filter
   * dependency that `loadImages` watches (or by calling `loadImages` directly).
   */
  const resetAndReload = useCallback(() => {
    setImages([])
    setTotal(0)
    setPages(0)
    setPageByMode(prev => ({ ...prev, [galleryMode]: 1 }))
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [galleryMode, setPageByMode])

  /**
   * Variant for gallery-mode switches: clear list state without resetting the
   * destination mode's page (the new mode keeps its own remembered page).
   */
  const clearListForModeSwitch = useCallback(() => {
    setImages([])
    setTotal(0)
    setPages(0)
  }, [])

  return {
    images,
    displayImages,
    sources,
    sourceCounts,
    dates,
    total,
    pages,
    loading,
    loadingMore,
    error,
    errorKind,
    currentPage,
    hasMore,
    loadImages,
    loadMore,
    resetAndReload,
    clearListForModeSwitch,
    searchQuery,
    setSearchQuery,
  }
}

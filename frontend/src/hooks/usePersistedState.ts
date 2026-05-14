import { useEffect, useRef, useMemo } from 'react'
import type { View, GalleryMode, MediaFilter, NovelItem } from '../types'

export type { GalleryMode, MediaFilter } from '../types'
export type { NovelItem } from '../types'

export interface PersistedState {
  view: View
  selectedSource: string
  selectedDate: string
  selectedMedia: MediaFilter
  sort: string
  galleryMode: GalleryMode
  pageByMode: Record<GalleryMode, number>
  galleryScrollY: number
  selectedNovelId: number | null
  novelSearch: string
  novelDate: string
  novelSort: string
  novelPage: number
  searchQuery: string
}

export interface NovelFilterState {
  search: string
  date: string
  sort: string
  page: number
}

const STORAGE_KEY = 'sieve-ui-state'

const VALID_VIEWS: View[] = ['gallery', 'novels', 'labeler', 'danbooru', 'stats']

const defaultState: PersistedState = {
  view: 'gallery',
  selectedSource: '',
  selectedDate: '',
  selectedMedia: '',
  sort: 'newest',
  galleryMode: 'infinite',
  pageByMode: { infinite: 1, paged: 1 },
  galleryScrollY: 0,
  selectedNovelId: null,
  novelSearch: '',
  novelDate: '',
  novelSort: 'newest',
  novelPage: 1,
  searchQuery: '',
}

function loadPersistedState(): PersistedState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return defaultState
    const parsed = JSON.parse(raw)
    if (parsed.view && !VALID_VIEWS.includes(parsed.view)) parsed.view = defaultState.view
    return { ...defaultState, ...parsed }
  } catch {
    return defaultState
  }
}

function persistState(state: PersistedState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch { /* ignore */ }
}

function buildPersistedState(
  view: View,
  selectedSource: string,
  selectedDate: string,
  selectedMedia: MediaFilter,
  sort: string,
  galleryMode: GalleryMode,
  pageByMode: Record<GalleryMode, number>,
  scrollY: number,
  selectedNovel: NovelItem | null,
  pendingNovelId: number | null,
  novelState: NovelFilterState,
  searchQuery: string,
): PersistedState {
  return {
    view,
    selectedSource,
    selectedDate,
    selectedMedia,
    sort,
    galleryMode,
    pageByMode,
    galleryScrollY: view === 'gallery' ? scrollY : 0,
    selectedNovelId: selectedNovel?.id ?? pendingNovelId ?? null,
    novelSearch: novelState.search,
    novelDate: novelState.date,
    novelSort: novelState.sort,
    novelPage: novelState.page,
    searchQuery,
  }
}

export function usePersistedState() {
  const initial = useMemo(loadPersistedState, [])

  const scrollYRef = useRef(initial.galleryScrollY)
  const persistTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const persist = (
    view: View,
    selectedSource: string,
    selectedDate: string,
    selectedMedia: MediaFilter,
    sort: string,
    galleryMode: GalleryMode,
    pageByMode: Record<GalleryMode, number>,
    selectedNovel: NovelItem | null,
    pendingNovelId: number | null,
    novelState: NovelFilterState,
    searchQuery: string,
  ) => {
    if (persistTimerRef.current !== null) clearTimeout(persistTimerRef.current)
    persistTimerRef.current = setTimeout(() => {
      persistState(buildPersistedState(
        view, selectedSource, selectedDate, selectedMedia, sort,
        galleryMode, pageByMode, scrollYRef.current,
        selectedNovel, pendingNovelId, novelState, searchQuery,
      ))
    }, 500)
  }

  const persistNow = (
    view: View,
    selectedSource: string,
    selectedDate: string,
    selectedMedia: MediaFilter,
    sort: string,
    galleryMode: GalleryMode,
    pageByMode: Record<GalleryMode, number>,
    selectedNovel: NovelItem | null,
    pendingNovelId: number | null,
    novelState: NovelFilterState,
    searchQuery: string,
  ) => {
    persistState(buildPersistedState(
      view, selectedSource, selectedDate, selectedMedia, sort,
      galleryMode, pageByMode, scrollYRef.current,
      selectedNovel, pendingNovelId, novelState, searchQuery,
    ))
  }

  // Track scroll position for gallery view
  useEffect(() => {
    const onScroll = () => { scrollYRef.current = window.scrollY }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return { initial, scrollYRef, persist, persistNow }
}

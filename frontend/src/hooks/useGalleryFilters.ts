import { useState, useCallback } from 'react'
import type { GalleryMode, MediaFilter, PersistedState } from './usePersistedState'

export { type PersistedState, type NovelFilterState } from './usePersistedState'

export interface GalleryFilterState {
  selectedSource: string
  selectedDate: string
  selectedMedia: MediaFilter
  sort: string
  galleryMode: GalleryMode
  pageByMode: Record<GalleryMode, number>
}

export function useGalleryFilters(initial: PersistedState) {
  const [selectedSource, setSelectedSource] = useState(initial.selectedSource)
  const [selectedDate, setSelectedDate] = useState(initial.selectedDate)
  const [selectedMedia, setSelectedMedia] = useState<MediaFilter>(initial.selectedMedia)
  const [sort, setSort] = useState(initial.sort)
  const [galleryMode, setGalleryMode] = useState<GalleryMode>(initial.galleryMode)
  const [pageByMode, setPageByMode] = useState<Record<GalleryMode, number>>(initial.pageByMode)

  const handleSourceChange = useCallback((s: string) => setSelectedSource(s), [])
  const handleDateChange = useCallback((d: string) => setSelectedDate(d), [])
  const handleMediaChange = useCallback((m: MediaFilter) => setSelectedMedia(m), [])
  const handleSortChange = useCallback((s: string) => setSort(s), [])

  const handleGalleryModeChange = useCallback((mode: GalleryMode) => {
    if (galleryMode === mode) return
    setGalleryMode(mode)
    setPageByMode(p => ({ ...p, [mode]: p[mode] || 1 }))
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [galleryMode])

  return {
    selectedSource, setSelectedSource,
    selectedDate, setSelectedDate,
    selectedMedia, setSelectedMedia,
    sort, setSort,
    galleryMode, setGalleryMode,
    pageByMode, setPageByMode,
    handleSourceChange,
    handleDateChange,
    handleMediaChange,
    handleSortChange,
    handleGalleryModeChange,
  }
}

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

  const resetGalleryAndReload = useCallback((patch?: Partial<{
    selectedSource: string
    selectedDate: string
    selectedMedia: MediaFilter
    sort: string
  }>) => {
    if (patch?.selectedSource !== undefined) setSelectedSource(patch.selectedSource)
    if (patch?.selectedDate !== undefined) setSelectedDate(patch.selectedDate)
    if (patch?.selectedMedia !== undefined) setSelectedMedia(patch.selectedMedia)
    if (patch?.sort !== undefined) setSort(patch.sort)
    setPageByMode(prev => ({ ...prev, [galleryMode]: 1 }))
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [galleryMode])

  const handleSourceChange = useCallback((s: string) => resetGalleryAndReload({ selectedSource: s }), [resetGalleryAndReload])
  const handleDateChange = useCallback((d: string) => resetGalleryAndReload({ selectedDate: d }), [resetGalleryAndReload])
  const handleMediaChange = useCallback((m: MediaFilter) => resetGalleryAndReload({ selectedMedia: m }), [resetGalleryAndReload])
  const handleSortChange = useCallback((s: string) => resetGalleryAndReload({ sort: s }), [resetGalleryAndReload])

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

import React, { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from 'react'
import Header from './components/Header'
import FilterBar from './components/FilterBar'
import ImageGrid from './components/ImageGrid'
import Lightbox from './components/Lightbox'
import Pagination from './components/Pagination'
import ScrollToTop from './components/ScrollToTop'
import EmptyState from './components/EmptyState'
import LoadMoreTrigger from './components/LoadMoreTrigger'
import KeyboardShortcuts from './components/KeyboardShortcuts'
import { fetchImages, fetchDates, fetchSources } from './api'
import type { ImageItem, NovelItem, View, GalleryMode, MediaFilter } from './types'

const StatsView = lazy(() => import('./components/StatsView'))
const NovelList = lazy(() => import('./components/NovelList'))
const NovelReader = lazy(() => import('./components/NovelReader'))
const Labeler = lazy(() => import('./components/Labeler'))
const DanbooruLabeler = lazy(() => import('./components/DanbooruLabeler'))

const GALLERY_PAGE_SIZE = 60
const STORAGE_KEY = 'sieve-ui-state'

type SortOrder = 'newest' | 'oldest'

interface PersistedState {
  view: View
  selectedSource: string
  selectedDate: string
  selectedMedia: MediaFilter
  sort: SortOrder | string
  galleryMode: GalleryMode
  pageByMode: Record<GalleryMode, number>
  galleryScrollY: number
  selectedNovelId: number | null
  novelSearch: string
  novelDate: string
  novelSort: string
  novelPage: number
}

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

interface NovelFilterState {
  search: string
  date: string
  sort: string
  page: number
}

function getCurrentPersistedState(
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
  }
}

const suspenseFallback = (
  <div className="flex h-64 items-center justify-center">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--spinner-base)] border-t-[var(--spinner-accent)]" role="status" aria-label="加载中" />
  </div>
)

export default function App() {
  const initial = useMemo(loadPersistedState, [])

  const [view, setView] = useState<View>(initial.view)
  const [images, setImages] = useState<ImageItem[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [sourceCounts, setSourceCounts] = useState<Record<string, number>>({})
  const [dates, setDates] = useState<string[]>([])
  const [selectedSource, setSelectedSource] = useState(initial.selectedSource)
  const [selectedDate, setSelectedDate] = useState(initial.selectedDate)
  const [selectedMedia, setSelectedMedia] = useState<MediaFilter>(initial.selectedMedia)
  const [sort, setSort] = useState(initial.sort)
  const [galleryMode, setGalleryMode] = useState<GalleryMode>(initial.galleryMode)
  const [pageByMode, setPageByMode] = useState<Record<GalleryMode, number>>(initial.pageByMode)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [lightboxImage, setLightboxImage] = useState<ImageItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedNovel, setSelectedNovel] = useState<NovelItem | null>(null)
  const pendingNovelId = initial.selectedNovelId
  const [filterExpanded, setFilterExpanded] = useState(false)
  const [viewFade, setViewFade] = useState(false)

  const [novelState, setNovelState] = useState<NovelFilterState>({
    search: initial.novelSearch,
    date: initial.novelDate,
    sort: initial.novelSort,
    page: initial.novelPage,
  })

  const currentPage = pageByMode[galleryMode]
  const hasMore = galleryMode === 'infinite' && currentPage < pages
  const scrollYRef = useRef(initial.galleryScrollY)
  const abortRef = useRef<AbortController | null>(null)
  const galleryFetchedRef = useRef(false)

  useEffect(() => {
    const onScroll = () => {
      if (view === 'gallery') scrollYRef.current = window.scrollY
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [view])

  useEffect(() => {
    const timeout = setTimeout(() => {
      persistState(getCurrentPersistedState(
        view, selectedSource, selectedDate, selectedMedia, sort,
        galleryMode, pageByMode, scrollYRef.current,
        selectedNovel, pendingNovelId, novelState,
      ))
    }, 500)
    return () => clearTimeout(timeout)
  }, [view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode,
      selectedNovel, pendingNovelId, novelState])

  useEffect(() => {
    const onBeforeUnload = () => {
      persistState(getCurrentPersistedState(
        view, selectedSource, selectedDate, selectedMedia, sort,
        galleryMode, pageByMode, scrollYRef.current,
        selectedNovel, pendingNovelId, novelState,
      ))
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode,
      selectedNovel, pendingNovelId, novelState])

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
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
      setError('图片加载失败了，刷新一下或者换个筛选再试试。')
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
        setLoadingMore(false)
      }
    }
  }, [galleryMode, selectedSource, selectedDate, selectedMedia, sort])

  useEffect(() => {
    if (view !== 'gallery') return
    loadImages(pageByMode[galleryMode], false)
  }, [loadImages, view, galleryMode])

  useEffect(() => {
    if (view !== 'gallery') return
    const savedY = scrollYRef.current
    if (savedY > 0 && pageByMode[galleryMode] >= 1) {
      const t = window.setTimeout(() => {
        window.scrollTo({ top: savedY, behavior: 'auto' })
      }, 50)
      return () => window.clearTimeout(t)
    }
  }, [pageByMode, galleryMode, view])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      const typing = tag === 'input' || tag === 'textarea' || target?.isContentEditable
      if (typing) return

      if (e.key === 'g' || e.key === 'G') { e.preventDefault(); setView('gallery') }
      else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); setView('novels') }
      else if (e.key === 'd' || e.key === 'D') { e.preventDefault(); setView('labeler') }
      else if (e.key === 'b' || e.key === 'B') { e.preventDefault(); setView('danbooru') }
      else if (e.key === 's' || e.key === 'S') { e.preventDefault(); setView('stats') }
      else if (e.key === 'f' || e.key === 'F') {
        if (view === 'gallery') setFilterExpanded(v => !v)
      } else if (e.key === 'j' || e.key === 'J') {
        if (view === 'gallery' && galleryMode === 'paged' && currentPage < pages) {
          loadImages(currentPage + 1)
        }
      } else if (e.key === 'k' || e.key === 'K') {
        if (view === 'gallery' && galleryMode === 'paged' && currentPage > 1) {
          loadImages(currentPage - 1)
        }
      } else if (e.key === 'Escape' && view === 'novels' && selectedNovel) {
        setSelectedNovel(null)
      } else if (e.key === '?') {
        window.dispatchEvent(new CustomEvent('booru-shortcuts-open'))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [currentPage, galleryMode, loadImages, pages, selectedNovel, view])

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
    setImages([])
    setTotal(0)
    setPages(0)
    setPageByMode(prev => ({ ...prev, [galleryMode]: 1 }))
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [galleryMode])

  const handleSourceChange = useCallback((s: string) => resetGalleryAndReload({ selectedSource: s }), [resetGalleryAndReload])
  const handleDateChange = useCallback((d: string) => resetGalleryAndReload({ selectedDate: d }), [resetGalleryAndReload])
  const handleMediaChange = useCallback((m: MediaFilter) => resetGalleryAndReload({ selectedMedia: m }), [resetGalleryAndReload])
  const handleSortChange = useCallback((s: string) => resetGalleryAndReload({ sort: s }), [resetGalleryAndReload])

  const handleViewChange = useCallback((v: View) => {
    if (view === 'gallery') {
      scrollYRef.current = window.scrollY
    }
    setViewFade(true)
    setTimeout(() => {
      setView(v)
      setViewFade(false)
    }, 150)
    if (v !== 'novels') setSelectedNovel(null)
    if (v !== 'gallery') setLightboxImage(null)
  }, [view])

  const handleGalleryModeChange = useCallback((mode: GalleryMode) => {
    if (galleryMode === mode) return
    setGalleryMode(mode)
    setImages([])
    setTotal(0)
    setPages(0)
    setPageByMode(p => ({ ...p, [mode]: p[mode] || 1 }))
    window.scrollTo({ top: 0, behavior: 'auto' })
  }, [galleryMode])

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore) return
    loadImages(currentPage + 1, true)
  }, [hasMore, loadingMore, currentPage, loadImages])

  const handleNovelStateChange = useCallback((patch: Partial<NovelFilterState>) => {
    setNovelState(prev => ({ ...prev, ...patch }))
  }, [])

  const closeLightbox = useCallback(() => setLightboxImage(null), [])
  const handlePageChange = useCallback((p: number) => loadImages(p), [loadImages])
  const handleNovelBack = useCallback(() => setSelectedNovel(null), [])

  return (
    <div className="archive-shell min-h-screen text-[var(--text)] transition-opacity duration-150" style={{ opacity: viewFade ? 0 : 1 }}>
      <Header view={view} onViewChange={handleViewChange} />

      {view === 'gallery' ? (
        <>
          <FilterBar
            sources={sources}
            sourceCounts={sourceCounts}
            dates={dates}
            selectedSource={selectedSource}
            selectedDate={selectedDate}
            selectedMedia={selectedMedia}
            sort={sort}
            onSourceChange={handleSourceChange}
            onDateChange={handleDateChange}
            onMediaChange={handleMediaChange}
            onSortChange={handleSortChange}
            total={total}
            mode={galleryMode}
            onModeChange={handleGalleryModeChange}
            expanded={filterExpanded}
            onExpandedChange={setFilterExpanded}
          />
          <main className="mx-auto max-w-[1920px] px-3 py-4 pb-20 md:px-6 md:py-6 md:pb-6">
            {error ? (
              <div className="px-4">
                <EmptyState
                  title="图片暂时没刷出来"
                  description={error}
                  action={(
                    <button
                      onClick={() => loadImages(currentPage || 1)}
                      className="rounded-2xl border border-[var(--line-strong)] bg-[var(--accent-soft)] px-4 py-2 text-sm text-[var(--text)] transition hover:bg-[rgba(214,165,93,0.2)]"
                    >
                      重新加载
                    </button>
                  )}
                />
              </div>
            ) : (
              <>
                <ImageGrid images={images} onImageClick={setLightboxImage} loading={loading} />
                {galleryMode === 'infinite' ? (
                  <LoadMoreTrigger
                    hasMore={hasMore}
                    loading={loadingMore}
                    onLoadMore={loadMore}
                    summary={`已加载 ${images.length} / ${total} 张`}
                    endText="全部加载完了"
                  />
                ) : (
                  <>
                    <Pagination page={currentPage} pages={pages} onPageChange={handlePageChange} />
                    <LoadMoreTrigger
                      hasMore={false}
                      summary={`当前分页模式 · 第 ${currentPage} / ${pages || 1} 页`}
                      endText="可用 J / K 快捷翻页"
                    />
                  </>
                )}
              </>
            )}
          </main>
          <Lightbox
            image={lightboxImage}
            images={images}
            onClose={closeLightbox}
            onNavigate={setLightboxImage}
          />
        </>
      ) : (
        <>
          {view === 'novels' && (
            <main>
              <Suspense fallback={suspenseFallback}>
                {selectedNovel ? (
                  <NovelReader novel={selectedNovel} onBack={handleNovelBack} />
                ) : (
                  <NovelList
                    onNovelSelect={setSelectedNovel}
                    initialNovelId={pendingNovelId}
                    initialSearch={novelState.search}
                    initialDate={novelState.date}
                    initialSort={novelState.sort}
                    initialPage={novelState.page}
                    onStateChange={handleNovelStateChange}
                  />
                )}
              </Suspense>
            </main>
          )}
          {view === 'labeler' && (
            <main>
              <Suspense fallback={suspenseFallback}>
                <Labeler />
              </Suspense>
            </main>
          )}
          {view === 'danbooru' && (
            <main>
              <Suspense fallback={suspenseFallback}>
                <DanbooruLabeler />
              </Suspense>
            </main>
          )}
          {view === 'stats' && (
            <main>
              <Suspense fallback={suspenseFallback}>
                <StatsView />
              </Suspense>
            </main>
          )}
        </>
      )}

      <ScrollToTop />
      <KeyboardShortcuts />

      <nav aria-label="移动端导航" className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--line)] bg-[rgba(10,8,7,0.88)] backdrop-blur-md md:hidden safe-bottom">
        <div className="flex items-stretch">
          <MobileNavButton active={view === 'gallery'} label="图库" onClick={() => handleViewChange('gallery')}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>
          </MobileNavButton>
          <MobileNavButton active={view === 'novels'} label="小说" onClick={() => handleViewChange('novels')}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" /><path d="M8 7h8M8 11h6" /></svg>
          </MobileNavButton>
          <MobileNavButton active={view === 'labeler'} label="标注" onClick={() => handleViewChange('labeler')}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></svg>
          </MobileNavButton>
          <MobileNavButton active={view === 'danbooru'} label="Danbooru" onClick={() => handleViewChange('danbooru')}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" /><path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12" /></svg>
          </MobileNavButton>
          <MobileNavButton active={view === 'stats'} label="统计" onClick={() => handleViewChange('stats')}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 20V10M12 20V4M6 20v-6" /></svg>
          </MobileNavButton>
        </div>
      </nav>
    </div>
  )
}

const MobileNavButton = React.memo(function MobileNavBtn({ active, label, children, onClick }: {
  active: boolean; label: string; children: React.ReactNode; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={[
        'flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs transition-colors',
        active ? 'text-[var(--text)]' : 'text-[var(--muted)]',
      ].join(' ')}
    >
      <span className="text-lg" aria-hidden="true">{children}</span>
      <span>{label}</span>
    </button>
  )
})

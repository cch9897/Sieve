import { useState, useEffect, useCallback, useMemo } from 'react'
import Header from './components/Header'
import FilterBar from './components/FilterBar'
import ImageGrid from './components/ImageGrid'
import Lightbox from './components/Lightbox'
import Pagination from './components/Pagination'
import StatsView from './components/StatsView'
import NovelList from './components/NovelList'
import NovelReader from './components/NovelReader'
import ScrollToTop from './components/ScrollToTop'
import EmptyState from './components/EmptyState'
import LoadMoreTrigger from './components/LoadMoreTrigger'
import KeyboardShortcuts from './components/KeyboardShortcuts'
import Labeler from './components/Labeler'
import DanbooruLabeler from './components/DanbooruLabeler'
import { fetchImages, fetchDates, fetchSources } from './api'
import type { ImageItem, NovelItem } from './types'

const GALLERY_PAGE_SIZE = 60
const STORAGE_KEY = 'sieve-ui-state'

type View = 'gallery' | 'novels' | 'labeler' | 'danbooru' | 'stats'
type GalleryMode = 'infinite' | 'paged'
type MediaFilter = '' | 'image' | 'video'

interface PersistedState {
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
}

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
    return { ...defaultState, ...JSON.parse(raw) }
  } catch {
    return defaultState
  }
}

function persistState(state: Partial<PersistedState>) {
  try {
    const current = loadPersistedState()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...current, ...state }))
  } catch { /* ignore */ }
}

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
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [lightboxImage, setLightboxImage] = useState<ImageItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedNovel, setSelectedNovel] = useState<NovelItem | null>(null)
  const [pendingNovelId] = useState<number | null>(initial.selectedNovelId)
  const [filterExpanded, setFilterExpanded] = useState(false)

  // Novel state (persisted via callbacks)
  const [novelState, setNovelState] = useState({
    search: initial.novelSearch,
    date: initial.novelDate,
    sort: initial.novelSort,
    page: initial.novelPage,
  })

  const currentPage = pageByMode[galleryMode]
  const hasMore = galleryMode === 'infinite' && currentPage < pages

  // Persist all state changes
  useEffect(() => {
    persistState({
      view,
      selectedSource,
      selectedDate,
      selectedMedia,
      sort,
      galleryMode,
      pageByMode,
      galleryScrollY: view === 'gallery' ? window.scrollY : initial.galleryScrollY,
      selectedNovelId: selectedNovel?.id ?? pendingNovelId ?? null,
      novelSearch: novelState.search,
      novelDate: novelState.date,
      novelSort: novelState.sort,
      novelPage: novelState.page,
    })
  }, [view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode,
      selectedNovel, pendingNovelId, novelState, initial.galleryScrollY])

  // Scroll persistence for gallery
  useEffect(() => {
    const onScroll = () => {
      if (view === 'gallery') {
        persistState({ galleryScrollY: window.scrollY })
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [view])

  useEffect(() => {
    fetchSources()
      .then(r => {
        setSources(r.sources)
        if (r.counts) setSourceCounts(r.counts)
      })
      .catch(() => {})
    fetchDates()
      .then(r => setDates(r.dates))
      .catch(() => {})
  }, [])

  const loadImages = useCallback(async (targetPage: number, append = false) => {
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
      })

      setImages(prev => (append ? [...prev, ...data.images] : data.images))
      setTotal(data.total)
      setPages(data.pages)
      setPageByMode(prev => ({ ...prev, [galleryMode]: targetPage }))
    } catch {
      setError('图片加载失败了，刷新一下或者换个筛选再试试。')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [galleryMode, selectedSource, selectedDate, selectedMedia, sort])

  useEffect(() => {
    if (view !== 'gallery') return
    loadImages(pageByMode[galleryMode], false)
  }, [loadImages, view, galleryMode])

  // Restore scroll position on gallery mount
  useEffect(() => {
    if (view !== 'gallery') return
    if (initial.galleryScrollY > 0 && pageByMode[galleryMode] >= 1) {
      const t = window.setTimeout(() => {
        window.scrollTo({ top: initial.galleryScrollY, behavior: 'auto' })
      }, 50)
      return () => window.clearTimeout(t)
    }
  }, [initial.galleryScrollY, pageByMode, galleryMode, view])

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      const typing = tag === 'input' || tag === 'textarea' || target?.isContentEditable
      if (typing) return

      if (e.key === 'g' || e.key === 'G') setView('gallery')
      else if (e.key === 'n' || e.key === 'N') setView('novels')
      else if (e.key === 'd' || e.key === 'D') setView('labeler')
      else if (e.key === 'b' || e.key === 'B') setView('danbooru')
      else if (e.key === 's' || e.key === 'S') setView('stats')
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

  const resetGalleryAndReload = (patch?: Partial<{
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
    setPageByMode(prev => ({ ...prev, [galleryMode]: 1 }))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const handleSourceChange = (s: string) => resetGalleryAndReload({ selectedSource: s })
  const handleDateChange = (d: string) => resetGalleryAndReload({ selectedDate: d })
  const handleMediaChange = (m: MediaFilter) => resetGalleryAndReload({ selectedMedia: m })
  const handleSortChange = (s: string) => resetGalleryAndReload({ sort: s })

  const handleViewChange = (v: View) => {
    if (view === 'gallery') {
      persistState({ galleryScrollY: window.scrollY })
    }
    setView(v)
    if (v !== 'novels') setSelectedNovel(null)
    if (v !== 'gallery') setLightboxImage(null)
  }

  const handleGalleryModeChange = (mode: GalleryMode) => {
    if (mode === galleryMode) return
    setGalleryMode(mode)
    setImages([])
    setPageByMode(prev => ({ ...prev, [mode]: prev[mode] || 1 }))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const loadMore = () => {
    if (!hasMore || loadingMore) return
    loadImages(currentPage + 1, true)
  }

  const handleNovelStateChange = useCallback((patch: Partial<typeof novelState>) => {
    setNovelState(prev => ({ ...prev, ...patch }))
  }, [])

  return (
    <div className="min-h-screen bg-dark-950 bg-[radial-gradient(circle_at_top,_rgba(96,165,250,0.08),_transparent_28%),radial-gradient(circle_at_80%_20%,_rgba(244,114,182,0.08),_transparent_22%)] text-dark-100">
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
          <main className="mx-auto max-w-[1920px] py-4">
            {error ? (
              <div className="px-4">
                <EmptyState
                  title="图片暂时没刷出来"
                  description={error}
                  action={(
                    <button
                      onClick={() => loadImages(currentPage || 1)}
                      className="rounded-xl bg-dark-700 px-4 py-2 text-sm text-dark-100 transition-colors hover:bg-dark-600"
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
                    <Pagination page={currentPage} pages={pages} onPageChange={(p) => loadImages(p)} />
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
            onClose={() => setLightboxImage(null)}
            onNavigate={setLightboxImage}
          />
        </>
      ) : view === 'novels' ? (
        selectedNovel ? (
          <NovelReader novel={selectedNovel} onBack={() => setSelectedNovel(null)} />
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
        )
      ) : view === 'labeler' ? (
        <Labeler />
      ) : view === 'danbooru' ? (
        <DanbooruLabeler />
      ) : (
        <StatsView />
      )}

      <ScrollToTop />
      <KeyboardShortcuts />

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-dark-700/50 bg-dark-950/90 backdrop-blur-xl md:hidden safe-bottom">
        <div className="flex items-stretch">
          <MobileNavButton active={view === 'gallery'} label="图库" icon="🖼" onClick={() => handleViewChange('gallery')} />
          <MobileNavButton active={view === 'novels'} label="小说" icon="📖" onClick={() => handleViewChange('novels')} />
          <MobileNavButton active={view === 'labeler'} label="标注(新)" icon="🎯" onClick={() => handleViewChange('labeler')} />
          <MobileNavButton active={view === 'danbooru'} label="Danbooru" icon="📦" onClick={() => handleViewChange('danbooru')} />
          <MobileNavButton active={view === 'stats'} label="统计" icon="📊" onClick={() => handleViewChange('stats')} />
        </div>
      </nav>
    </div>
  )
}

function MobileNavButton({ active, label, icon, onClick }: {
  active: boolean; label: string; icon: string; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs transition-colors',
        active ? 'text-blue-300' : 'text-dark-500',
      ].join(' ')}
    >
      <span className="text-lg">{icon}</span>
      <span>{label}</span>
    </button>
  )
}

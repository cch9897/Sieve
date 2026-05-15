import React, { useState, useEffect, useCallback, lazy, Suspense } from 'react'
import { flushSync } from 'react-dom'
import Header from './components/Header'
import FilterBar from './components/FilterBar'
import ImageGrid from './components/ImageGrid'
import Lightbox from './components/Lightbox'
import Pagination from './components/Pagination'
import ScrollToTop from './components/ScrollToTop'
import EmptyState from './components/EmptyState'
import LoadMoreTrigger from './components/LoadMoreTrigger'
import KeyboardShortcuts from './components/KeyboardShortcuts'
import { usePersistedState } from './hooks/usePersistedState'
import { useGalleryFilters } from './hooks/useGalleryFilters'
import { useNovelFilters } from './hooks/useNovelFilters'
import { useGallery } from './hooks/useGallery'
import type { ImageItem, NovelItem, View, GalleryMode, MediaFilter } from './types'

const StatsView = lazy(() => import('./components/StatsView'))
const NovelList = lazy(() => import('./components/NovelList'))
const NovelReader = lazy(() => import('./components/NovelReader'))
const Labeler = lazy(() => import('./components/Labeler'))
const DanbooruLabeler = lazy(() => import('./components/DanbooruLabeler'))

const HASH_VIEWS: View[] = ['gallery', 'novels', 'labeler', 'danbooru', 'stats']

function parseHashView(hash: string): View | null {
  const v = hash.replace(/^#/, '') as View
  return HASH_VIEWS.includes(v) ? v : null
}

const suspenseFallback = (
  <div className="flex h-64 items-center justify-center">
    <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--spinner-base)] border-t-[var(--spinner-accent)]" role="status" aria-label="加载中" />
  </div>
)

export default function App() {
  const { initial, scrollYRef, persist, persistNow } = usePersistedState()
  const {
    selectedSource, selectedDate, selectedMedia, sort,
    galleryMode, pageByMode, setPageByMode,
    handleSourceChange, handleDateChange, handleMediaChange,
    handleSortChange, handleGalleryModeChange,
  } = useGalleryFilters(initial)
  const { novelState, handleNovelStateChange } = useNovelFilters(initial)

  const [view, setView] = useState<View>(() => {
    if (typeof window === 'undefined') return initial.view
    return parseHashView(window.location.hash) ?? initial.view
  })
  const [lightboxImage, setLightboxImage] = useState<ImageItem | null>(null)
  const [selectedNovel, setSelectedNovel] = useState<NovelItem | null>(null)
  const pendingNovelId = initial.selectedNovelId
  const [filterExpanded, setFilterExpanded] = useState(false)

  // Hooks must run unconditionally; useGallery's data-fetch effect is gated on view==='gallery'.
  const gallery = useGallery(
    { selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, setPageByMode },
    { view, initialSearchQuery: initial.searchQuery },
  )
  const {
    images, displayImages, sources, sourceCounts, dates, total, pages,
    loading, loadingMore, error, errorKind, currentPage, hasMore,
    loadImages, loadMore, resetAndReload, clearListForModeSwitch,
    searchQuery, setSearchQuery,
  } = gallery

  const handleSearchChange = useCallback((q: string) => {
    setSearchQuery(q)
  }, [setSearchQuery])

  // Persist state to localStorage on changes
  useEffect(() => {
    persist(view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, selectedNovel, pendingNovelId, novelState, searchQuery)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, selectedNovel, pendingNovelId, novelState, searchQuery, persist])

  // Persist on unload
  useEffect(() => {
    const onBeforeUnload = () => {
      persistNow(view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, selectedNovel, pendingNovelId, novelState, searchQuery)
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, selectedSource, selectedDate, selectedMedia, sort, galleryMode, pageByMode, selectedNovel, pendingNovelId, novelState, searchQuery, persistNow])

  // Restore scroll position after a fresh gallery list lands.
  useEffect(() => {
    if (view !== 'gallery') return
    const savedY = scrollYRef.current
    if (savedY > 0 && pageByMode[galleryMode] >= 1) {
      const t = window.setTimeout(() => {
        window.scrollTo({ top: savedY, behavior: 'auto' })
      }, 50)
      return () => window.clearTimeout(t)
    }
  }, [pageByMode, galleryMode, view, scrollYRef])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      const typing = tag === 'input' || tag === 'textarea' || target?.isContentEditable
      if (typing) return

      if (e.key === 'g' || e.key === 'G') { e.preventDefault(); handleViewChange('gallery') }
      else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); handleViewChange('novels') }
      else if (e.key === 'd' || e.key === 'D') { e.preventDefault(); handleViewChange('labeler') }
      else if (e.key === 'b' || e.key === 'B') { e.preventDefault(); handleViewChange('danbooru') }
      else if (e.key === 's' || e.key === 'S') { e.preventDefault(); handleViewChange('stats') }
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


  const applyView = useCallback((v: View) => {
    if (view === 'gallery') {
      scrollYRef.current = window.scrollY
    }
    if ('startViewTransition' in document) {
      document.startViewTransition(() => {
        flushSync(() => {
          setView(v)
          if (v !== 'novels') setSelectedNovel(null)
          if (v !== 'gallery') setLightboxImage(null)
        })
      })
    } else {
      setView(v)
      if (v !== 'novels') setSelectedNovel(null)
      if (v !== 'gallery') setLightboxImage(null)
    }
  }, [view, scrollYRef])

  const handleViewChange = useCallback((v: View) => {
    if (v === view) return
    applyView(v)
    try { window.history.pushState({ view: v }, '', '#' + v) } catch { /* ignore */ }
  }, [applyView, view])

  useEffect(() => {
    try {
      const hashView = parseHashView(window.location.hash)
      if (hashView) {
        window.history.replaceState({ view: hashView }, '', '#' + hashView)
      } else {
        window.history.replaceState({ view }, '', '#' + view)
      }
    } catch { /* ignore */ }
  // Run once on mount — we want a one-time URL/state sync.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const onPopState = (e: PopStateEvent) => {
      const stateView = (e.state && typeof e.state === 'object' && 'view' in e.state)
        ? (e.state as { view?: unknown }).view
        : undefined
      const next = (typeof stateView === 'string' && HASH_VIEWS.includes(stateView as View))
        ? (stateView as View)
        : parseHashView(window.location.hash)
      if (next && next !== view) applyView(next)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [applyView, view])

  // Filter change handlers — wrap each to also clear the gallery list and bounce to page 1.
  const handleSourceChangeWrapped = useCallback((s: string) => { handleSourceChange(s); resetAndReload() }, [handleSourceChange, resetAndReload])
  const handleDateChangeWrapped = useCallback((d: string) => { handleDateChange(d); resetAndReload() }, [handleDateChange, resetAndReload])
  const handleMediaChangeWrapped = useCallback((m: string) => { handleMediaChange(m as '' | 'image' | 'video'); resetAndReload() }, [handleMediaChange, resetAndReload])
  const handleSortChangeWrapped = useCallback((s: string) => { handleSortChange(s); resetAndReload() }, [handleSortChange, resetAndReload])

  const handleGalleryModeChangeWrapped = useCallback((mode: GalleryMode) => {
    handleGalleryModeChange(mode)
    clearListForModeSwitch()
  }, [handleGalleryModeChange, clearListForModeSwitch])

  const clearAllFilters = useCallback(() => {
    handleSourceChange('')
    handleDateChange('')
    handleMediaChange('' as MediaFilter)
    handleSortChange('newest')
    setSearchQuery('')
    resetAndReload()
  }, [handleSourceChange, handleDateChange, handleMediaChange, handleSortChange, setSearchQuery, resetAndReload])

  const closeLightbox = useCallback(() => setLightboxImage(null), [])
  const handlePageChange = useCallback((p: number) => loadImages(p), [loadImages])
  const handleNovelBack = useCallback(() => setSelectedNovel(null), [])

  return (
    <div className="archive-shell min-h-screen text-[var(--text)]">

      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:rounded-2xl focus:border focus:border-[var(--line-strong)] focus:bg-[var(--panel)] focus:px-4 focus:py-2 focus:text-sm focus:text-[var(--text)]"
      >
        跳到内容
      </a>
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
            onSourceChange={handleSourceChangeWrapped}
            onDateChange={handleDateChangeWrapped}
            onMediaChange={handleMediaChangeWrapped}
            onSortChange={handleSortChangeWrapped}
            total={total}
            mode={galleryMode}
            onModeChange={handleGalleryModeChangeWrapped}
            expanded={filterExpanded}
            onExpandedChange={setFilterExpanded}
            searchQuery={searchQuery}
            onSearchChange={handleSearchChange}
          />
          <main id="main-content" className="mx-auto max-w-[1920px] px-3 py-4 pb-20 md:px-6 md:py-6 md:pb-6">
            {errorKind === 'network' ? (
              <div className="px-4">
                <EmptyState
                  title="出错了，请重试"
                  description={error ?? undefined}
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
            ) : errorKind === 'empty' ? (
              <div className="px-4">
                <EmptyState
                  title="没找到符合条件的图片"
                  description="试着换一个来源、日期或清空当前筛选条件。"
                  action={(
                    <button
                      onClick={clearAllFilters}
                      className="rounded-2xl border border-[var(--line-strong)] bg-[var(--accent-soft)] px-4 py-2 text-sm text-[var(--text)] transition hover:bg-[rgba(214,165,93,0.2)]"
                    >
                      清空筛选
                    </button>
                  )}
                />
              </div>
            ) : (
              <>
                <ImageGrid images={displayImages} onImageClick={setLightboxImage} loading={loading} onClearFilters={clearAllFilters} />
                {galleryMode === 'infinite' ? (
                  <LoadMoreTrigger
                    hasMore={hasMore}
                    loading={loadingMore}
                    onLoadMore={loadMore}
                    summary={`已加载 ${images.length} / ${total} 张${searchQuery ? ` · 匹配 ${displayImages.length} 项` : ''}`}
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
            images={displayImages}
            onClose={closeLightbox}
            onNavigate={setLightboxImage}
          />
        </>
      ) : (
        <>
          {view === 'novels' && (
            <main id="main-content">
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
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('booru-shortcuts-open'))}
            aria-label="快捷键帮助"
            className="flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs text-[var(--muted)] transition-colors"
          >
            <span className="text-lg" aria-hidden="true">?</span>
            <span>快捷键</span>
          </button>
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
        'relative flex flex-1 flex-col items-center gap-0.5 py-2.5 text-xs transition-colors',
        active ? 'text-[var(--text)]' : 'text-[var(--muted)]',
      ].join(' ')}
    >
      <span className="text-lg relative" aria-hidden="true">
        {children}
        {active && <span className="absolute -top-0.5 -right-1.5 h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />}
      </span>
      <span>{label}</span>
    </button>
  )
})

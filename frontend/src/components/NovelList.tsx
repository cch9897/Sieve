import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchNovels, fetchNovelDates } from '../api'
import Pagination from './Pagination'
import type { NovelItem } from '../types'
import EmptyState from './EmptyState'
import { formatNum } from '../utils'
import FilterChip from './FilterChip'

interface NovelListProps {
  onNovelSelect: (novel: NovelItem) => void
  initialNovelId?: number | null
  initialSearch?: string
  initialDate?: string
  initialSort?: string
  initialPage?: number
  onStateChange?: (state: { search?: string; date?: string; sort?: string; page?: number }) => void
}

export default function NovelList({
  onNovelSelect, initialNovelId,
  initialSearch = '', initialDate = '', initialSort = 'newest', initialPage = 1,
  onStateChange,
}: NovelListProps) {
  const [novels, setNovels] = useState<NovelItem[]>([])
  const [dates, setDates] = useState<string[]>([])
  const [selectedDate, setSelectedDate] = useState(initialDate)
  const [sort, setSort] = useState(initialSort)
  const [search, setSearch] = useState(initialSearch)
  const [searchInput, setSearchInput] = useState(initialSearch)
  const [page, setPage] = useState(initialPage)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchNovelDates().then(r => setDates(r.dates))
  }, [])

  const onStateChangeRef = useRef(onStateChange)
  onStateChangeRef.current = onStateChange

  useEffect(() => {
    onStateChangeRef.current?.({ search, date: selectedDate, sort, page })
  }, [search, selectedDate, sort, page])

  const loadNovels = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchNovels({
        date: selectedDate || undefined,
        sort,
        search: search || undefined,
        page,
        per_page: 30,
      })
      setNovels(data.novels)
      setTotal(data.total)
      setPages(data.pages)
    } finally {
      setLoading(false)
    }
  }, [selectedDate, sort, search, page])

  useEffect(() => {
    loadNovels()
  }, [loadNovels])

  const hasRestoredRef = useRef(false)
  useEffect(() => {
    if (hasRestoredRef.current || !initialNovelId || novels.length === 0) return
    const found = novels.find(n => n.id === initialNovelId)
    if (found) {
      hasRestoredRef.current = true
      onNovelSelect(found)
    }
  }, [initialNovelId, novels, onNovelSelect])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setSearch(searchInput.trim())
    setPage(1)
  }

  const clearSearch = () => {
    setSearchInput('')
    setSearch('')
    setPage(1)
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 pb-24 md:pb-6">
      <div className="mb-6 editorial-panel p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-[var(--text)]">小说库</h2>
            <p className="text-sm text-[var(--muted)]">支持按标题、作者、日期和热度快速挑文。</p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
            <span className="rounded-full border border-[var(--line)] bg-[var(--panel-strong)] px-2.5 py-1">共 {total} 篇</span>
            {search && <FilterChip label="搜索" value={search} onDismiss={clearSearch} />}
            {selectedDate && <FilterChip label="日期" value={selectedDate} onDismiss={() => { setSelectedDate(''); setPage(1) }} />}
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="搜标题、作者、系列……"
              aria-label="搜索小说"
              className="w-full rounded-ed-sm border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--input-focus)] placeholder:text-[var(--muted)]/50"
            />
            <button
              type="submit"
              className="rounded-ed-sm bg-[rgba(255,255,255,0.06)] px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-[rgba(255,255,255,0.1)]"
            >
              搜索
            </button>
          </form>

          <select
            value={selectedDate}
            onChange={e => { setSelectedDate(e.target.value); setPage(1) }}
            className="rounded-ed-sm border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--input-focus)]"
          >
            <option value="">全部日期</option>
            {dates.map(d => (<option key={d} value={d}>{d}</option>))}
          </select>

          <select
            value={sort}
            onChange={e => { setSort(e.target.value); setPage(1) }}
            className="rounded-ed-sm border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--input-focus)]"
          >
            <option value="newest">最新</option>
            <option value="oldest">最早</option>
            <option value="bookmarks">收藏数</option>
            <option value="views">阅读量</option>
            <option value="length">字数</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="grid gap-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-ed-md border border-[var(--line)]" />
          ))}
        </div>
      ) : novels.length === 0 ? (
        <EmptyState
          title="没找到匹配的小说"
          description="可以换个关键词，或者去掉日期和排序限制再看看。"
        />
      ) : (
        <div className="grid gap-3">
          {novels.map(novel => (
            <article
              key={novel.id}
              onClick={() => onNovelSelect(novel)}
              onKeyDown={e => { if (e.key === 'Enter') onNovelSelect(novel) }}
              tabIndex={0}
              role="button"
              aria-label={`打开小说：${novel.title}`}
              className="group cursor-pointer editorial-panel p-4 transition-transform-colors duration-200 hover:-translate-y-0.5 hover:border-[var(--line-strong)] active:scale-[0.995]"
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {novel.r18 && <span className="rounded-full bg-[var(--danger-soft)] px-2 py-0.5 text-[11px] text-[var(--danger)]">R18</span>}
                    {novel.series_title && <span className="rounded-full bg-[rgba(255,255,255,0.05)] px-2 py-0.5 text-[11px] text-[var(--muted)]">系列</span>}
                  </div>

                  <h3 className="mt-2 text-base font-medium leading-relaxed text-[var(--text)] group-hover:text-[var(--text)] line-clamp-2">
                    {novel.title}
                  </h3>

                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-[var(--muted)]">
                    <span>✏️ {novel.author || '未知作者'}</span>
                    {novel.series_title && (
                      <span className="truncate text-[var(--muted)]">📚 {novel.series_title}</span>
                    )}
                    {novel.date && <span className="text-[var(--muted)]">🗓 {novel.date}</span>}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {novel.tags.slice(0, 6).map((tag, i) => (
                      <span key={i} className="rounded-full border border-[var(--line)] bg-[rgba(0,0,0,0.16)] px-2 py-0.5 text-[11px] text-[var(--muted)]">
                        {tag}
                      </span>
                    ))}
                    {novel.tags.length > 6 && (
                      <span className="rounded-full border border-[var(--line)] bg-[rgba(0,0,0,0.16)] px-2 py-0.5 text-[11px] text-[var(--muted)]">+{novel.tags.length - 6}</span>
                    )}
                  </div>
                </div>

                <div className="grid shrink-0 grid-cols-3 gap-2 md:min-w-56">
                  <MetricCard label="字数" value={formatNum(novel.text_length)} />
                  <MetricCard label="收藏" value={formatNum(novel.total_bookmarks)} />
                  <MetricCard label="阅读" value={formatNum(novel.total_view)} />
                </div>
              </div>
            </article>
          ))}
        </div>
      )}

      <Pagination page={page} pages={pages} onPageChange={setPage} />
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-ed-md border border-[var(--line)] bg-[rgba(0,0,0,0.16)] px-3 py-2 text-center">
      <div className="text-sm font-medium text-[var(--text)]">{value}</div>
      <div className="mt-1 text-[11px] text-[var(--muted)]">{label}</div>
    </div>
  )
}

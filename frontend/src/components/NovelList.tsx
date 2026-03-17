import { useState, useEffect, useCallback } from 'react'
import { fetchNovels, fetchNovelDates } from '../api'
import Pagination from './Pagination'
import type { NovelItem } from '../types'
import EmptyState from './EmptyState'

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

  // Report state changes to parent for persistence
  useEffect(() => {
    onStateChange?.({ search, date: selectedDate, sort, page })
  }, [search, selectedDate, sort, page, onStateChange])

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

  useEffect(() => {
    if (!initialNovelId || novels.length === 0) return
    const found = novels.find(n => n.id === initialNovelId)
    if (found) onNovelSelect(found)
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

  const formatNum = (n: number) => {
    if (n >= 10000) return (n / 10000).toFixed(1) + '万'
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
    return String(n)
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 pb-24 md:pb-6">
      <div className="mb-6 rounded-2xl border border-dark-700/60 bg-dark-900/70 p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold text-dark-100">小说库</h2>
            <p className="text-sm text-dark-500">支持按标题、作者、日期和热度快速挑文。</p>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-dark-500">
            <span className="rounded-full border border-dark-800 bg-dark-950 px-2.5 py-1">共 {total} 篇</span>
            {search && (
              <button
                onClick={clearSearch}
                className="inline-flex items-center gap-1 rounded-full border border-dark-800 bg-dark-950 px-2.5 py-1 transition-colors hover:border-dark-600 hover:text-dark-300"
              >
                搜索：{search} ✕
              </button>
            )}
            {selectedDate && (
              <button
                onClick={() => { setSelectedDate(''); setPage(1) }}
                className="inline-flex items-center gap-1 rounded-full border border-dark-800 bg-dark-950 px-2.5 py-1 transition-colors hover:border-dark-600 hover:text-dark-300"
              >
                {selectedDate} ✕
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_180px_180px]">
          <form onSubmit={handleSearch} className="flex gap-2">
            <input
              type="text"
              value={searchInput}
              onChange={e => setSearchInput(e.target.value)}
              placeholder="搜标题、作者、系列……"
              className="w-full rounded-xl border border-dark-700 bg-dark-950 px-3 py-2 text-sm text-dark-100 outline-none transition-colors focus:border-dark-500 placeholder:text-dark-600"
            />
            <button
              type="submit"
              className="rounded-xl bg-dark-700 px-4 py-2 text-sm text-dark-100 transition-colors hover:bg-dark-600"
            >
              搜索
            </button>
          </form>

          <select
            value={selectedDate}
            onChange={e => { setSelectedDate(e.target.value); setPage(1) }}
            className="rounded-xl border border-dark-700 bg-dark-950 px-3 py-2 text-sm text-dark-100 outline-none transition-colors focus:border-dark-500"
          >
            <option value="">全部日期</option>
            {dates.map(d => (<option key={d} value={d}>{d}</option>))}
          </select>

          <select
            value={sort}
            onChange={e => { setSort(e.target.value); setPage(1) }}
            className="rounded-xl border border-dark-700 bg-dark-950 px-3 py-2 text-sm text-dark-100 outline-none transition-colors focus:border-dark-500"
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
            <div key={i} className="h-32 animate-pulse rounded-2xl border border-dark-700/50 bg-dark-900" />
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
              className="group cursor-pointer rounded-2xl border border-dark-700/50 bg-dark-900/80 p-4 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-dark-500/60 hover:bg-dark-900 active:scale-[0.995]"
            >
              <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    {novel.r18 && <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[11px] text-rose-200">R18</span>}
                    {novel.series_title && <span className="rounded-full bg-dark-800 px-2 py-0.5 text-[11px] text-dark-400">系列</span>}
                  </div>

                  <h3 className="mt-2 text-base font-medium leading-relaxed text-dark-100 group-hover:text-white line-clamp-2">
                    {novel.title}
                  </h3>

                  <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-dark-400">
                    <span>✏️ {novel.author || '未知作者'}</span>
                    {novel.series_title && (
                      <span className="truncate text-dark-500">📚 {novel.series_title}</span>
                    )}
                    {novel.date && <span className="text-dark-500">🗓 {novel.date}</span>}
                  </div>

                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {novel.tags.slice(0, 6).map((tag, i) => (
                      <span key={i} className="rounded-full border border-dark-700/70 bg-dark-950 px-2 py-0.5 text-[11px] text-dark-400">
                        {tag}
                      </span>
                    ))}
                    {novel.tags.length > 6 && (
                      <span className="rounded-full border border-dark-700/70 bg-dark-950 px-2 py-0.5 text-[11px] text-dark-500">+{novel.tags.length - 6}</span>
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
    <div className="rounded-xl border border-dark-700/50 bg-dark-950/80 px-3 py-2 text-center">
      <div className="text-sm font-medium text-dark-100">{value}</div>
      <div className="mt-1 text-[11px] text-dark-500">{label}</div>
    </div>
  )
}

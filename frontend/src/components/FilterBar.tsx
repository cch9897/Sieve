import { useMemo } from 'react'
import { getSourceMeta } from '../sourceMeta'

type GalleryMode = 'infinite' | 'paged'
type MediaFilter = '' | 'image' | 'video'

interface FilterBarProps {
  sources: string[]
  sourceCounts?: Record<string, number>
  dates: string[]
  selectedSource: string
  selectedDate: string
  selectedMedia: MediaFilter
  sort: string
  onSourceChange: (s: string) => void
  onDateChange: (d: string) => void
  onMediaChange: (m: MediaFilter) => void
  onSortChange: (s: string) => void
  total: number
  mode: GalleryMode
  onModeChange: (mode: GalleryMode) => void
  expanded: boolean
  onExpandedChange: (expanded: boolean | ((prev: boolean) => boolean)) => void
}

export default function FilterBar({
  sources, sourceCounts, dates, selectedSource, selectedDate, selectedMedia, sort,
  onSourceChange, onDateChange, onMediaChange, onSortChange, total,
  mode, onModeChange, expanded, onExpandedChange,
}: FilterBarProps) {
  const activeCount = useMemo(() => {
    let count = 0
    if (selectedSource) count += 1
    if (selectedDate) count += 1
    if (selectedMedia) count += 1
    if (sort !== 'newest') count += 1
    return count
  }, [selectedSource, selectedDate, selectedMedia, sort])

  const clearAll = () => {
    onSourceChange('')
    onDateChange('')
    onMediaChange('')
    onSortChange('newest')
  }

  return (
    <div className="sticky top-[72px] z-30 border-b border-dark-700/40 bg-dark-950/72 backdrop-blur-xl md:top-16">
      <div className="mx-auto max-w-[1920px] px-4 py-3">
        <div className="flex flex-col gap-3">
          {/* Top row: filter toggle + mode switch + pills */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => onExpandedChange(v => !v)}
              className={[
                'inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition-colors',
                activeCount > 0 || expanded
                  ? 'border-blue-500/30 bg-blue-500/10 text-blue-200'
                  : 'border-dark-700 bg-dark-900 text-dark-300 hover:border-dark-600 hover:text-dark-100',
              ].join(' ')}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 5h18" /><path d="M6 12h12" /><path d="M10 19h4" />
              </svg>
              筛选
              {activeCount > 0 && (
                <span className="rounded-full bg-blue-400/20 px-1.5 py-0.5 text-[10px] text-blue-200">{activeCount}</span>
              )}
            </button>

            {/* Mode switch */}
            <div className="inline-flex items-center rounded-xl border border-dark-700/60 bg-dark-900/90 p-1 text-sm">
              <button
                onClick={() => onModeChange('infinite')}
                className={['rounded-lg px-3 py-1.5 transition-colors', mode === 'infinite' ? 'bg-dark-700 text-dark-50' : 'text-dark-400 hover:text-dark-100'].join(' ')}
              >
                无限滚动
              </button>
              <button
                onClick={() => onModeChange('paged')}
                className={['rounded-lg px-3 py-1.5 transition-colors', mode === 'paged' ? 'bg-dark-700 text-dark-50' : 'text-dark-400 hover:text-dark-100'].join(' ')}
              >
                分页
              </button>
            </div>

            {/* Media type quick filter */}
            <div className="inline-flex items-center rounded-xl border border-dark-700/60 bg-dark-900/90 p-1 text-sm">
              <button
                onClick={() => onMediaChange('')}
                className={['rounded-lg px-2.5 py-1.5 transition-colors', !selectedMedia ? 'bg-dark-700 text-dark-50' : 'text-dark-400 hover:text-dark-100'].join(' ')}
              >
                全部
              </button>
              <button
                onClick={() => onMediaChange('image')}
                className={['rounded-lg px-2.5 py-1.5 transition-colors', selectedMedia === 'image' ? 'bg-dark-700 text-dark-50' : 'text-dark-400 hover:text-dark-100'].join(' ')}
              >
                🖼 图片
              </button>
              <button
                onClick={() => onMediaChange('video')}
                className={['rounded-lg px-2.5 py-1.5 transition-colors', selectedMedia === 'video' ? 'bg-dark-700 text-dark-50' : 'text-dark-400 hover:text-dark-100'].join(' ')}
              >
                🎬 视频
              </button>
            </div>

            {/* Info pills */}
            <div className="hidden flex-wrap items-center gap-2 text-xs text-dark-500 sm:flex">
              <InfoPill label="总数" value={`${total} 张`} />
              {selectedSource && <InfoPill label="来源" value={getSourceMeta(selectedSource).label} />}
              {selectedDate && <InfoPill label="日期" value={selectedDate} />}
              {sort !== 'newest' && <InfoPill label="排序" value={sortLabel(sort)} />}
            </div>

            {activeCount > 0 && (
              <button
                onClick={clearAll}
                className="ml-auto rounded-lg px-2.5 py-1.5 text-xs text-dark-400 hover:bg-dark-900 hover:text-dark-100"
              >
                清空筛选
              </button>
            )}
          </div>

          {/* Expanded filter panel */}
          {expanded && (
            <div className="grid gap-3 rounded-2xl border border-dark-700/60 bg-dark-900/80 p-3 shadow-sm lg:grid-cols-[1.8fr_220px_180px]">
              <section>
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-dark-500">来源</div>
                <div className="flex flex-wrap gap-2">
                  <SourceChip
                    active={!selectedSource}
                    label="全部"
                    count={total}
                    onClick={() => onSourceChange('')}
                  />
                  {sources.map(source => (
                    <SourceChip
                      key={source}
                      active={selectedSource === source}
                      label={getSourceMeta(source).label}
                      count={sourceCounts?.[source]}
                      className={getSourceMeta(source).chipClass}
                      onClick={() => onSourceChange(selectedSource === source ? '' : source)}
                    />
                  ))}
                </div>
              </section>

              <label className="block">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-dark-500">日期</div>
                <select
                  value={selectedDate}
                  onChange={e => onDateChange(e.target.value)}
                  className="w-full rounded-xl border border-dark-700 bg-dark-950 px-3 py-2 text-sm text-dark-100 outline-none transition-colors focus:border-dark-500"
                >
                  <option value="">全部日期</option>
                  {dates.map(d => (<option key={d} value={d}>{d}</option>))}
                </select>
              </label>

              <label className="block">
                <div className="mb-2 text-xs font-medium uppercase tracking-wide text-dark-500">排序</div>
                <select
                  value={sort}
                  onChange={e => onSortChange(e.target.value)}
                  className="w-full rounded-xl border border-dark-700 bg-dark-950 px-3 py-2 text-sm text-dark-100 outline-none transition-colors focus:border-dark-500"
                >
                  <option value="newest">最新优先</option>
                  <option value="oldest">最早优先</option>
                </select>
              </label>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SourceChip({ active, label, count, className, onClick }: {
  active: boolean; label: string; count?: number; className?: string; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-all',
        active
          ? className || 'border-dark-500 bg-dark-700 text-dark-100'
          : 'border-dark-700 bg-dark-950 text-dark-400 hover:border-dark-600 hover:text-dark-100',
      ].join(' ')}
    >
      <span>{label}</span>
      {count !== undefined && <span className="text-[11px] opacity-70">{count}</span>}
    </button>
  )
}

function InfoPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-dark-800 bg-dark-900 px-2.5 py-1 text-xs text-dark-400">
      <span className="text-dark-600">{label}</span>
      <span className="text-dark-300">{value}</span>
    </span>
  )
}

function sortLabel(sort: string) {
  return sort === 'oldest' ? '最早优先' : '最新优先'
}

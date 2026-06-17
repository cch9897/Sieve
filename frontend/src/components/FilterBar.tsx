import { useMemo } from 'react'
import { getSourceMeta } from '../sourceMeta'
import type { GalleryMode, MediaFilter } from '../types'
import FilterChip from './FilterChip'

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
  searchQuery?: string
  onSearchChange?: (q: string) => void
  onClearAll?: () => void
}

export default function FilterBar({
  sources, sourceCounts, dates, selectedSource, selectedDate, selectedMedia, sort,
  onSourceChange, onDateChange, onMediaChange, onSortChange, total,
  mode, onModeChange, expanded, onExpandedChange, searchQuery, onSearchChange, onClearAll,
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
    if (onClearAll) { onClearAll(); return }
    onSearchChange?.('')
    onSourceChange('')
    onDateChange('')
    onMediaChange('')
    onSortChange('newest')
  }

  return (
    <div className="sticky z-30 px-3 pt-3 md:top-[calc(var(--header-height)+10px)] md:px-6 md:pt-4 top-[calc(var(--header-height)+8px)]">
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {`显示 ${total} 项`}
      </div>
      <div className="editorial-panel mx-auto max-w-[1920px] rounded-[28px] px-4 py-4 md:px-6 md:py-5">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="micro-label">Gallery Filters</div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--muted)]">
                <InfoPill label="总藏品" value={`${total} 项`} />
                <InfoPill label="当前模式" value={mode === 'infinite' ? 'Infinite Flow' : 'Paged Sheets'} />
                {selectedSource && <FilterChip label="来源" value={getSourceMeta(selectedSource).label} onDismiss={() => onSourceChange('')} />}
                {selectedDate && <FilterChip label="日期" value={selectedDate} onDismiss={() => onDateChange('')} />}
                {selectedMedia && <FilterChip label="媒介" value={selectedMedia === 'image' ? '静态图像' : '动态影像'} onDismiss={() => onMediaChange('')} />}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => onExpandedChange(v => !v)}
                aria-expanded={expanded}
                aria-pressed={expanded}
                className={[
                  'xl:hidden inline-flex items-center gap-2 rounded-2xl border px-4 py-2.5 text-sm transition-all duration-200',
                  activeCount > 0 || expanded
                    ? 'border-[var(--line-strong)] bg-[var(--accent-soft)] text-[var(--text)]'
                    : 'border-[var(--line)] bg-[rgba(255,255,255,0.03)] text-[var(--muted)] hover:text-[var(--text)]',
                ].join(' ')}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 7h16" /><path d="M7 12h10" /><path d="M10 17h4" />
                </svg>
                打开筛选台
                {activeCount > 0 && (
                  <span className="rounded-full border border-[var(--line-strong)] bg-black/20 px-1.5 py-0.5 text-[10px] text-[var(--text)]">{activeCount}</span>
                )}
              </button>

              <div className="inline-flex items-center rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.03)] p-1 text-sm">
                <ModeButton active={mode === 'infinite'} onClick={() => onModeChange('infinite')}>无限滚动</ModeButton>
                <ModeButton active={mode === 'paged'} onClick={() => onModeChange('paged')}>分页</ModeButton>
              </div>

              <div className="inline-flex items-center rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.03)] p-1 text-sm">
                <ModeButton active={!selectedMedia} onClick={() => onMediaChange('')}>全部</ModeButton>
                <ModeButton active={selectedMedia === 'image'} onClick={() => onMediaChange('image')}>图片</ModeButton>
                <ModeButton active={selectedMedia === 'video'} onClick={() => onMediaChange('video')}>视频</ModeButton>
              </div>

              {activeCount > 0 && (
                <button
                  onClick={clearAll}
                  className="rounded-2xl border border-[var(--line)] px-3 py-2 text-xs uppercase tracking-[0.18em] text-[var(--muted)] transition-colors hover:text-[var(--text)]"
                >
                  Reset
                </button>
              )}
            </div>
          </div>

          {onSearchChange && (
            <div className="flex items-center gap-2 pt-1 first:pt-0">
              <input
                type="text"
                value={searchQuery || ''}
                onChange={e => onSearchChange(e.target.value)}
                placeholder="搜索 source_id 或 文件路径…"
                aria-label="搜索图片"
                className={`${fieldClassName} max-w-sm`}
              />
              {searchQuery && (
                <button
                  onClick={() => onSearchChange('')}
                  aria-label="清除搜索"
                  className="rounded-2xl border border-[var(--line)] px-3 py-2 text-xs text-[var(--muted)] transition-colors hover:text-[var(--text)]"
                >
                  清除
                </button>
              )}
            </div>
          )}

          <div className={`grid gap-3 overflow-hidden transition-all duration-300 rounded-[24px] border border-[var(--line)] bg-[rgba(255,255,255,0.025)] p-3 md:grid-cols-2 xl:grid-cols-4 ${expanded ? 'max-h-[500px] opacity-100 mt-3' : 'max-h-0 opacity-0 mt-0 p-0 border-0 xl:max-h-[500px] xl:opacity-100 xl:mt-3 xl:p-3 xl:border'}`}>
              <Field label="来源">
                <select value={selectedSource} onChange={e => onSourceChange(e.target.value)} className={fieldClassName}>
                  <option value="">全部来源</option>
                  {sources.map(source => {
                    const meta = getSourceMeta(source)
                    const count = sourceCounts?.[source]
                    return (
                      <option key={source} value={source}>
                        {meta.label}{typeof count === 'number' ? ` (${count})` : ''}
                      </option>
                    )
                  })}
                </select>
              </Field>

              <Field label="日期">
                <select value={selectedDate} onChange={e => onDateChange(e.target.value)} className={fieldClassName}>
                  <option value="">全部日期</option>
                  {dates.map(date => <option key={date} value={date}>{date}</option>)}
                </select>
              </Field>

              <Field label="排序">
                <select value={sort} onChange={e => onSortChange(e.target.value)} className={fieldClassName}>
                  <option value="newest">最新优先</option>
                  <option value="oldest">最早优先</option>
                </select>
              </Field>
            </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-2 text-[11px] uppercase tracking-[0.2em] text-[var(--muted)]">{label}</div>
      {children}
    </label>
  )
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={[
        'rounded-[14px] px-3 py-1.5 transition-all duration-200',
        active
          ? 'bg-[linear-gradient(180deg,rgba(214,165,93,0.24),rgba(159,91,82,0.14))] text-[var(--text)]'
          : 'text-[var(--muted)] hover:text-[var(--text)]',
      ].join(' ')}
    >
      {children}
    </button>
  )
}

function InfoPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5">
      <span className="text-[10px] uppercase tracking-[0.22em] text-[var(--muted)]/80">{label}</span>
      <span className="text-[13px] text-[var(--text)]">{value}</span>
    </span>
  )
}

const fieldClassName = 'w-full appearance-none rounded-2xl border border-[var(--line)] bg-[rgba(14,12,10,0.92)] px-4 py-3 text-sm text-[var(--text)] outline-none transition focus:border-[var(--line-strong)] focus-visible:ring-2 focus-visible:ring-[var(--accent)] cursor-pointer bg-[length:12px_8px] bg-[right_12px_center] bg-no-repeat pr-10'

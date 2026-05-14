import { useCallback, useRef, useState, type ReactNode } from 'react'
import type { AutoTagsStats } from '../../api'
import type { Stats } from '../../types'
import { SOURCE_META, getSourceMeta } from '../../sourceMeta'

interface TooltipData {
  date: string
  total: number
  sources: Record<string, number>
  x: number
  y: number
}

interface StatsChartsProps {
  stats: Stats
  autoTagsStats: AutoTagsStats | null
  /** Recent dates already sliced & sorted in the parent (last 21). */
  recentDates: string[]
  /** Pre-computed daily max for normalisation. */
  maxDaily: number
  /** Recent-7-day average (for header strip). */
  avg7: number
  /** Pct change between most-recent-7d and prior-7d windows. */
  trendPct: number
  /** Total active dates (for the overview StatCard). */
  activeDates: number
  /**
   * Slot rendered between the auto-tagging progress block and the source/daily
   * grid — preserves the original StatsView visual order where Model Management
   * sits in the middle of the page.
   */
  modelPanelSlot?: ReactNode
}

export default function StatsCharts({
  stats,
  autoTagsStats,
  recentDates,
  maxDaily,
  avg7,
  trendPct,
  activeDates,
  modelPanelSlot,
}: StatsChartsProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<TooltipData | null>(null)

  const handleBarHover = useCallback((
    e: React.MouseEvent,
    date: string,
    total: number,
    sources: Record<string, number>,
  ) => {
    const rect = chartRef.current?.getBoundingClientRect()
    if (!rect) return
    setTooltip({
      date,
      total,
      sources,
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    })
  }, [])

  const handleBarLeave = useCallback(() => setTooltip(null), [])

  return (
    <>
      {/* Overview cards */}
      <section className="rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-[var(--text)]">统计概览</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">收藏规模、来源结构和每日变化。</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
            <span>最近 7 天均值 <strong className="text-[var(--text)]">{avg7.toFixed(1)}</strong>/天</span>
            {trendPct !== 0 && (
              <span className={trendPct > 0 ? 'text-emerald-400' : 'text-red-400'}>
                {trendPct > 0 ? '↑' : '↓'} {Math.abs(trendPct).toFixed(0)}%
              </span>
            )}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard label="图片总数" value={stats.total} icon="🖼" />
          <StatCard label="小说数" value={stats.total_novels || 0} icon="📖" />
          <StatCard label="数据库记录" value={stats.total_db} icon="💾" />
          <StatCard label="活跃日期" value={activeDates} icon="📅" />
          <StatCard label="来源数" value={Object.keys(stats.by_source).length} icon="🌐" />
        </div>
      </section>

      {/* Auto-tagging progress */}
      {autoTagsStats && (
        <section className="rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
          <h3 className="text-sm font-medium text-[var(--text)]">自动打标进度</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">AI 模型自动识别图片内容标签。</p>

          <div className="mt-4 flex items-center gap-4">
            <div className="flex-1">
              <div className="h-3 overflow-hidden rounded-full bg-[var(--surface)]">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 progress-bar-fill"
                  style={{ transform: `scaleX(${autoTagsStats.progress_pct / 100})` }}
                />
              </div>
            </div>
            <div className="shrink-0 text-sm text-[var(--text)]">
              {autoTagsStats.tagged.toLocaleString()} / {autoTagsStats.total.toLocaleString()}
              <span className="ml-2 text-xs text-[var(--muted)]">({autoTagsStats.progress_pct.toFixed(1)}%)</span>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted)]">
            {autoTagsStats.remaining > 0 && (
              <span>剩余 {autoTagsStats.remaining.toLocaleString()} 张待标记</span>
            )}
            {(autoTagsStats.errored ?? 0) > 0 && (
              <span className="text-amber-400/80">
                ⚠ {autoTagsStats.errored} 张损坏/无法识别
              </span>
            )}
          </div>

          {/* Per-source errors */}
          {(autoTagsStats.errored ?? 0) > 0 && autoTagsStats.errors_by_source && Object.keys(autoTagsStats.errors_by_source).length > 0 && (
            <div className="mt-3 rounded-ed-md border border-amber-500/20 bg-amber-500/5 p-3">
              <div className="mb-2 text-xs font-medium text-amber-300/80">损坏文件来源分布</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(autoTagsStats.errors_by_source)
                  .sort(([, a], [, b]) => b - a)
                  .map(([source, count]) => {
                    const meta = getSourceMeta(source)
                    return (
                      <span
                        key={source}
                        className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-[var(--surface)] px-2.5 py-1 text-[11px] text-[var(--text)]"
                      >
                        <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
                        {meta.label}
                        <span className="text-amber-400/70">{count}</span>
                      </span>
                    )
                  })}
              </div>
            </div>
          )}

          {autoTagsStats.top_tags.length > 0 && (
            <div className="mt-5">
              <div className="text-xs uppercase tracking-wide text-[var(--muted)] mb-3">热门标签</div>
              <div className="flex flex-wrap gap-2">
                {autoTagsStats.top_tags.slice(0, 30).map((t, i) => (
                  <span
                    key={t.tag}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/70 transition-colors hover:border-blue-400/30 hover:bg-blue-400/10 hover:text-blue-200"
                    style={{ opacity: Math.max(0.5, 1 - i * 0.015) }}
                  >
                    {t.tag}
                    <span className="ml-1 text-white/40">{t.count}</span>
                  </span>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {modelPanelSlot}

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        {/* Source distribution */}
        <section className="rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
          <h3 className="text-sm font-medium text-[var(--text)]">来源分布</h3>
          <div className="mt-4 space-y-3">
            {Object.entries(stats.by_source)
              .sort(([, a], [, b]) => b - a)
              .map(([source, count]) => {
                const meta = getSourceMeta(source)
                const pct = ((count / stats.total) * 100).toFixed(1)
                return (
                  <div key={source} className="group rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3 transition-colors hover:border-[var(--line-strong)]">
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2 text-[var(--text)]">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
                        <span>{meta.label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-[var(--muted)]">{pct}%</span>
                        <span className="text-[var(--muted)]">{count.toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]">
                      <div
                        className="h-full rounded-full transition-colors duration-500 group-hover:brightness-110"
                        style={{
                          width: `${(count / stats.total) * 100}%`,
                          backgroundColor: meta.color,
                        }}
                      />
                    </div>
                  </div>
                )
              })}
          </div>
        </section>

        {/* Daily chart */}
        <section className="relative rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="text-sm font-medium text-[var(--text)]">每日新增</h3>
              <p className="mt-1 text-xs text-[var(--muted)]">悬停查看每天的来源拆分。</p>
            </div>
          </div>

          <div ref={chartRef} className="relative mt-6" style={{ minHeight: '18rem' }}>
            <div className="flex h-72 items-end gap-1.5 sm:gap-2">
              {recentDates.map(date => {
                const total = stats.by_date[date]
                const pct = (total / maxDaily) * 100
                const sources = stats.by_date_source[date] || {}
                return (
                  <div
                    key={date}
                    className="group relative flex min-w-6 flex-1 flex-col items-center gap-2 sm:min-w-8"
                    onMouseMove={(e) => handleBarHover(e, date, total, sources)}
                    onMouseLeave={handleBarLeave}
                  >
                    <div className="flex h-64 w-full items-end">
                      <div
                        className="flex w-full flex-col-reverse overflow-hidden rounded-t-lg rounded-b-sm border border-[var(--line)] bg-[var(--panel-strong)] transition-all duration-200 hover:border-[var(--line-strong)] hover:brightness-110 sm:rounded-t-xl sm:rounded-b-md"
                        style={{ height: `${Math.max(pct, 4)}%` }}
                      >
                        {Object.entries(sources).map(([s, c]) => (
                          <div
                            key={s}
                            style={{
                              height: `${(c / total) * 100}%`,
                              backgroundColor: getSourceMeta(s).color,
                            }}
                          />
                        ))}
                      </div>
                    </div>
                    <span className="text-[10px] text-[var(--muted)] opacity-50 sm:text-[11px]">{date.slice(5)}</span>
                  </div>
                )
              })}
            </div>

            {/* Tooltip - rendered outside overflow to avoid clipping */}
            {tooltip && (
              <div
                className="pointer-events-none absolute z-50 min-w-40 rounded-ed-md border border-[var(--line)] bg-[var(--bg)] px-3.5 py-2.5 text-xs text-[var(--text)] shadow-xl shadow-black/30 backdrop-blur-sm"
                style={{
                  left: Math.min(Math.max(tooltip.x - 80, 0), (chartRef.current?.offsetWidth || 400) - 170),
                  bottom: '5rem',
                }}
              >
                <div className="font-medium text-[var(--text)]">{tooltip.date}</div>
                <div className="mt-1.5 space-y-1">
                  {Object.entries(tooltip.sources)
                    .sort(([, a], [, b]) => b - a)
                    .map(([s, c]) => (
                      <div key={s} className="flex items-center justify-between gap-4">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: getSourceMeta(s).color }}
                          />
                          <span className="text-[var(--muted)]">{getSourceMeta(s).label}</span>
                        </div>
                        <span className="font-medium tabular-nums">{c}</span>
                      </div>
                    ))}
                </div>
                <div className="mt-2 border-t border-[var(--line)] pt-2 font-medium text-[var(--text)]">
                  总计 {tooltip.total}
                </div>
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            {Object.entries(SOURCE_META).map(([source, meta]) => (
              <div key={source} className="flex items-center gap-1.5 rounded-full border border-[var(--line)] bg-[var(--panel-strong)] px-2.5 py-1 text-xs text-[var(--muted)]">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
                <span>{meta.label}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  )
}

function StatCard({ label, value, icon }: { label: string; value: number; icon?: string }) {
  return (
    <div className="group rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4 transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)]">
      <div className="flex items-start justify-between">
        <div className="text-2xl font-bold text-[var(--text)]">{value.toLocaleString()}</div>
        {icon && <span className="text-lg opacity-50 group-hover:opacity-80 transition-opacity">{icon}</span>}
      </div>
      <div className="mt-1 text-xs text-[var(--muted)]">{label}</div>
    </div>
  )
}

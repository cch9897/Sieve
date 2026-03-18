import { useEffect, useState, useRef, useCallback } from 'react'
import { fetchStats, fetchAutoTagsStats, fetchMLModels, startRetrainXGBoost, fetchRetrainStatus, startPackDataset, fetchPackStatus } from '../api'
import type { AutoTagsStats, MLModelsInfo, MLTaskStatus } from '../api'
import type { Stats } from '../types'
import { SOURCE_META, getSourceMeta } from '../sourceMeta'

interface TooltipData {
  date: string
  total: number
  sources: Record<string, number>
  x: number
  y: number
}

export default function StatsView() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [autoTagsStats, setAutoTagsStats] = useState<AutoTagsStats | null>(null)
  const [mlModels, setMlModels] = useState<MLModelsInfo | null>(null)
  const [retrainStatus, setRetrainStatus] = useState<MLTaskStatus | null>(null)
  const [packStatus, setPackStatus] = useState<MLTaskStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [tooltip, setTooltip] = useState<TooltipData | null>(null)
  const chartRef = useRef<HTMLDivElement>(null)
  const retrainPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const packPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    Promise.all([
      fetchStats().then(s => setStats(s)),
      fetchAutoTagsStats().then(s => setAutoTagsStats(s)).catch(() => {}),
      fetchMLModels().then(m => setMlModels(m)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (retrainPollRef.current) clearInterval(retrainPollRef.current)
      if (packPollRef.current) clearInterval(packPollRef.current)
    }
  }, [])

  const pollRetrain = useCallback(() => {
    if (retrainPollRef.current) return
    retrainPollRef.current = setInterval(async () => {
      try {
        const s = await fetchRetrainStatus()
        setRetrainStatus(s)
        if (!s.running) {
          clearInterval(retrainPollRef.current!)
          retrainPollRef.current = null
          // Refresh model info after completion
          fetchMLModels().then(m => setMlModels(m)).catch(() => {})
        }
      } catch { /* ignore */ }
    }, 3000)
  }, [])

  const pollPack = useCallback(() => {
    if (packPollRef.current) return
    packPollRef.current = setInterval(async () => {
      try {
        const s = await fetchPackStatus()
        setPackStatus(s)
        if (!s.running) {
          clearInterval(packPollRef.current!)
          packPollRef.current = null
        }
      } catch { /* ignore */ }
    }, 3000)
  }, [])

  const handleRetrain = useCallback(async () => {
    try {
      const res = await startRetrainXGBoost()
      if (res.status === 'started') {
        setRetrainStatus({ running: true, finished: false, exit_code: null, log: '' })
        pollRetrain()
      } else if (res.status === 'already_running') {
        pollRetrain()
      }
    } catch { /* ignore */ }
  }, [pollRetrain])

  const handlePack = useCallback(async () => {
    try {
      const res = await startPackDataset()
      if (res.status === 'started') {
        setPackStatus({ running: true, finished: false, exit_code: null, log: '' })
        pollPack()
      } else if (res.status === 'already_running') {
        pollPack()
      }
    } catch { /* ignore */ }
  }, [pollPack])

  const handleBarHover = useCallback((
    e: React.MouseEvent,
    date: string,
    total: number,
    sources: Record<string, number>
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

  if (loading || !stats) {
    return (
      <div className="flex h-64 items-center justify-center text-dark-500">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-dark-600 border-t-blue-400" />
      </div>
    )
  }

  const dates = Object.keys(stats.by_date).sort()
  const recentDates = dates.slice(-21)
  const maxDaily = Math.max(...recentDates.map(date => stats.by_date[date]), 1)

  // Compute trends
  const recent7 = dates.slice(-7)
  const prev7 = dates.slice(-14, -7)
  const avg7 = recent7.length > 0
    ? recent7.reduce((sum, d) => sum + stats.by_date[d], 0) / recent7.length
    : 0
  const avgPrev7 = prev7.length > 0
    ? prev7.reduce((sum, d) => sum + stats.by_date[d], 0) / prev7.length
    : 0
  const trendPct = avgPrev7 > 0 ? ((avg7 - avgPrev7) / avgPrev7 * 100) : 0

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 space-y-6">
      {/* Overview cards */}
      <section className="rounded-3xl border border-dark-700/60 bg-dark-900/75 p-5 shadow-sm md:p-6">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-dark-100">统计概览</h2>
            <p className="mt-1 text-sm text-dark-500">收藏规模、来源结构和每日变化。</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-dark-500">
            <span>最近 7 天均值 <strong className="text-dark-300">{avg7.toFixed(1)}</strong>/天</span>
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
          <StatCard label="活跃日期" value={dates.length} icon="📅" />
          <StatCard label="来源数" value={Object.keys(stats.by_source).length} icon="🌐" />
        </div>
      </section>

      {/* Auto-tagging progress */}
      {autoTagsStats && (
        <section className="rounded-3xl border border-dark-700/60 bg-dark-900/75 p-5 shadow-sm md:p-6">
          <h3 className="text-sm font-medium text-dark-200">自动打标进度</h3>
          <p className="mt-1 text-xs text-dark-500">AI 模型自动识别图片内容标签。</p>

          <div className="mt-4 flex items-center gap-4">
            <div className="flex-1">
              <div className="h-3 overflow-hidden rounded-full bg-dark-800">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-blue-500 to-blue-400 transition-all duration-500"
                  style={{ width: `${autoTagsStats.progress_pct}%` }}
                />
              </div>
            </div>
            <div className="shrink-0 text-sm text-dark-300">
              {autoTagsStats.tagged.toLocaleString()} / {autoTagsStats.total.toLocaleString()}
              <span className="ml-2 text-xs text-dark-500">({autoTagsStats.progress_pct.toFixed(1)}%)</span>
            </div>
          </div>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-dark-500">
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
            <div className="mt-3 rounded-2xl border border-amber-500/20 bg-amber-500/5 p-3">
              <div className="mb-2 text-xs font-medium text-amber-300/80">损坏文件来源分布</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(autoTagsStats.errors_by_source)
                  .sort(([, a], [, b]) => b - a)
                  .map(([source, count]) => {
                    const meta = getSourceMeta(source)
                    return (
                      <span
                        key={source}
                        className="inline-flex items-center gap-1.5 rounded-full border border-amber-500/20 bg-dark-900/60 px-2.5 py-1 text-[11px] text-dark-300"
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
              <div className="text-xs uppercase tracking-wide text-dark-500 mb-3">热门标签</div>
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

      {/* Model Management */}
      <section className="rounded-3xl border border-dark-700/60 bg-dark-900/75 p-5 shadow-sm md:p-6">
        <h3 className="text-sm font-medium text-dark-200">模型管理</h3>
        <p className="mt-1 text-xs text-dark-500">偏好分类模型状态与训练操作。</p>

        {/* Model cards */}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {/* XGBoost card */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-950/60 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-dark-200">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
              XGBoost
              {mlModels?.xgboost ? (
                <span className="ml-auto rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-400">已加载</span>
              ) : (
                <span className="ml-auto rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">未加载</span>
              )}
            </div>
            {mlModels?.xgboost ? (
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                  <div className="text-dark-500">AUC</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.xgboost.auc.toFixed(3)}</div>
                </div>
                <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                  <div className="text-dark-500">样本数</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.xgboost.n_samples.toLocaleString()}</div>
                </div>
                <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                  <div className="text-dark-500">喜欢/不喜欢</div>
                  <div className="mt-0.5 text-sm text-dark-200">
                    <span className="text-emerald-400">{mlModels.xgboost.n_liked.toLocaleString()}</span>
                    {' / '}
                    <span className="text-red-400">{mlModels.xgboost.n_disliked.toLocaleString()}</span>
                  </div>
                </div>
                <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                  <div className="text-dark-500">特征维度</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.xgboost.vocab_size.toLocaleString()}</div>
                </div>
              </div>
            ) : (
              <div className="mt-3 text-xs text-dark-500">模型文件不存在或加载失败</div>
            )}
          </div>

          {/* Vision model card */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-950/60 p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-dark-200">
              <span className="h-2.5 w-2.5 rounded-full bg-blue-400" />
              Vision
              {mlModels?.cnn ? (
                <span className="ml-auto rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-400">已加载</span>
              ) : (
                <span className="ml-auto rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">未加载</span>
              )}
            </div>
            {mlModels?.cnn ? (
              <div className="mt-3 space-y-2 text-xs">
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                    <div className="text-dark-500">CV AUC</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.cnn.cv_auc.toFixed(3)}</div>
                  </div>
                  <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                    <div className="text-dark-500">输入尺寸</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.cnn.input_size}px</div>
                  </div>
                  <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                    <div className="text-dark-500">样本数</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-dark-200">{mlModels.cnn.n_samples.toLocaleString()}</div>
                  </div>
                  <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                    <div className="text-dark-500">模型架构</div>
                    <div className="mt-0.5 text-[11px] font-medium text-dark-200 truncate" title={mlModels.cnn.model_name}>{mlModels.cnn.model_name}</div>
                  </div>
                </div>
                {mlModels.cnn.fold_aucs.length > 0 && (
                  <div className="rounded-xl bg-dark-900/60 px-3 py-2">
                    <div className="text-dark-500 mb-1">Fold AUCs</div>
                    <div className="flex gap-1.5">
                      {mlModels.cnn.fold_aucs.map((auc, i) => (
                        <span key={i} className="rounded-md bg-blue-500/10 px-1.5 py-0.5 font-mono text-[10px] text-blue-300">{auc.toFixed(3)}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-3 text-xs text-dark-500">模型文件不存在或加载失败</div>
            )}
          </div>
        </div>

        {/* Action buttons */}
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {/* Pack dataset */}
          <div>
            <button
              onClick={handlePack}
              disabled={packStatus?.running}
              className="w-full rounded-2xl border border-dark-700/50 bg-dark-950/60 px-4 py-3 text-sm font-medium text-dark-200 transition-all hover:border-dark-500/60 hover:bg-dark-900/60 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {packStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-dark-600 border-t-amber-400" />
                  打包中...
                </span>
              ) : '打包训练集'}
            </button>
            {packStatus && !packStatus.running && packStatus.finished && (
              <div className={`mt-2 rounded-xl px-3 py-2 text-xs ${packStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                {packStatus.exit_code === 0 ? '打包完成' : `打包失败 (exit ${packStatus.exit_code})`}
              </div>
            )}
          </div>

          {/* Retrain XGBoost */}
          <div>
            <button
              onClick={handleRetrain}
              disabled={retrainStatus?.running}
              className="w-full rounded-2xl border border-dark-700/50 bg-dark-950/60 px-4 py-3 text-sm font-medium text-dark-200 transition-all hover:border-dark-500/60 hover:bg-dark-900/60 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {retrainStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-dark-600 border-t-blue-400" />
                  训练中...
                </span>
              ) : '重训 XGBoost'}
            </button>
            {retrainStatus && !retrainStatus.running && retrainStatus.finished && (
              <div className={`mt-2 rounded-xl px-3 py-2 text-xs ${retrainStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                {retrainStatus.exit_code === 0 ? '训练完成，模型已热加载' : `训练失败 (exit ${retrainStatus.exit_code})`}
              </div>
            )}
          </div>
        </div>

        {/* Log output */}
        {(retrainStatus?.log || packStatus?.log) && (
          <div className="mt-4 space-y-3">
            {packStatus?.log && (
              <div className="rounded-2xl border border-dark-700/40 bg-dark-950/80 p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-dark-500">打包日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-dark-400">{packStatus.log}</pre>
              </div>
            )}
            {retrainStatus?.log && (
              <div className="rounded-2xl border border-dark-700/40 bg-dark-950/80 p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-dark-500">训练日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-dark-400">{retrainStatus.log}</pre>
              </div>
            )}
          </div>
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        {/* Source distribution */}
        <section className="rounded-3xl border border-dark-700/60 bg-dark-900/75 p-5 shadow-sm md:p-6">
          <h3 className="text-sm font-medium text-dark-200">来源分布</h3>
          <div className="mt-4 space-y-3">
            {Object.entries(stats.by_source)
              .sort(([, a], [, b]) => b - a)
              .map(([source, count]) => {
                const meta = getSourceMeta(source)
                const pct = ((count / stats.total) * 100).toFixed(1)
                return (
                  <div key={source} className="group rounded-2xl border border-dark-700/50 bg-dark-950/60 p-3 transition-colors hover:border-dark-600/70">
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <div className="flex items-center gap-2 text-dark-200">
                        <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
                        <span>{meta.label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-dark-500">{pct}%</span>
                        <span className="text-dark-400">{count.toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-dark-800">
                      <div
                        className="h-full rounded-full transition-all duration-500 group-hover:brightness-110"
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
        <section className="relative rounded-3xl border border-dark-700/60 bg-dark-900/75 p-5 shadow-sm md:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h3 className="text-sm font-medium text-dark-200">每日新增</h3>
              <p className="mt-1 text-xs text-dark-500">悬停查看每天的来源拆分。</p>
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
                        className="flex w-full flex-col-reverse overflow-hidden rounded-t-lg rounded-b-sm border border-dark-700/40 bg-dark-950/60 transition-all duration-200 hover:border-dark-500/60 hover:brightness-110 sm:rounded-t-xl sm:rounded-b-md"
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
                    <span className="text-[10px] text-dark-600 sm:text-[11px]">{date.slice(5)}</span>
                  </div>
                )
              })}
            </div>

            {/* Tooltip - rendered outside overflow to avoid clipping */}
            {tooltip && (
              <div
                className="pointer-events-none absolute z-50 min-w-40 rounded-2xl border border-dark-600 bg-dark-950/95 px-3.5 py-2.5 text-xs text-dark-200 shadow-xl shadow-black/30 backdrop-blur-sm"
                style={{
                  left: Math.min(Math.max(tooltip.x - 80, 0), (chartRef.current?.offsetWidth || 400) - 170),
                  bottom: '5rem',
                }}
              >
                <div className="font-medium text-dark-100">{tooltip.date}</div>
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
                          <span className="text-dark-400">{getSourceMeta(s).label}</span>
                        </div>
                        <span className="font-medium tabular-nums">{c}</span>
                      </div>
                    ))}
                </div>
                <div className="mt-2 border-t border-dark-700 pt-2 font-medium text-dark-200">
                  总计 {tooltip.total}
                </div>
              </div>
            )}
          </div>

          {/* Legend */}
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            {Object.entries(SOURCE_META).map(([source, meta]) => (
              <div key={source} className="flex items-center gap-1.5 rounded-full border border-dark-800 bg-dark-950 px-2.5 py-1 text-xs text-dark-400">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
                <span>{meta.label}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function StatCard({ label, value, icon }: { label: string; value: number; icon?: string }) {
  return (
    <div className="group rounded-2xl border border-dark-700/50 bg-dark-950/70 p-4 transition-all hover:border-dark-600/70 hover:bg-dark-900/70">
      <div className="flex items-start justify-between">
        <div className="text-2xl font-bold text-dark-100">{value.toLocaleString()}</div>
        {icon && <span className="text-lg opacity-50 group-hover:opacity-80 transition-opacity">{icon}</span>}
      </div>
      <div className="mt-1 text-xs text-dark-500">{label}</div>
    </div>
  )
}

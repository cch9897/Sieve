import { useEffect, useState, useRef, useCallback } from 'react'
import Spinner from './Spinner'
import { fetchStats, fetchAutoTagsStats, fetchMLModels, startRetrainXGBoost, fetchRetrainStatus, startPackDataset, fetchPackStatus, startVisionScore, fetchVisionScoreStatus, fetchVisionModels, setActiveModel, fetchVisionScoreCompareStats, startTagTrain, fetchTagTrainStatus } from '../api'
import type { AutoTagsStats, MLModelsInfo, MLTaskStatus, ModelsResponse, CompareStatsResponse } from '../api'
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
  const [vscoreStatus, setVscoreStatus] = useState<MLTaskStatus | null>(null)
  const [tagTrainStatus, setTagTrainStatus] = useState<MLTaskStatus | null>(null)
  const [visionModels, setVisionModels] = useState<ModelsResponse | null>(null)
  const [compareStats, setCompareStats] = useState<CompareStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [tooltip, setTooltip] = useState<TooltipData | null>(null)
  const chartRef = useRef<HTMLDivElement>(null)
  const retrainPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const packPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const vscorePollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const tagTrainPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    Promise.all([
      fetchStats().then(s => setStats(s)).catch(() => {}),
      fetchAutoTagsStats().then(s => setAutoTagsStats(s)).catch(() => {}),
      fetchMLModels().then(m => setMlModels(m)).catch(() => {}),
      fetchVisionModels().then(m => setVisionModels(m)).catch(() => {}),
      fetchVisionScoreCompareStats().then(s => setCompareStats(s)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (retrainPollRef.current) clearInterval(retrainPollRef.current)
      if (packPollRef.current) clearInterval(packPollRef.current)
      if (vscorePollRef.current) clearInterval(vscorePollRef.current)
      if (tagTrainPollRef.current) clearInterval(tagTrainPollRef.current)
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
      } catch (e) { console.error('retrain polling failed:', e) }
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
      } catch (e) { console.error('pack polling failed:', e) }
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
    } catch (e) { console.error('retrain start failed:', e) }
  }, [pollRetrain])

  const pollVscore = useCallback(() => {
    if (vscorePollRef.current) return
    vscorePollRef.current = setInterval(async () => {
      try {
        const s = await fetchVisionScoreStatus()
        setVscoreStatus(s)
        if (!s.running) {
          clearInterval(vscorePollRef.current!)
          vscorePollRef.current = null
        }
      } catch (e) { console.error('vscore polling failed:', e) }
    }, 3000)
  }, [])

  const handleVscore = useCallback(async () => {
    try {
      const res = await startVisionScore(visionModels?.active_model || undefined)
      if (res.status === 'started') {
        setVscoreStatus({ running: true, finished: false, exit_code: null, log: '' })
        pollVscore()
      } else if (res.status === 'already_running') {
        pollVscore()
      }
    } catch (e) { console.error('vscore start failed:', e) }
  }, [pollVscore, visionModels?.active_model])

  const handlePack = useCallback(async (maxSize?: number) => {
    try {
      const res = await startPackDataset(maxSize)
      if (res.status === 'started') {
        setPackStatus({ running: true, finished: false, exit_code: null, log: '' })
        pollPack()
      } else if (res.status === 'already_running') {
        pollPack()
      }
    } catch (e) { console.error('pack start failed:', e) }
  }, [pollPack])

  const pollTagTrain = useCallback(() => {
    if (tagTrainPollRef.current) return
    tagTrainPollRef.current = setInterval(async () => {
      try {
        const s = await fetchTagTrainStatus()
        setTagTrainStatus(s)
        if (!s.running) {
          clearInterval(tagTrainPollRef.current!)
          tagTrainPollRef.current = null
        }
      } catch (e) { console.error('tag-train polling failed:', e) }
    }, 3000)
  }, [])

  const handleTagTrain = useCallback(async () => {
    try {
      const res = await startTagTrain()
      if (res.status === 'started') {
        setTagTrainStatus({ running: true, finished: false, exit_code: null, log: '' })
        pollTagTrain()
      } else if (res.status === 'already_running') {
        pollTagTrain()
      }
    } catch (e) { console.error('tag-train start failed:', e) }
  }, [pollTagTrain])

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
      <div className="flex h-64 items-center justify-center text-[var(--muted)]">
        <Spinner />
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
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
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
          <StatCard label="活跃日期" value={dates.length} icon="📅" />
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

      {/* Model Management */}
      <section className="rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
        <h3 className="text-sm font-medium text-[var(--text)]">模型管理</h3>
        <p className="mt-1 text-xs text-[var(--muted)]">偏好分类模型状态与训练操作。</p>

        {/* Model cards */}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {/* XGBoost card */}
          <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
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
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">AUC</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.auc.toFixed(3)}</div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">样本数</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.n_samples.toLocaleString()}</div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">喜欢/不喜欢</div>
                  <div className="mt-0.5 text-sm text-[var(--text)]">
                    <span className="text-emerald-400">{mlModels.xgboost.n_liked.toLocaleString()}</span>
                    {' / '}
                    <span className="text-red-400">{mlModels.xgboost.n_disliked.toLocaleString()}</span>
                  </div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">特征维度</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.vocab_size.toLocaleString()}</div>
                </div>
              </div>
            ) : (
              <div className="mt-3 text-xs text-[var(--muted)]">模型文件不存在或加载失败</div>
            )}
          </div>

          {/* Vision model card */}
          <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
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
                  <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                    <div className="text-[var(--muted)]">CV AUC</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.cv_auc.toFixed(3)}</div>
                  </div>
                  <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                    <div className="text-[var(--muted)]">输入尺寸</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.input_size}px</div>
                  </div>
                  <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                    <div className="text-[var(--muted)]">样本数</div>
                    <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.n_samples.toLocaleString()}</div>
                  </div>
                  <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                    <div className="text-[var(--muted)]">模型架构</div>
                    <div className="mt-0.5 text-[11px] font-medium text-[var(--text)] truncate" title={mlModels.cnn.model_name}>{mlModels.cnn.model_name}</div>
                  </div>
                </div>
                {mlModels.cnn.fold_aucs.length > 0 && (
                  <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                    <div className="text-[var(--muted)] mb-1">Fold AUCs</div>
                    <div className="flex gap-1.5">
                      {mlModels.cnn.fold_aucs.map((auc, i) => (
                        <span key={i} className="rounded-ed-sm bg-blue-500/10 px-1.5 py-0.5 font-mono text-[10px] text-blue-300">{auc.toFixed(3)}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-3 text-xs text-[var(--muted)]">模型文件不存在或加载失败</div>
            )}
          </div>
        </div>

        {/* Multi-model selector & comparison */}
        {visionModels && Object.keys(visionModels.models).length > 0 && (
          <div className="mt-4 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-[var(--text)]">活跃模型</div>
              <select
                className="rounded-ed-sm border border-[var(--line)] bg-[var(--input-bg)] px-3 py-1.5 text-xs text-[var(--text)] focus:border-[var(--line-strong)] focus:outline-none"
                value={visionModels.active_model || ''}
                onChange={async (e) => {
                  try {
                    await setActiveModel(e.target.value)
                    const updated = await fetchVisionModels()
                    setVisionModels(updated)
                  } catch (e) { console.error('set active model failed:', e) }
                }}
              >
                {Object.entries(visionModels.models).map(([key, info]) => (
                  <option key={key} value={key}>
                    {key} — {info.model_class} (AUC: {info.cv_auc ? info.cv_auc.toFixed(3) : 'N/A'})
                  </option>
                ))}
              </select>
            </div>

            {/* Per-model comparison stats */}
            {compareStats && Object.keys(compareStats.models).length > 1 && (
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {Object.entries(compareStats.models).map(([modelName, st]) => {
                  const shortName = modelName.split('/').pop() || modelName
                  return (
                    <div key={modelName} className="rounded-ed-sm bg-[var(--surface)] p-3">
                      <div className="text-xs font-medium text-[var(--text)] truncate" title={modelName}>{shortName}</div>
                      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                        <div>
                          <div className="text-[var(--muted)]">已评分</div>
                          <div className="font-mono text-[var(--text)]">{st.total.toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-[var(--muted)]">均分</div>
                          <div className="font-mono text-[var(--text)]">{st.avg_score != null ? (st.avg_score * 100).toFixed(1) + '%' : '-'}</div>
                        </div>
                        <div>
                          <div className="text-[var(--muted)]">范围</div>
                          <div className="font-mono text-[var(--text)]">
                            {st.min_score != null ? (st.min_score * 100).toFixed(0) : '?'}–{st.max_score != null ? (st.max_score * 100).toFixed(0) : '?'}%
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Action buttons */}
        <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {/* Vision score */}
          <div>
            <button
              onClick={handleVscore}
              disabled={vscoreStatus?.running}
              className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {vscoreStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-purple-400" />
                  评分中...
                </span>
              ) : '视觉评分'}
            </button>
            {vscoreStatus && !vscoreStatus.running && vscoreStatus.finished && (
              <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${vscoreStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                {vscoreStatus.exit_code === 0 ? '评分完成' : `评分失败 (exit ${vscoreStatus.exit_code})`}
              </div>
            )}
          </div>

          {/* Pack dataset */}
          <div className="flex gap-2">
            <button
              onClick={() => handlePack()}
              disabled={packStatus?.running}
              className="flex-1 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {packStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-amber-400" />
                  打包中...
                </span>
              ) : '📦 打包训练集'}
            </button>
            <button
              onClick={() => handlePack(0)}
              disabled={packStatus?.running}
              className="flex-1 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-blue-500/60 hover:bg-blue-900/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              🖼️ 打包原图
            </button>
          </div>
          {packStatus && !packStatus.running && packStatus.finished && (
            <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${packStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
              {packStatus.exit_code === 0 ? '打包完成' : `打包失败 (exit ${packStatus.exit_code})`}
            </div>
          )}

          {/* Retrain XGBoost */}
          <div>
            <button
              onClick={handleRetrain}
              disabled={retrainStatus?.running}
              className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {retrainStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-blue-400" />
                  训练中...
                </span>
              ) : '重训 XGBoost'}
            </button>
            {retrainStatus && !retrainStatus.running && retrainStatus.finished && (
              <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${retrainStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                {retrainStatus.exit_code === 0 ? '训练完成，模型已热加载' : `训练失败 (exit ${retrainStatus.exit_code})`}
              </div>
            )}
          </div>

          {/* Tag Train (incremental sync + WD14) */}
          <div>
            <button
              onClick={handleTagTrain}
              disabled={tagTrainStatus?.running}
              className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-pink-500/60 hover:bg-pink-900/30 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {tagTrainStatus?.running ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-pink-400" />
                  打标中...
                </span>
              ) : '🏷️ 同步打标训练集'}
            </button>
            {tagTrainStatus && !tagTrainStatus.running && tagTrainStatus.finished && (
              <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${tagTrainStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                {tagTrainStatus.exit_code === 0 ? '打标完成 (GPU)' : `打标失败 (exit ${tagTrainStatus.exit_code})`}
              </div>
            )}
          </div>
        </div>

        {/* Log output */}
        {(retrainStatus?.log || packStatus?.log || vscoreStatus?.log || tagTrainStatus?.log) && (
          <div className="mt-4 space-y-3">
            {vscoreStatus?.log && (
              <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">视觉评分日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{vscoreStatus.log}</pre>
              </div>
            )}
            {packStatus?.log && (
              <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">打包日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{packStatus.log}</pre>
              </div>
            )}
            {retrainStatus?.log && (
              <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">训练日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{retrainStatus.log}</pre>
              </div>
            )}
            {tagTrainStatus?.log && (
              <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
                <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">打标日志</div>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{tagTrainStatus.log}</pre>
              </div>
            )}
          </div>
        )}
      </section>

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
    </div>
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

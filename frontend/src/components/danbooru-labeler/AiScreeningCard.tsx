import { useState, useEffect } from 'react'
import Spinner from '../Spinner'
import {
  fetchDanbooruCandidatesStats,
  fetchPrefetchStatus,
  fetchRescoreStatus,
  startPrefetch,
  stopPrefetch,
  clearDanbooruCandidates,
  fetchVisionModels,
  setActiveModel,
  startCandidatesRescore,
  type DanbooruCandidatesStats,
  type PrefetchMode,
} from '../../api'
import { getRatingMeta } from './shared'
import GpuSettingsPanel from './GpuSettingsPanel'
import ScoreHistogram from './ScoreHistogram'

export default function AiScreeningCard() {
  const [stats, setStats] = useState<DanbooruCandidatesStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [prefetchRunning, setPrefetchRunning] = useState(false)
  const [prefetchLoading, setPrefetchLoading] = useState(false)
  const [prefetchMsg, setPrefetchMsg] = useState<string | null>(null)
  const [clearing, setClearing] = useState(false)
  const [prefetchMode, setPrefetchMode] = useState<PrefetchMode>('tag+vision')
  const [prefetchThreshold, setPrefetchThreshold] = useState(55)
  const [rescoreRunning, setRescoreRunning] = useState(false)

  useEffect(() => {
    Promise.all([
      fetchDanbooruCandidatesStats().then(setStats).catch(() => {}),
      fetchPrefetchStatus().then(s => setPrefetchRunning(s.running)).catch(() => {}),
      fetchRescoreStatus().then(s => setRescoreRunning(s.running)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!prefetchRunning) return
    const id = setInterval(() => {
      fetchPrefetchStatus().then(s => setPrefetchRunning(s.running)).catch(() => {})
      fetchDanbooruCandidatesStats().then(setStats).catch(() => {})
    }, 8000)
    return () => clearInterval(id)
  }, [prefetchRunning])

  useEffect(() => {
    if (!rescoreRunning) return
    const id = setInterval(async () => {
      try {
        const s = await fetchRescoreStatus()
        if (!s.running) {
          setRescoreRunning(false)
          fetchDanbooruCandidatesStats().then(setStats).catch(() => {})
        }
      } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(id)
  }, [rescoreRunning])

  const handleToggle = async () => {
    setPrefetchLoading(true)
    setPrefetchMsg(null)
    try {
      if (prefetchRunning) {
        const res = await stopPrefetch()
        setPrefetchRunning(res.running)
      } else {
        let activeModel: string | undefined
        try {
          const models = await fetchVisionModels()
          activeModel = models.active_model || undefined
        } catch { /* fallback to server default */ }
        const res = await startPrefetch(prefetchMode, prefetchThreshold / 100, activeModel)
        setPrefetchRunning(res.running)
        if (!res.running && res.message) {
          setPrefetchMsg(res.message)
          setTimeout(() => setPrefetchMsg(null), 4000)
        }
      }
    } catch { /* ignore */ }
    setPrefetchLoading(false)
  }

  const prefetchControls = (
    <div className="flex items-center gap-2">
      {!prefetchRunning && (
        <div className="flex rounded-full border border-[var(--line)] bg-[var(--surface)] text-[11px]" role="radiogroup" aria-label="预筛选模式">
          <button
            onClick={() => setPrefetchMode('tag+vision')}
            aria-checked={prefetchMode === 'tag+vision'}
            role="radio"
            className={`rounded-l-full px-2.5 py-1 transition-all ${
              prefetchMode === 'tag+vision'
                ? 'bg-purple-500/20 text-purple-300'
                : 'text-[var(--muted)] hover:text-[var(--text)]'
            }`}
          >Tag+Vision</button>
          <button
            onClick={() => setPrefetchMode('vision-only')}
            aria-checked={prefetchMode === 'vision-only'}
            role="radio"
            className={`rounded-r-full px-2.5 py-1 transition-all ${
              prefetchMode === 'vision-only'
                ? 'bg-blue-500/20 text-blue-300'
                : 'text-[var(--muted)] hover:text-[var(--text)]'
            }`}
          >Vision Only</button>
        </div>
      )}
      {!prefetchRunning && (
        <div className="flex items-center gap-1.5 rounded-full border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5">
          <label className="text-[10px] text-[var(--muted)]" htmlFor="prefetch-threshold">阈值</label>
          <input
            id="prefetch-threshold"
            type="number"
            min={0} max={100} step={5}
            value={prefetchThreshold}
            onChange={e => setPrefetchThreshold(Math.max(0, Math.min(100, Number(e.target.value))))}
            className="w-10 bg-transparent text-center text-[11px] text-purple-300 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
          <span className="text-[10px] text-[var(--muted)]">%</span>
        </div>
      )}
      {prefetchRunning && (
        <span className="rounded border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5 text-[10px] text-[var(--muted)]">
          {prefetchMode === 'vision-only' ? '🔭 Vision Only' : '🏷 Tag+Vision'}
        </span>
      )}
      <button
        onClick={handleToggle}
        disabled={prefetchLoading}
        className={`
          flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs font-medium
          transition-all duration-200 disabled:opacity-50
          ${prefetchRunning
            ? 'border border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20'
            : 'border border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20'
          }
        `}
        aria-pressed={prefetchRunning}
      >
        {prefetchLoading ? (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
        ) : prefetchRunning ? (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" aria-hidden="true" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-red-400" aria-hidden="true" />
          </span>
        ) : (
          <span className="h-2 w-2 rounded-full bg-purple-400" aria-hidden="true" />
        )}
        {prefetchRunning ? '停止预筛选' : '开始预筛选'}
      </button>
    </div>
  )

  if (loading) {
    return (
      <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
        <div className="flex h-20 items-center justify-center">
          <Spinner size="sm" />
        </div>
      </div>
    )
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-[var(--text)]">
            <span aria-hidden="true">🤖</span> AI 预筛选
          </div>
          <div className="flex items-center gap-2">
            {prefetchControls}
          </div>
        </div>
        <p className="text-xs text-[var(--muted)]">
          {prefetchRunning ? '预筛选正在运行中，候选图片即将出现…' : '尚未运行预筛选，或候选列表为空。'}
        </p>
        {prefetchMsg && (
          <div className="mt-2 text-xs text-amber-400/80">{prefetchMsg}</div>
        )}
        <GpuSettingsPanel prefetchRunning={prefetchRunning} />
      </div>
    )
  }

  const scoreBuckets = Object.entries(stats.score_distribution).sort((a, b) => {
    const order = ['90-100%', '80-90%', '70-80%', '60-70%', '50-60%', '<50%']
    return order.indexOf(a[0]) - order.indexOf(b[0])
  })
  const maxBucket = Math.max(...scoreBuckets.map(([, v]) => v), 1)

  const bucketColors: Record<string, string> = {
    '90-100%': 'rgba(52, 211, 153, 0.8)',
    '80-90%': 'rgba(52, 211, 153, 0.6)',
    '70-80%': 'rgba(96, 165, 250, 0.7)',
    '60-70%': 'rgba(251, 191, 36, 0.6)',
    '50-60%': 'rgba(251, 191, 36, 0.4)',
    '<50%': 'rgba(248, 113, 113, 0.5)',
  }

  return (
    <div className="rounded-ed-md border border-purple-500/20 bg-[var(--panel)] editorial-panel p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-[var(--text)]">
          <span aria-hidden="true">🤖</span> AI 预筛选进度
        </div>
        <div className="flex items-center gap-3">
          {stats.vision_models && Object.keys(stats.vision_models).length > 0 && (
            <select
              className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] px-2 py-1 text-[11px] text-[var(--text)] focus:border-purple-500 focus:outline-none"
              aria-label="视觉模型"
              value={stats.active_model || ''}
              onChange={async (e) => {
                try {
                  await setActiveModel(e.target.value)
                  const updated = await fetchDanbooruCandidatesStats()
                  setStats(updated)
                } catch { /* ignore */ }
              }}
            >
              {Object.entries(stats.vision_models).map(([key, info]) => (
                <option key={key} value={key}>
                  {key} — {info.model_class} (AUC: {info.cv_auc ? (info.cv_auc * 100).toFixed(1) : 'N/A'}%)
                </option>
              ))}
            </select>
          )}
          {stats.model_loaded && (
            <span className="rounded border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-xs text-purple-300">
              XGB AUC {(stats.model_auc * 100).toFixed(1)}%
            </span>
          )}
          {prefetchControls}
          <button
            onClick={async () => {
              if (!confirm(`确定清空全部 ${stats.total.toLocaleString()} 条候选记录？扫描位置也会重置。`)) return
              setClearing(true)
              try {
                await clearDanbooruCandidates()
                setStats(await fetchDanbooruCandidatesStats())
              } catch { /* ignore */ }
              setClearing(false)
            }}
            disabled={clearing || prefetchRunning}
            className="flex items-center gap-1.5 rounded-full border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-xs text-[var(--muted)] transition-all hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
            title={prefetchRunning ? '请先停止预筛选' : '清空所有候选并重置扫描位置'}
          >
            {clearing ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
            ) : (
              <span aria-hidden="true">🗑</span>
            )}
            清空
          </button>
          <button
            onClick={async () => {
              try {
                const res = await startCandidatesRescore()
                if (res.status === 'started' || res.status === 'already_running') {
                  setRescoreRunning(true)
                }
              } catch { /* ignore */ }
            }}
            disabled={rescoreRunning || prefetchRunning}
            className="flex items-center gap-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 transition-all hover:bg-blue-500/20 disabled:opacity-40"
            title="用当前模型重新评分所有候选"
          >
            {rescoreRunning ? (
              <>
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" aria-hidden="true" />
                重评中...
              </>
            ) : (
              <><span aria-hidden="true">🧠</span> 重新评分</>
            )}
          </button>
        </div>
      </div>
      {prefetchMsg && (
        <div className="mb-3 text-xs text-amber-400/80">{prefetchMsg}</div>
      )}

      <GpuSettingsPanel prefetchRunning={prefetchRunning} />

      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-ed-sm bg-[var(--surface)] p-3 text-center">
          <div className="text-xl font-bold text-purple-400">{stats.total.toLocaleString()}</div>
          <div className="mt-0.5 text-[10px] text-[var(--muted)]">已筛选</div>
        </div>
        <div className="rounded-ed-sm bg-[var(--surface)] p-3 text-center">
          <div className="text-xl font-bold text-emerald-400">{stats.pending.toLocaleString()}</div>
          <div className="mt-0.5 text-[10px] text-[var(--muted)]">待标注</div>
        </div>
        <div className="rounded-ed-sm bg-[var(--surface)] p-3 text-center">
          <div className="text-xl font-bold text-blue-400">{(stats.avg_score * 100).toFixed(0)}%</div>
          <div className="mt-0.5 text-[10px] text-[var(--muted)]">平均分</div>
        </div>
        <div className="rounded-ed-sm bg-[var(--surface)] p-3 text-center">
          <div className="text-xl font-bold text-amber-400">{(stats.top_score * 100).toFixed(0)}%</div>
          <div className="mt-0.5 text-[10px] text-[var(--muted)]">最高分</div>
        </div>
      </div>

      {scoreBuckets.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs text-[var(--muted)]">分数分布</div>
          <div className="space-y-1.5">
            {scoreBuckets.map(([label, count]) => (
              <div key={label} className="group flex items-center gap-2">
                <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-[var(--muted)]">{label}</span>
                <div className="relative h-6 flex-1 overflow-hidden rounded-ed-sm bg-[var(--surface)]">
                  <div
                    className="absolute inset-y-0 left-0 rounded-ed-sm transition-all duration-500"
                    style={{
                      width: `${Math.max((count / maxBucket) * 100, 2)}%`,
                      backgroundColor: bucketColors[label] || 'rgba(148, 163, 184, 0.5)',
                    }}
                  />
                  <div className="relative flex h-full items-center justify-end px-2">
                    <span className="text-[11px] tabular-nums text-[var(--muted)]">{count.toLocaleString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.histogram && stats.histogram.length > 0 && stats.ci_stats && (
        <ScoreHistogram histogram={stats.histogram} ci={stats.ci_stats} />
      )}

      {Object.keys(stats.rating_distribution).length > 0 && (
        <div>
          <div className="mb-2 text-xs text-[var(--muted)]">Rating 分布</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.rating_distribution)
              .sort(([, a], [, b]) => b - a)
              .map(([rating, count]) => {
                const meta = getRatingMeta(rating)
                return (
                  <span
                    key={rating}
                    className="flex items-center gap-1.5 rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] px-2.5 py-1 text-xs"
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} aria-hidden="true" />
                    <span className="text-[var(--text)]">{meta.label}</span>
                    <span className="text-[var(--muted)]">{count.toLocaleString()}</span>
                  </span>
                )
              })}
          </div>
        </div>
      )}
    </div>
  )
}

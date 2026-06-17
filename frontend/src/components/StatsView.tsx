import { useCallback, useEffect, useState } from 'react'
import Spinner from './Spinner'
import {
  fetchStats,
  fetchAutoTagsStats,
  fetchMLModels,
  startRetrainXGBoost,
  fetchRetrainStatus,
  startPackDataset,
  fetchPackStatus,
  startVisionScore,
  fetchVisionScoreStatus,
  fetchVisionModels,
  fetchVisionScoreCompareStats,
  startTagTrain,
  fetchTagTrainStatus,
} from '../api'
import type {
  AutoTagsStats,
  MLModelsInfo,
  MLTaskStatus,
  ModelsResponse,
  CompareStatsResponse,
} from '../api'
import type { Stats } from '../types'
import { useTaskPoller } from '../hooks/useTaskPoller'
import { useToast } from '../hooks/useToast'
import ModelManagementPanel from './stats/ModelManagementPanel'
import StatsCharts from './stats/StatsCharts'

export default function StatsView() {
  const { toast } = useToast()
  const [stats, setStats] = useState<Stats | null>(null)
  const [autoTagsStats, setAutoTagsStats] = useState<AutoTagsStats | null>(null)
  const [mlModels, setMlModels] = useState<MLModelsInfo | null>(null)
  const [visionModels, setVisionModels] = useState<ModelsResponse | null>(null)
  const [compareStats, setCompareStats] = useState<CompareStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)

  // Four near-identical poll loops, now driven by a single hook.
  // Polling cadence (3000ms) and side-effects match the pre-refactor behaviour
  // exactly; only retrain has a post-completion model refresh.
  const retrain = useTaskPoller<MLTaskStatus>({
    statusFn: fetchRetrainStatus,
    label: 'retrain',
    onStop: () => {
      // Refresh model info after completion (mirrors the original pollRetrain).
      fetchMLModels().then(m => setMlModels(m)).catch(() => {})
    },
  })
  const pack = useTaskPoller<MLTaskStatus>({ statusFn: fetchPackStatus, label: 'pack' })
  const vscore = useTaskPoller<MLTaskStatus>({ statusFn: fetchVisionScoreStatus, label: 'vscore' })
  const tagTrain = useTaskPoller<MLTaskStatus>({ statusFn: fetchTagTrainStatus, label: 'tag-train' })

  useEffect(() => {
    Promise.all([
      fetchStats().then(s => setStats(s)).catch(() => {}),
      fetchAutoTagsStats().then(s => setAutoTagsStats(s)).catch(() => {}),
      fetchMLModels().then(m => setMlModels(m)).catch(() => {}),
      fetchVisionModels().then(m => setVisionModels(m)).catch(() => {}),
      fetchVisionScoreCompareStats().then(s => setCompareStats(s)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const handleRetrain = useCallback(async () => {
    try {
      const res = await startRetrainXGBoost()
      if (res.status === 'started') {
        retrain.setStatus({ running: true, finished: false, exit_code: null, log: '' })
        retrain.start()
      } else if (res.status === 'already_running') {
        retrain.start()
      }
    } catch (e) { console.error('retrain start failed:', e); toast('重训启动失败', 'error') }
  }, [retrain])

  const handleVscore = useCallback(async () => {
    try {
      const res = await startVisionScore(visionModels?.active_model || undefined)
      if (res.status === 'started') {
        toast('视觉评分已启动', 'success')
        vscore.setStatus({ running: true, finished: false, exit_code: null, log: '' })
        vscore.start()
      } else if (res.status === 'already_running') {
        vscore.start()
      }
    } catch (e) { console.error('vscore start failed:', e); toast('评分启动失败', 'error') }
  }, [vscore, visionModels?.active_model])

  const handlePack = useCallback(async (maxSize?: number) => {
    try {
      const res = await startPackDataset(maxSize)
      if (res.status === 'started') {
        pack.setStatus({ running: true, finished: false, exit_code: null, log: '' })
        pack.start()
      } else if (res.status === 'already_running') {
        pack.start()
      }
    } catch (e) { console.error('pack start failed:', e); toast('打包启动失败', 'error') }
  }, [pack])

  const handleTagTrain = useCallback(async () => {
    try {
      const res = await startTagTrain()
      if (res.status === 'started') {
        tagTrain.setStatus({ running: true, finished: false, exit_code: null, log: '' })
        tagTrain.start()
      } else if (res.status === 'already_running') {
        tagTrain.start()
      }
    } catch (e) { console.error('tag-train start failed:', e); toast('打标启动失败', 'error') }
  }, [tagTrain])

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

  const modelPanel = (
    <ModelManagementPanel
      mlModels={mlModels}
      visionModels={visionModels}
      setVisionModels={setVisionModels}
      compareStats={compareStats}
      retrainStatus={retrain.status}
      packStatus={pack.status}
      vscoreStatus={vscore.status}
      tagTrainStatus={tagTrain.status}
      onRetrain={handleRetrain}
      onVscore={handleVscore}
      onPack={handlePack}
      onTagTrain={handleTagTrain}
    />
  )

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-6">
      <StatsCharts
        stats={stats}
        autoTagsStats={autoTagsStats}
        recentDates={recentDates}
        maxDaily={maxDaily}
        avg7={avg7}
        trendPct={trendPct}
        activeDates={dates.length}
        modelPanelSlot={modelPanel}
      />
    </div>
  )
}

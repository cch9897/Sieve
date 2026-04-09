import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchDanbooruLabelerNext,
  fetchDanbooruLabelerStats,
  fetchDanbooruLabelerHistory,
  fetchDanbooruRecommended,
  fetchDanbooruCandidatesStats,
  fetchDanbooruCandidateNext,
  markDanbooruCandidate,
  danbooruLabelImage,
  danbooruUnlabelImage,
  getDanbooruExportUrl,
  fetchPrefetchStatus,
  startPrefetch,
  stopPrefetch,
  clearDanbooruCandidates,
  fetchGpuConfig,
  updateGpuConfig,
  testGpuConnection,
  fetchInferenceStatus,
  setInferenceMode,
  fetchVisionModels,
  setActiveModel,
  startCandidatesRescore,
  fetchRescoreStatus,
  type DanbooruLabelerNextResponse,
  type DanbooruLabelerStats,
  type DanbooruLabeledImage,
  type DanbooruCandidatesStats,
  type HistogramBin,
  type CIStats,
  type GpuConfig,
  type InferenceStatus,
  type InferenceMode,
  type PrefetchMode,
} from '../api'

type DanbooruReviewImage = NonNullable<DanbooruLabelerNextResponse['image']>

type LabelerTab = 'review' | 'history' | 'stats' | 'recommended'

export default function DanbooruLabeler() {
  const [tab, setTab] = useState<LabelerTab>('stats')

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      {/* Tab bar */}
      <div className="mb-6 flex items-center gap-1 rounded-2xl border border-dark-700/50 bg-dark-900/50 p-1">
        {([
          ['review', '🎯 审阅'],
          ['history', '📋 历史'],
          ['stats', '📊 统计'],
          ['recommended', '🤖 AI推荐'],
        ] as [LabelerTab, string][]).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={[
              'flex-1 rounded-xl px-4 py-2 text-sm font-medium transition-all',
              tab === key
                ? 'bg-dark-700 text-dark-50 shadow-sm'
                : 'text-dark-400 hover:text-dark-200',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'review' && <ReviewMode />}
      {tab === 'history' && <HistoryMode />}
      {tab === 'stats' && <StatsMode />}
      {tab === 'recommended' && <RecommendedMode />}
    </div>
  )
}

// ==========================================================================
// Tag category colors
// ==========================================================================

const TAG_CAT_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  artist: { bg: 'bg-red-500/20 border-red-500/30', text: 'text-red-300', label: '画师' },
  character: { bg: 'bg-emerald-500/20 border-emerald-500/30', text: 'text-emerald-300', label: '角色' },
  copyright: { bg: 'bg-purple-500/20 border-purple-500/30', text: 'text-purple-300', label: '作品' },
  general: { bg: 'bg-blue-500/20 border-blue-500/30', text: 'text-blue-300', label: '通用' },
  meta: { bg: 'bg-amber-500/20 border-amber-500/30', text: 'text-amber-300', label: '元' },
}

function TagCategoryDisplay({ tagCategories }: { tagCategories: Record<string, string[]> }) {
  const order = ['artist', 'character', 'copyright', 'general', 'meta']
  const entries = order
    .filter(cat => tagCategories[cat] && tagCategories[cat].length > 0)
    .map(cat => ({ cat, tags: tagCategories[cat] }))

  if (entries.length === 0) return null

  return (
    <div className="space-y-2">
      {entries.map(({ cat, tags }) => {
        const colors = TAG_CAT_COLORS[cat] || TAG_CAT_COLORS.general
        return (
          <div key={cat}>
            <div className={`mb-1 text-[10px] uppercase tracking-wide ${colors.text}`}>
              {colors.label} ({tags.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {tags.slice(0, 20).map(t => (
                <span
                  key={t}
                  className={`rounded border px-1.5 py-0.5 text-[11px] ${colors.bg} ${colors.text}`}
                >
                  {t.replace(/_/g, ' ')}
                </span>
              ))}
              {tags.length > 20 && (
                <span className="px-1 text-[11px] text-dark-500">+{tags.length - 20}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RatingBadge({ rating }: { rating: string }) {
  const colors: Record<string, string> = {
    s: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    q: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    e: 'bg-red-500/20 text-red-300 border-red-500/30',
    g: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  }
  const labels: Record<string, string> = { s: 'Safe', q: 'Questionable', e: 'Explicit', g: 'General' }
  return (
    <span className={`rounded border px-2 py-0.5 text-xs ${colors[rating] || 'bg-dark-700 text-dark-400 border-dark-600'}`}>
      {labels[rating] || rating}
    </span>
  )
}

// ==========================================================================
// Review Mode
// ==========================================================================

function ReviewMode() {
  const [image, setImage] = useState<DanbooruReviewImage | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [totalLabeled, setTotalLabeled] = useState(0)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [mediaFilter, setMediaFilter] = useState<'' | 'image' | 'video'>('image')
  const [ratingFilter, setRatingFilter] = useState<string>('')
  const [minScore, setMinScore] = useState<number>(0)
  const [minScoreDisplay, setMinScoreDisplay] = useState<number>(0)
  const [minAes, setMinAes] = useState<number | undefined>(undefined)
  const [minAesDisplay, setMinAesDisplay] = useState<number>(0)
  const [lastAction, setLastAction] = useState<{ imageId: number; verdict: string } | null>(null)
  const [slideDir, setSlideDir] = useState<'left' | 'right' | 'up' | ''>('')
  const [source, setSource] = useState<'random' | 'ai'>('random')
  const tagInputRef = useRef<HTMLInputElement>(null)

  const loadNext = useCallback(async () => {
    setLoading(true)
    setSlideDir('')
    setTags([])
    setTagInput('')
    try {
      let res: DanbooruLabelerNextResponse
      if (source === 'ai') {
        res = await fetchDanbooruCandidateNext({
          media: mediaFilter || undefined,
          rating: ratingFilter || undefined,
          min_score: minScore > 0 ? minScore / 100 : undefined,
          min_aes: minAes,
        })
      } else {
        res = await fetchDanbooruLabelerNext({
          media: mediaFilter || undefined,
          rating: ratingFilter || undefined,
          min_score: minScore > 0 ? minScore : undefined,
        })
      }
      setImage(res.image)
      setRemaining(res.remaining)
      setTotalLabeled(res.total_labeled)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [mediaFilter, ratingFilter, minScore, minAes, source])

  useEffect(() => { loadNext() }, [loadNext])

  const handleVerdict = useCallback(async (verdict: string) => {
    if (!image || acting) return
    setActing(true)
    const dir = verdict === 'liked' ? 'right' : verdict === 'disliked' ? 'left' : 'up'
    setSlideDir(dir)
    setLastAction({ imageId: image.id, verdict })

    try {
      await danbooruLabelImage(image.id, verdict, tags, {
        ext: image.ext,
        score: image.score,
        rating: image.rating,
        danbooru_tags: image.tags,
      })
      if (source === 'ai') {
        await markDanbooruCandidate(image.id).catch(() => {})
      }
      await new Promise(r => setTimeout(r, 300))
      await loadNext()
    } catch {
      setSlideDir('')
    } finally {
      setActing(false)
    }
  }, [image, acting, tags, loadNext, source])

  const handleUndo = useCallback(async () => {
    if (!lastAction) return
    try {
      await danbooruUnlabelImage(lastAction.imageId)
      setLastAction(null)
      await loadNext()
    } catch { /* ignore */ }
  }, [lastAction, loadNext])

  const addTag = useCallback(() => {
    const t = tagInput.trim()
    if (t && !tags.includes(t)) {
      setTags(prev => [...prev, t])
    }
    setTagInput('')
    tagInputRef.current?.focus()
  }, [tagInput, tags])

  const removeTag = (t: string) => setTags(prev => prev.filter(x => x !== t))

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      if (e.key === 'ArrowRight' || e.key === 'l' || e.key === 'L') {
        e.preventDefault()
        handleVerdict('liked')
      } else if (e.key === 'ArrowLeft' || e.key === 'h' || e.key === 'H') {
        e.preventDefault()
        handleVerdict('disliked')
      } else if (e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault()
        handleVerdict('skipped')
      } else if (e.key === 'z' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        handleUndo()
      } else if (e.key === 't' || e.key === 'T') {
        e.preventDefault()
        tagInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [handleVerdict, handleUndo])

  const total = remaining + totalLabeled
  const progress = total > 0 ? ((totalLabeled / total) * 100) : 0

  if (loading && !image) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-dark-500 border-t-blue-400" />
      </div>
    )
  }

  if (!image) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <div className="text-5xl">🎉</div>
        <h2 className="text-xl font-semibold text-dark-100">没有更多图片了！</h2>
        <p className="text-dark-400">共标注了 {totalLabeled} 张图片，试试调整筛选条件</p>
        <div className="flex gap-3">
          <a
            href={getDanbooruExportUrl('liked')}
            className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出喜欢的
          </a>
          <a
            href={getDanbooruExportUrl('liked', undefined, 0)}
            className="rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            🖼️ 原始分辨率
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-5">
      {/* Progress bar + filters */}
      <div className="w-full max-w-2xl">
        <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
          <span>已标注 {totalLabeled}</span>
          <span>剩余 ~{remaining.toLocaleString()}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-dark-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
            style={{ width: `${Math.min(progress, 100)}%` }}
          />
        </div>

        {/* Filters */}
        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
          {/* Media filter */}
          <div className="flex items-center gap-1.5">
            {(['', 'image', 'video'] as const).map(m => (
              <button
                key={m}
                onClick={() => setMediaFilter(m)}
                className={`rounded-lg px-2 py-1 transition-all ${mediaFilter === m ? 'bg-dark-700 text-blue-400' : 'text-dark-400 hover:text-dark-200'}`}
              >
                {m === '' ? '全部' : m === 'image' ? '图片' : '视频'}
              </button>
            ))}
          </div>

          <span className="text-dark-700">|</span>

          {/* Rating filter */}
          <div className="flex items-center gap-1.5">
            <span className="text-dark-500">Rating:</span>
            {(['', 'g', 's', 'q', 'e'] as const).map(r => (
              <button
                key={r}
                onClick={() => setRatingFilter(r)}
                className={`rounded-lg px-2 py-1 transition-all ${ratingFilter === r ? 'bg-dark-700 text-blue-400' : 'text-dark-400 hover:text-dark-200'}`}
              >
                {r === '' ? 'All' : r.toUpperCase()}
              </button>
            ))}
          </div>

          <span className="text-dark-700">|</span>

          {/* Min score slider */}
          <div className="flex items-center gap-2">
            <span className="text-dark-500">Score≥</span>
            <input
              type="range"
              min={0}
              max={1000}
              value={minScoreDisplay}
              onChange={e => setMinScoreDisplay(Number(e.target.value))}
              onMouseUp={e => setMinScore(Number((e.target as HTMLInputElement).value))}
              onTouchEnd={e => setMinScore(Number((e.target as HTMLInputElement).value))}
              className="h-1 w-24 appearance-none rounded-full bg-dark-700 accent-blue-500"
            />
            <span className="min-w-[3ch] text-dark-300">{minScoreDisplay}</span>
          </div>

          <span className="text-dark-700">|</span>

          {/* Source toggle */}
          <div className="flex items-center gap-1.5">
            <span className="text-dark-500">来源:</span>
            <button
              onClick={() => setSource('random')}
              className={`rounded-lg px-2 py-1 transition-all ${source === 'random' ? 'bg-dark-700 text-blue-400' : 'text-dark-400 hover:text-dark-200'}`}
            >
              🎲 随机
            </button>
            <button
              onClick={() => setSource('ai')}
              className={`rounded-lg px-2 py-1 transition-all ${source === 'ai' ? 'bg-purple-900/50 text-purple-300 ring-1 ring-purple-500/30' : 'text-dark-400 hover:text-dark-200'}`}
            >
              🤖 AI推荐
            </button>
          </div>

          {/* Aesthetic score slider — AI mode only */}
          {source === 'ai' && (
            <>
              <span className="text-dark-700">|</span>
              <div className="flex items-center gap-2">
                <span className="text-dark-500">Aes≥</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={minAesDisplay}
                  onChange={e => setMinAesDisplay(Number(e.target.value))}
                  onMouseUp={e => {
                    const v = Number((e.target as HTMLInputElement).value)
                    setMinAes(v > 0 ? v / 100 : undefined)
                  }}
                  onTouchEnd={e => {
                    const v = Number((e.target as HTMLInputElement).value)
                    setMinAes(v > 0 ? v / 100 : undefined)
                  }}
                  className="h-1 w-24 appearance-none rounded-full bg-dark-700 accent-pink-500"
                />
                <span className="min-w-[3ch] text-pink-300">{minAesDisplay}%</span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Image card */}
      <div
        className={[
          'relative w-full max-w-2xl overflow-hidden rounded-3xl border border-dark-700/50 bg-dark-900/50 transition-all duration-300',
          slideDir === 'left' ? '-translate-x-full rotate-[-8deg] opacity-0' : '',
          slideDir === 'right' ? 'translate-x-full rotate-[8deg] opacity-0' : '',
          slideDir === 'up' ? '-translate-y-full opacity-0' : '',
        ].join(' ')}
      >
        <div className="flex min-h-[50vh] items-center justify-center bg-black/20 p-2">
          {image.is_video ? (
            <video
              key={image.id}
              src={image.video_url || image.preview_url}
              className="max-h-[65vh] max-w-full rounded-2xl"
              controls
              autoPlay
              loop
              muted
            />
          ) : (
            <img
              key={image.id}
              src={image.preview_url}
              alt=""
              className="max-h-[65vh] max-w-full rounded-2xl object-contain"
              loading="eager"
              onError={async () => { if (source === 'ai' && image) { await markDanbooruCandidate(image.id).catch(() => {}); loadNext() } }}
            />
          )}
        </div>

        {/* Image info bar */}
        <div className="flex items-center justify-between border-t border-dark-700/50 px-4 py-2 text-xs text-dark-400">
          <div className="flex items-center gap-2">
            <span>#{image.id}</span>
            <RatingBadge rating={image.rating} />
            <span>Score: {image.score}</span>
            {source === 'ai' && (image as any).preference_score != null && (
              <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${
                (image as any).preference_score >= 0.8 ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-300' :
                (image as any).preference_score >= 0.5 ? 'border-amber-500/30 bg-amber-500/20 text-amber-300' :
                'border-red-500/30 bg-red-500/20 text-red-300'
              }`}>
                🤖 {((image as any).preference_score * 100).toFixed(0)}%
              </span>
            )}
            {source === 'ai' && (image as any).aesthetic_score != null && (
              <span className="rounded border border-pink-500/30 bg-pink-500/20 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-pink-300">
                🎨 {((image as any).aesthetic_score * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <span>{image.ext}</span>
        </div>

        {/* Tag categories */}
        {image.tag_categories && Object.keys(image.tag_categories).length > 0 && (
          <div className="border-t border-dark-700/50 px-4 py-3">
            <TagCategoryDisplay tagCategories={image.tag_categories} />
          </div>
        )}
      </div>

      {/* Tag input */}
      <div className="flex w-full max-w-2xl flex-wrap items-center gap-2">
        {tags.map(t => (
          <span
            key={t}
            className="inline-flex items-center gap-1 rounded-lg border border-dark-600 bg-dark-800 px-2.5 py-1 text-xs text-dark-200"
          >
            {t}
            <button onClick={() => removeTag(t)} className="text-dark-500 hover:text-red-400">×</button>
          </span>
        ))}
        <div className="flex flex-1 items-center gap-2">
          <input
            ref={tagInputRef}
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); addTag() }
              if (e.key === 'Escape') { setTagInput(''); (e.target as HTMLElement).blur() }
            }}
            placeholder="添加标签… (T 聚焦, Enter 确认)"
            className="min-w-[160px] flex-1 rounded-lg border border-dark-700 bg-dark-900 px-3 py-1.5 text-sm text-dark-100 placeholder:text-dark-600 focus:border-blue-500/50 focus:outline-none"
          />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => handleVerdict('disliked')}
          disabled={acting}
          className="group flex h-16 w-16 items-center justify-center rounded-full border-2 border-red-500/30 bg-red-500/10 text-2xl transition-all hover:border-red-400 hover:bg-red-500/20 hover:scale-110 active:scale-95 disabled:opacity-50"
          title="不喜欢 (← / H)"
        >
          <span className="transition-transform group-hover:scale-110">👎</span>
        </button>

        <button
          onClick={() => handleVerdict('skipped')}
          disabled={acting}
          className="group flex h-12 w-12 items-center justify-center rounded-full border-2 border-dark-600/50 bg-dark-800/50 text-lg transition-all hover:border-dark-500 hover:bg-dark-700 hover:scale-110 active:scale-95 disabled:opacity-50"
          title="跳过 (↓ / Space)"
        >
          <span className="transition-transform group-hover:scale-110">⏭</span>
        </button>

        <button
          onClick={() => handleVerdict('liked')}
          disabled={acting}
          className="group flex h-16 w-16 items-center justify-center rounded-full border-2 border-emerald-500/30 bg-emerald-500/10 text-2xl transition-all hover:border-emerald-400 hover:bg-emerald-500/20 hover:scale-110 active:scale-95 disabled:opacity-50"
          title="喜欢 (→ / L)"
        >
          <span className="transition-transform group-hover:scale-110">👍</span>
        </button>
      </div>

      {/* Undo + shortcuts hint */}
      <div className="flex items-center gap-4 text-xs text-dark-500">
        {lastAction && (
          <button onClick={handleUndo} className="text-blue-400 hover:text-blue-300">
            ↩ 撤销上一个
          </button>
        )}
        <span>← 不喜欢 · ↓ 跳过 · → 喜欢 · T 标签 · Ctrl+Z 撤销</span>
      </div>
    </div>
  )
}

// ==========================================================================
// History Mode
// ==========================================================================

function HistoryMode() {
  const [images, setImages] = useState<DanbooruLabeledImage[]>([])
  const [loading, setLoading] = useState(true)
  const [verdict, setVerdict] = useState<string>('liked')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [selected, setSelected] = useState<DanbooruLabeledImage | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchDanbooruLabelerHistory({ verdict, page, per_page: 60 })
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
    } catch { /* ignore */ }
    setLoading(false)
  }, [verdict, page])

  useEffect(() => { load() }, [load])

  const handleRelabel = useCallback(async (img: DanbooruLabeledImage, newVerdict: string) => {
    if (acting) return
    setActing(true)
    try {
      await danbooruLabelImage(img.id, newVerdict, img.tags || [], {
        ext: img.ext,
        score: img.score,
        rating: img.rating,
        danbooru_tags: img.danbooru_tags,
      })
      if (newVerdict !== verdict) {
        setImages(prev => prev.filter(i => i.id !== img.id))
        setTotal(t => t - 1)
      } else {
        setImages(prev => prev.map(i => i.id === img.id ? { ...i, verdict: newVerdict } : i))
      }
      setSelected(null)
    } catch { /* ignore */ }
    setActing(false)
  }, [acting, verdict])

  const handleRemoveLabel = useCallback(async (img: DanbooruLabeledImage) => {
    if (acting) return
    setActing(true)
    try {
      await danbooruUnlabelImage(img.id)
      setImages(prev => prev.filter(i => i.id !== img.id))
      setTotal(t => t - 1)
      setSelected(null)
    } catch { /* ignore */ }
    setActing(false)
  }, [acting])

  const selectedIndex = selected ? images.findIndex(i => i.id === selected.id) : -1
  const goPrev = useCallback(() => {
    if (selectedIndex > 0) setSelected(images[selectedIndex - 1])
  }, [selectedIndex, images])
  const goNext = useCallback(() => {
    if (selectedIndex >= 0 && selectedIndex < images.length - 1) setSelected(images[selectedIndex + 1])
  }, [selectedIndex, images])

  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setSelected(null); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev() }
      if (e.key === 'ArrowRight') { e.preventDefault(); goNext() }
      if (e.key === 'l' || e.key === 'L') { e.preventDefault(); handleRelabel(selected, 'liked') }
      if (e.key === 'h' || e.key === 'H') { e.preventDefault(); handleRelabel(selected, 'disliked') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, goPrev, goNext, handleRelabel])

  return (
    <div>
      {/* Filter tabs */}
      <div className="mb-4 flex items-center gap-2">
        {[
          ['liked', '👍 喜欢'],
          ['disliked', '👎 不喜欢'],
          ['skipped', '⏭ 跳过'],
        ].map(([key, label]) => (
          <button
            key={key}
            onClick={() => { setVerdict(key); setPage(1); setSelected(null) }}
            className={[
              'rounded-xl px-4 py-2 text-sm transition-all',
              verdict === key
                ? 'bg-dark-700 text-dark-50'
                : 'text-dark-400 hover:text-dark-200',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-dark-500">{total} 张</span>

        {verdict === 'liked' && total > 0 && (<>
          <a
            href={getDanbooruExportUrl('liked')}
            className="rounded-xl bg-emerald-600/80 px-4 py-2 text-sm text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出 ZIP
          </a>
          <a
            href={getDanbooruExportUrl('liked', undefined, 0)}
            className="rounded-xl bg-blue-600/80 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-500"
          >
            🖼️ 原图
          </a>
        </>)}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-dark-500 border-t-blue-400" />
        </div>
      ) : images.length === 0 ? (
        <div className="py-20 text-center text-dark-500">还没有标注过的图片</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {images.map(img => (
              <div
                key={img.id}
                onClick={() => setSelected(img)}
                className="group relative cursor-pointer overflow-hidden rounded-2xl border border-dark-700/50 bg-dark-900/30 transition-all hover:border-dark-500 hover:shadow-lg"
              >
                <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                {/* Score + Rating overlay */}
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 p-2">
                  <div className="flex items-center justify-between">
                    <RatingBadge rating={img.rating} />
                    <span className="text-[11px] text-white/70">★ {img.score}</span>
                  </div>
                </div>
                {img.vision_score != null && (
                  <div className="absolute right-1.5 top-1.5 rounded px-1 py-0.5 font-mono text-[10px] font-medium backdrop-blur-sm"
                    style={{
                      background: img.vision_score >= 0.7 ? 'rgba(16,185,129,0.4)' : img.vision_score >= 0.4 ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.4)',
                      color: 'rgba(255,255,255,0.9)',
                    }}
                  >
                    🧠{(img.vision_score * 100).toFixed(0)}%
                  </div>
                )}
                <div className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition-all group-hover:bg-black/30 group-hover:opacity-100">
                  <span className="text-2xl drop-shadow-lg">🔍</span>
                </div>
              </div>
            ))}
          </div>

          {pages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-sm text-dark-300 disabled:opacity-30"
              >
                上一页
              </button>
              <span className="text-sm text-dark-400">{page} / {pages}</span>
              <button
                disabled={page >= pages}
                onClick={() => setPage(p => p + 1)}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-sm text-dark-300 disabled:opacity-30"
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail / Re-label Modal */}
      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
          onClick={() => setSelected(null)}
        >
          <button
            onClick={() => setSelected(null)}
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-black/40 text-2xl text-white/70 hover:bg-black/60 hover:text-white"
          >
            &times;
          </button>

          {selectedIndex > 0 && (
            <button
              onClick={e => { e.stopPropagation(); goPrev() }}
              className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 hover:bg-black/60 hover:text-white"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}
          {selectedIndex < images.length - 1 && (
            <button
              onClick={e => { e.stopPropagation(); goNext() }}
              className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 hover:bg-black/60 hover:text-white"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}

          <div
            className="flex max-h-[92vh] w-full max-w-5xl flex-col gap-4 lg:flex-row"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex flex-1 items-center justify-center rounded-3xl border border-white/10 bg-black/30 p-2">
              {selected.is_video ? (
                <video
                  key={selected.id}
                  src={selected.video_url || selected.preview_url}
                  className="max-h-[75vh] max-w-full rounded-2xl"
                  controls autoPlay loop
                />
              ) : (
                <img
                  key={selected.id}
                  src={selected.preview_url}
                  alt=""
                  className="max-h-[75vh] max-w-full rounded-2xl object-contain"
                />
              )}
            </div>

            <aside className="flex w-full flex-col justify-between overflow-y-auto rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-md lg:w-80">
              <div className="space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">当前标记</div>
                  <div className="mt-1 text-sm">
                    {selected.verdict === 'liked' && <span className="text-emerald-400">👍 喜欢</span>}
                    {selected.verdict === 'disliked' && <span className="text-red-400">👎 不喜欢</span>}
                    {selected.verdict === 'skipped' && <span className="text-dark-400">⏭ 跳过</span>}
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">信息</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-white/80">
                    <span>#{selected.id}</span>
                    <RatingBadge rating={selected.rating} />
                    <span>Score: {selected.score}</span>
                  </div>
                </div>

                {selected.vision_score != null && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">视觉评分</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
                        <div
                          className={[
                            'h-full rounded-full',
                            selected.vision_score >= 0.7 ? 'bg-emerald-500' : selected.vision_score >= 0.4 ? 'bg-amber-500' : 'bg-red-500',
                          ].join(' ')}
                          style={{ width: `${(selected.vision_score * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <span className="font-mono text-sm text-white/80">{(selected.vision_score * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                )}

                {/* Danbooru tags from stored data */}
                {selected.danbooru_tags && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">Danbooru Tags</div>
                    <div className="mt-1 flex max-h-40 flex-wrap gap-1 overflow-y-auto">
                      {selected.danbooru_tags.split(' ').filter(Boolean).slice(0, 30).map(t => (
                        <span key={t} className="rounded border border-blue-500/20 bg-blue-500/10 px-1.5 py-0.5 text-[11px] text-blue-300">
                          {t.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {selected.tags && selected.tags.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">自定义标签</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selected.tags.map(t => (
                        <span key={t} className="rounded-lg bg-dark-700 px-2 py-0.5 text-xs text-dark-200">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 space-y-2">
                <div className="mb-2 text-xs text-white/40">重新标记</div>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    onClick={() => handleRelabel(selected, 'liked')}
                    disabled={acting || selected.verdict === 'liked'}
                    className={[
                      'rounded-xl py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'liked'
                        ? 'border border-emerald-500/50 bg-emerald-500/20 text-emerald-300'
                        : 'border border-white/10 bg-white/5 text-white/70 hover:bg-emerald-500/20 hover:text-emerald-300',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👍
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'disliked')}
                    disabled={acting || selected.verdict === 'disliked'}
                    className={[
                      'rounded-xl py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'disliked'
                        ? 'border border-red-500/50 bg-red-500/20 text-red-300'
                        : 'border border-white/10 bg-white/5 text-white/70 hover:bg-red-500/20 hover:text-red-300',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👎
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'skipped')}
                    disabled={acting || selected.verdict === 'skipped'}
                    className={[
                      'rounded-xl py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'skipped'
                        ? 'border border-dark-500/50 bg-dark-500/20 text-dark-300'
                        : 'border border-white/10 bg-white/5 text-white/70 hover:bg-dark-500/20 hover:text-dark-300',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    ⏭
                  </button>
                </div>
                <button
                  onClick={() => handleRemoveLabel(selected)}
                  disabled={acting}
                  className="w-full rounded-xl border border-white/10 bg-white/5 py-2 text-xs text-white/50 transition-colors hover:bg-red-500/10 hover:text-red-300"
                >
                  🗑 移除标记（放回未审阅）
                </button>

                <div className="pt-2 text-center text-[10px] text-white/30">
                  {selectedIndex + 1} / {images.length} · ← → 切换 · H/L 标记 · Esc 关闭
                </div>
              </div>
            </aside>
          </div>
        </div>
      )}
    </div>
  )
}

// ==========================================================================
// Stats Mode
// ==========================================================================

const RATING_META: Record<string, { label: string; color: string }> = {
  g: { label: 'General', color: '#60a5fa' },
  s: { label: 'Safe', color: '#34d399' },
  q: { label: 'Questionable', color: '#fbbf24' },
  e: { label: 'Explicit', color: '#f87171' },
}

function getRatingMeta(r: string) {
  return RATING_META[r] || { label: r, color: '#94a3b8' }
}

function GpuSettingsPanel({ prefetchRunning }: { prefetchRunning: boolean }) {
  const [infStatus, setInfStatus] = useState<InferenceStatus | null>(null)
  const [gpu, setGpu] = useState<GpuConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [batchInput, setBatchInput] = useState(16)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    Promise.all([
      fetchInferenceStatus().then(setInfStatus).catch(() => {}),
      fetchGpuConfig().then(cfg => {
        setGpu(cfg)
        setUrlInput(cfg.url)
        setBatchInput(cfg.batch_size)
      }).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const handleModeSwitch = async (mode: InferenceMode) => {
    setSwitching(true)
    setSwitchError('')
    try {
      const res = await setInferenceMode(mode)
      setInfStatus(prev => prev ? { ...prev, inference_mode: res.inference_mode, current_device: res.current_device, cuda_info: res.cuda_info } : prev)
      // Sync gpu config state
      fetchGpuConfig().then(cfg => { setGpu(cfg); setUrlInput(cfg.url); setBatchInput(cfg.batch_size) }).catch(() => {})
    } catch (e: any) {
      setSwitchError(e?.message || '切换失败')
    }
    setSwitching(false)
  }

  const handleSaveRemote = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      const updated = await updateGpuConfig({ url: urlInput, batch_size: batchInput })
      setGpu({ ...updated, remote_health: gpu?.remote_health ?? null })
    } catch { /* ignore */ }
    setSaving(false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      await updateGpuConfig({ url: urlInput, batch_size: batchInput })
      const res = await testGpuConnection()
      if (res.ok) {
        const h = res.health
        setTestResult({
          ok: true,
          msg: `✅ 连接成功 · ${h?.model_name || '?'} · ${h?.device || '?'}${h?.fp16 ? ' · FP16' : ''}`
            + (h?.cv_auc ? ` · AUC ${(h.cv_auc * 100).toFixed(1)}%` : '')
            + (h?.gpu_memory_mb ? ` · ${h.gpu_memory_mb.toFixed(0)}MB` : ''),
        })
        fetchGpuConfig().then(setGpu).catch(() => {})
      } else {
        setTestResult({ ok: false, msg: `❌ ${res.error || '连接失败'}` })
      }
    } catch (e: any) {
      setTestResult({ ok: false, msg: `❌ ${e?.message || '请求失败'}` })
    }
    setTesting(false)
  }

  if (loading) return null

  const currentMode = infStatus?.inference_mode || 'cpu'

  const modeOptions: { key: InferenceMode; label: string; icon: string; desc: string; color: string; disabledReason?: string }[] = [
    { key: 'cpu', label: 'CPU', icon: '🖥', desc: '本机 CPU 推理', color: 'blue' },
    {
      key: 'local_gpu',
      label: '本地 GPU',
      icon: '🎮',
      desc: infStatus?.cuda_info ? `${infStatus.cuda_info.device_name} · ${infStatus.cuda_info.total_memory_mb}MB` : 'CUDA 设备',
      color: 'emerald',
      disabledReason: !infStatus?.cuda_available ? 'CUDA 不可用' : undefined,
    },
    { key: 'remote', label: '远程 GPU', icon: '🌐', desc: gpu?.url || '未配置', color: 'purple' },
  ]

  return (
    <div className="mt-3 rounded-xl border border-dark-700/30 bg-dark-950/50 p-3">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between text-xs text-dark-400 hover:text-dark-200 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span>⚡</span>
          <span>推理模式</span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] ${
            currentMode === 'local_gpu' ? 'bg-emerald-500/20 text-emerald-300' :
            currentMode === 'remote' ? 'bg-purple-500/20 text-purple-300' :
            'bg-blue-500/20 text-blue-300'
          }`}>
            {currentMode === 'local_gpu' ? '🎮 本地 GPU' : currentMode === 'remote' ? '🌐 远程' : '🖥 CPU'}
          </span>
          {infStatus?.current_device === 'cuda' && infStatus?.cuda_info && (
            <span className="text-[10px] text-dark-500">
              {infStatus.cuda_info.device_name} · {infStatus.cuda_info.allocated_mb}MB used
            </span>
          )}
        </div>
        <svg
          className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20" fill="currentColor"
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {/* Mode selector */}
          <div className="grid grid-cols-3 gap-2">
            {modeOptions.map(opt => {
              const active = currentMode === opt.key
              const disabled = switching || !!opt.disabledReason
              return (
                <button
                  key={opt.key}
                  onClick={() => !active && !disabled && handleModeSwitch(opt.key)}
                  disabled={disabled}
                  className={[
                    'relative rounded-xl border p-3 text-left transition-all',
                    active
                      ? `border-${opt.color}-500/50 bg-${opt.color}-500/10 ring-1 ring-${opt.color}-500/20`
                      : 'border-dark-700/50 bg-dark-900/30 hover:border-dark-500/70',
                    disabled && !active ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
                  ].join(' ')}
                  title={opt.disabledReason || ''}
                >
                  {switching && currentMode !== opt.key && !active && (
                    <span className="absolute right-2 top-2 h-3 w-3 animate-spin rounded-full border-2 border-dark-500 border-t-transparent" />
                  )}
                  <div className="text-base">{opt.icon}</div>
                  <div className={`mt-1 text-xs font-medium ${active ? 'text-dark-100' : 'text-dark-300'}`}>{opt.label}</div>
                  <div className="mt-0.5 text-[10px] text-dark-500 truncate">{opt.disabledReason || opt.desc}</div>
                  {active && (
                    <div className={`absolute right-2 top-2 h-2 w-2 rounded-full bg-${opt.color}-400`} />
                  )}
                </button>
              )
            })}
          </div>

          {switching && (
            <div className="flex items-center gap-2 text-xs text-dark-400">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-dark-500 border-t-blue-400" />
              模型迁移中…
            </div>
          )}

          {switchError && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-300">
              ❌ {switchError}
            </div>
          )}

          {/* CUDA device info */}
          {infStatus?.cuda_available && infStatus.cuda_info && (
            <div className="rounded-lg border border-dark-700/30 bg-dark-900/30 px-3 py-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-dark-500">CUDA 设备</span>
                <span className="text-dark-300">{infStatus.cuda_info.device_name}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px]">
                <span className="text-dark-500">显存</span>
                <span className="text-dark-300">{infStatus.cuda_info.allocated_mb}MB / {infStatus.cuda_info.total_memory_mb}MB</span>
              </div>
              {infStatus.cnn_loaded && (
                <div className="mt-1 flex items-center justify-between text-[11px]">
                  <span className="text-dark-500">当前设备</span>
                  <span className={`font-mono ${infStatus.current_device === 'cuda' ? 'text-emerald-400' : 'text-blue-400'}`}>{infStatus.current_device}</span>
                </div>
              )}
            </div>
          )}

          {/* Remote GPU config — only show when remote mode */}
          {currentMode === 'remote' && (
            <div className="space-y-2 rounded-lg border border-purple-500/10 bg-purple-500/5 p-3">
              <div className="text-[11px] font-medium text-purple-300/80">远程 GPU 服务器配置</div>
              <div className="flex items-center gap-2">
                <label className="shrink-0 text-xs text-dark-500 w-14">地址</label>
                <input
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  placeholder="http://192.168.x.x:5099"
                  className="flex-1 rounded-lg border border-dark-700 bg-dark-900 px-3 py-1.5 text-sm text-dark-100 placeholder:text-dark-600 focus:border-purple-500/50 focus:outline-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="shrink-0 text-xs text-dark-500 w-14">Batch</label>
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={batchInput}
                  onChange={e => setBatchInput(Number(e.target.value))}
                  className="w-20 rounded-lg border border-dark-700 bg-dark-900 px-3 py-1.5 text-sm text-dark-100 focus:border-purple-500/50 focus:outline-none"
                />
                <span className="text-[10px] text-dark-600">张/请求 (1-64)</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveRemote}
                  disabled={saving}
                  className="rounded-lg border border-dark-600 bg-dark-800 px-3 py-1.5 text-xs text-dark-300 transition-all hover:bg-dark-700 hover:text-dark-100 disabled:opacity-50"
                >
                  {saving ? '保存中…' : '💾 保存'}
                </button>
                <button
                  onClick={handleTest}
                  disabled={testing || !urlInput}
                  className="rounded-lg border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-300 transition-all hover:bg-purple-500/20 disabled:opacity-50"
                >
                  {testing ? (
                    <span className="flex items-center gap-1.5">
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      测试中…
                    </span>
                  ) : '🔌 测试连接'}
                </button>
              </div>
              {testResult && (
                <div className={`rounded-lg px-3 py-2 text-xs ${
                  testResult.ok
                    ? 'border border-emerald-500/20 bg-emerald-500/5 text-emerald-300'
                    : 'border border-red-500/20 bg-red-500/5 text-red-300'
                }`}>
                  {testResult.msg}
                </div>
              )}
            </div>
          )}

          {prefetchRunning && (
            <div className="text-[10px] text-amber-400/70">
              ⚠ 预筛选正在运行，模式切换将在下次启动时生效
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Score distribution histogram with 95% CI, IQR, and key percentiles */
function ScoreHistogram({ histogram, ci }: { histogram: HistogramBin[]; ci: CIStats }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<{ x: number; text: string } | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const dpr = window.devicePixelRatio || 1
    const width = container.offsetWidth
    const height = 200
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)

    const pad = { top: 24, right: 16, bottom: 32, left: 44 }
    const plotW = width - pad.left - pad.right
    const plotH = height - pad.top - pad.bottom

    const maxCount = Math.max(...histogram.map(b => b.count), 1)

    // Clear
    ctx.clearRect(0, 0, width, height)

    // Helper: score → x
    const sx = (v: number) => pad.left + v * plotW
    // Helper: count → y
    const cy = (c: number) => pad.top + plotH - (c / maxCount) * plotH

    // Draw IQR shaded region (p25-p75)
    ctx.fillStyle = 'rgba(139, 92, 246, 0.08)'
    ctx.fillRect(sx(ci.p25), pad.top, sx(ci.p75) - sx(ci.p25), plotH)

    // Draw 95% CI band
    ctx.fillStyle = 'rgba(52, 211, 153, 0.15)'
    ctx.fillRect(sx(ci.ci95_lo), pad.top, sx(ci.ci95_hi) - sx(ci.ci95_lo), plotH)

    // Draw histogram bars (stacked: accepted on top, rejected on bottom)
    const binW = plotW / histogram.length
    histogram.forEach((bin, i) => {
      if (bin.count === 0) return
      const x = pad.left + i * binW

      // Rejected portion (bottom, muted)
      if (bin.rejected > 0) {
        const rejH = (bin.rejected / maxCount) * plotH
        const rejY = pad.top + plotH - rejH
        ctx.fillStyle = 'rgba(100, 116, 139, 0.35)'
        ctx.fillRect(x + 0.5, rejY, binW - 1, rejH)
      }

      // Accepted portion (stacked on top of rejected)
      if (bin.accepted > 0) {
        const totalH = (bin.count / maxCount) * plotH
        const accH = (bin.accepted / maxCount) * plotH
        const accY = pad.top + plotH - totalH // top of full bar

        const score = (bin.lo + bin.hi) / 2
        let color: string
        if (score >= 0.8) color = 'rgba(52, 211, 153, 0.75)'
        else if (score >= 0.6) color = 'rgba(96, 165, 250, 0.65)'
        else if (score >= 0.4) color = 'rgba(251, 191, 36, 0.55)'
        else color = 'rgba(248, 113, 113, 0.5)'

        ctx.fillStyle = color
        ctx.fillRect(x + 0.5, accY, binW - 1, accH)
      }
    })

    // Mean line
    ctx.strokeStyle = 'rgba(251, 191, 36, 0.9)'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 3])
    const mx = sx(ci.mean)
    ctx.beginPath()
    ctx.moveTo(mx, pad.top)
    ctx.lineTo(mx, pad.top + plotH)
    ctx.stroke()
    ctx.setLineDash([])

    // Median line
    ctx.strokeStyle = 'rgba(139, 92, 246, 0.9)'
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    const medX = sx(ci.median)
    ctx.beginPath()
    ctx.moveTo(medX, pad.top)
    ctx.lineTo(medX, pad.top + plotH)
    ctx.stroke()
    ctx.setLineDash([])

    // P10 / P90 ticks
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)'
    ctx.lineWidth = 1
    ctx.setLineDash([2, 4])
    for (const p of [ci.p10, ci.p90]) {
      const px = sx(p)
      ctx.beginPath()
      ctx.moveTo(px, pad.top)
      ctx.lineTo(px, pad.top + plotH)
      ctx.stroke()
    }
    ctx.setLineDash([])

    // X-axis labels
    ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
    ctx.font = '10px system-ui, sans-serif'
    ctx.textAlign = 'center'
    for (let v = 0; v <= 1; v += 0.2) {
      const x = sx(v)
      ctx.fillText(`${(v * 100).toFixed(0)}%`, x, height - 8)
      // Tick
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)'
      ctx.beginPath()
      ctx.moveTo(x, pad.top + plotH)
      ctx.lineTo(x, pad.top + plotH + 4)
      ctx.stroke()
    }

    // Y-axis labels
    ctx.textAlign = 'right'
    ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
    const yTicks = 4
    for (let i = 0; i <= yTicks; i++) {
      const val = Math.round((maxCount / yTicks) * i)
      const y = cy(val)
      ctx.fillText(val.toLocaleString(), pad.left - 6, y + 3)
      // Grid line
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.06)'
      ctx.beginPath()
      ctx.moveTo(pad.left, y)
      ctx.lineTo(width - pad.right, y)
      ctx.stroke()
    }
  }, [histogram, ci])

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const pad = { left: 44, right: 16 }
    const plotW = container.offsetWidth - pad.left - pad.right
    const relX = (x - pad.left) / plotW
    if (relX < 0 || relX > 1) { setTooltip(null); return }
    const binIdx = Math.min(Math.floor(relX * histogram.length), histogram.length - 1)
    const bin = histogram[binIdx]
    const parts = [`${(bin.lo * 100).toFixed(0)}-${(bin.hi * 100).toFixed(0)}%: ${bin.count} 张`]
    if (bin.accepted > 0 || bin.rejected > 0) {
      parts.push(`✓${bin.accepted} ✗${bin.rejected}`)
    }
    setTooltip({
      x: e.clientX - rect.left,
      text: parts.join(' · '),
    })
  }

  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs text-dark-500">分数分布直方图</div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-dark-500">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(96, 165, 250, 0.65)' }} /> 入选
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(100, 116, 139, 0.35)' }} /> 未入选
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3" style={{ background: 'rgba(251, 191, 36, 0.9)' }} /> 均值 {(ci.mean * 100).toFixed(1)}%
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3" style={{ background: 'rgba(139, 92, 246, 0.9)', borderTop: '1px dashed' }} /> 中位数 {(ci.median * 100).toFixed(1)}%
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(52, 211, 153, 0.15)' }} /> 95% CI
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(139, 92, 246, 0.08)' }} /> IQR
          </span>
        </div>
      </div>
      <div ref={containerRef} className="relative">
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setTooltip(null)}
          className="w-full cursor-crosshair"
        />
        {tooltip && (
          <div
            className="pointer-events-none absolute top-1 z-10 rounded-md border border-dark-600/50 bg-dark-800/95 px-2 py-1 text-[11px] text-dark-200 shadow-lg backdrop-blur"
            style={{ left: Math.min(Math.max(tooltip.x - 50, 0), (containerRef.current?.offsetWidth || 300) - 110) }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
      {/* Summary row */}
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-dark-500">
        <span>σ = {(ci.std * 100).toFixed(1)}%</span>
        <span>P10 = {(ci.p10 * 100).toFixed(0)}%</span>
        <span>P90 = {(ci.p90 * 100).toFixed(0)}%</span>
        <span>n = {ci.n.toLocaleString()}</span>
      </div>
    </div>
  )
}

function AiScreeningCard() {
  const [stats, setStats] = useState<DanbooruCandidatesStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [prefetchRunning, setPrefetchRunning] = useState(false)
  const [prefetchLoading, setPrefetchLoading] = useState(false)
  const [prefetchMsg, setPrefetchMsg] = useState<string | null>(null)
  const [clearing, setClearing] = useState(false)
  const [prefetchMode, setPrefetchMode] = useState<PrefetchMode>('tag+vision')
  const [prefetchThreshold, setPrefetchThreshold] = useState(55)  // 0-100, default 55%
  const [rescoreRunning, setRescoreRunning] = useState(false)

  useEffect(() => {
    Promise.all([
      fetchDanbooruCandidatesStats().then(setStats).catch(() => {}),
      fetchPrefetchStatus().then(s => setPrefetchRunning(s.running)).catch(() => {}),
      fetchRescoreStatus().then(s => setRescoreRunning(s.running)).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  // Poll while running
  useEffect(() => {
    if (!prefetchRunning) return
    const id = setInterval(() => {
      fetchPrefetchStatus().then(s => setPrefetchRunning(s.running)).catch(() => {})
      fetchDanbooruCandidatesStats().then(setStats).catch(() => {})
    }, 8000)
    return () => clearInterval(id)
  }, [prefetchRunning])

  // Poll rescore status
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
        // Fetch active vision model to pass to prefetch
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

  if (loading) {
    return (
      <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
        <div className="flex h-20 items-center justify-center">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-dark-500 border-t-purple-400" />
        </div>
      </div>
    )
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-dark-300">
            <span>🤖</span> AI 预筛选
          </div>
          <div className="flex items-center gap-2">
            {!prefetchRunning && (
              <div className="flex rounded-full border border-dark-600/50 bg-dark-800/50 text-[11px]">
                <button
                  onClick={() => setPrefetchMode('tag+vision')}
                  className={`rounded-l-full px-2.5 py-1 transition-all ${
                    prefetchMode === 'tag+vision'
                      ? 'bg-purple-500/20 text-purple-300'
                      : 'text-dark-500 hover:text-dark-300'
                  }`}
                >Tag+Vision</button>
                <button
                  onClick={() => setPrefetchMode('vision-only')}
                  className={`rounded-r-full px-2.5 py-1 transition-all ${
                    prefetchMode === 'vision-only'
                      ? 'bg-blue-500/20 text-blue-300'
                      : 'text-dark-500 hover:text-dark-300'
                  }`}
                >Vision Only</button>
              </div>
            )}
            {!prefetchRunning && (
              <div className="flex items-center gap-1.5 rounded-full border border-dark-600/50 bg-dark-800/50 px-2 py-0.5">
                <span className="text-[10px] text-dark-500">阈值</span>
                <input
                  type="number"
                  min={0} max={100} step={5}
                  value={prefetchThreshold}
                  onChange={e => setPrefetchThreshold(Math.max(0, Math.min(100, Number(e.target.value))))}
                  className="w-10 bg-transparent text-center text-[11px] text-purple-300 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
                />
                <span className="text-[10px] text-dark-500">%</span>
              </div>
            )}
            {prefetchRunning && (
              <span className="rounded border border-dark-600/40 bg-dark-800/40 px-2 py-0.5 text-[10px] text-dark-400">
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
            >
              {prefetchLoading ? (
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : prefetchRunning ? (
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-red-400" />
                </span>
              ) : (
                <span className="h-2 w-2 rounded-full bg-purple-400" />
              )}
              {prefetchRunning ? '停止预筛选' : '开始预筛选'}
            </button>
          </div>
        </div>
        <p className="text-xs text-dark-500">
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
    // Sort by bucket label descending (90-100% first)
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
    <div className="rounded-2xl border border-purple-500/20 bg-dark-900/50 p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-dark-300">
          <span>🤖</span> AI 预筛选进度
        </div>
        <div className="flex items-center gap-3">
          {stats.vision_models && Object.keys(stats.vision_models).length > 0 && (
            <select
              className="rounded-lg border border-dark-600/50 bg-dark-800/50 px-2 py-1 text-[11px] text-dark-200 focus:border-purple-500 focus:outline-none"
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
          {/* Mode selector */}
          {!prefetchRunning && (
            <div className="flex rounded-full border border-dark-600/50 bg-dark-800/50 text-[11px]">
              <button
                onClick={() => setPrefetchMode('tag+vision')}
                className={`rounded-l-full px-2.5 py-1 transition-all ${
                  prefetchMode === 'tag+vision'
                    ? 'bg-purple-500/20 text-purple-300'
                    : 'text-dark-500 hover:text-dark-300'
                }`}
              >Tag+Vision</button>
              <button
                onClick={() => setPrefetchMode('vision-only')}
                className={`rounded-r-full px-2.5 py-1 transition-all ${
                  prefetchMode === 'vision-only'
                    ? 'bg-blue-500/20 text-blue-300'
                    : 'text-dark-500 hover:text-dark-300'
                }`}
              >Vision Only</button>
            </div>
          )}
          {!prefetchRunning && (
            <div className="flex items-center gap-1.5 rounded-full border border-dark-600/50 bg-dark-800/50 px-2 py-0.5">
              <span className="text-[10px] text-dark-500">阈值</span>
              <input
                type="number"
                min={0} max={100} step={5}
                value={prefetchThreshold}
                onChange={e => setPrefetchThreshold(Math.max(0, Math.min(100, Number(e.target.value))))}
                className="w-10 bg-transparent text-center text-[11px] text-purple-300 outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
              />
              <span className="text-[10px] text-dark-500">%</span>
            </div>
          )}
          {prefetchRunning && (
            <span className="rounded border border-dark-600/40 bg-dark-800/40 px-2 py-0.5 text-[10px] text-dark-400">
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
          >
            {prefetchLoading ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : prefetchRunning ? (
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-400 opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-red-400" />
              </span>
            ) : (
              <span className="h-2 w-2 rounded-full bg-purple-400" />
            )}
            {prefetchRunning ? '停止预筛选' : '开始预筛选'}
          </button>
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
            className="flex items-center gap-1.5 rounded-full border border-dark-600/50 bg-dark-800/50 px-3 py-1.5 text-xs text-dark-400 transition-all hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300 disabled:opacity-40"
            title={prefetchRunning ? '请先停止预筛选' : '清空所有候选并重置扫描位置'}
          >
            {clearing ? (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
            ) : (
              <span>🗑</span>
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
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                重评中...
              </>
            ) : (
              <>🧠 重新评分</>
            )}
          </button>
        </div>
      </div>
      {prefetchMsg && (
        <div className="mb-3 text-xs text-amber-400/80">{prefetchMsg}</div>
      )}

      <GpuSettingsPanel prefetchRunning={prefetchRunning} />

      {/* Quick stats */}
      <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl bg-dark-800/50 p-3 text-center">
          <div className="text-xl font-bold text-purple-400">{stats.total.toLocaleString()}</div>
          <div className="mt-0.5 text-[10px] text-dark-500">已筛选</div>
        </div>
        <div className="rounded-xl bg-dark-800/50 p-3 text-center">
          <div className="text-xl font-bold text-emerald-400">{stats.pending.toLocaleString()}</div>
          <div className="mt-0.5 text-[10px] text-dark-500">待标注</div>
        </div>
        <div className="rounded-xl bg-dark-800/50 p-3 text-center">
          <div className="text-xl font-bold text-blue-400">{(stats.avg_score * 100).toFixed(0)}%</div>
          <div className="mt-0.5 text-[10px] text-dark-500">平均分</div>
        </div>
        <div className="rounded-xl bg-dark-800/50 p-3 text-center">
          <div className="text-xl font-bold text-amber-400">{(stats.top_score * 100).toFixed(0)}%</div>
          <div className="mt-0.5 text-[10px] text-dark-500">最高分</div>
        </div>
      </div>

      {/* Score distribution */}
      {scoreBuckets.length > 0 && (
        <div className="mb-4">
          <div className="mb-2 text-xs text-dark-500">分数分布</div>
          <div className="space-y-1.5">
            {scoreBuckets.map(([label, count]) => (
              <div key={label} className="group flex items-center gap-2">
                <span className="w-16 shrink-0 text-right text-[11px] tabular-nums text-dark-400">{label}</span>
                <div className="relative h-6 flex-1 overflow-hidden rounded-lg bg-dark-800/50">
                  <div
                    className="absolute inset-y-0 left-0 rounded-lg transition-all duration-500"
                    style={{
                      width: `${Math.max((count / maxBucket) * 100, 2)}%`,
                      backgroundColor: bucketColors[label] || 'rgba(148, 163, 184, 0.5)',
                    }}
                  />
                  <div className="relative flex h-full items-center justify-end px-2">
                    <span className="text-[11px] tabular-nums text-dark-300">{count.toLocaleString()}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Score histogram with confidence interval */}
      {stats.histogram && stats.histogram.length > 0 && stats.ci_stats && (
        <ScoreHistogram histogram={stats.histogram} ci={stats.ci_stats} />
      )}

      {/* Rating distribution */}
      {Object.keys(stats.rating_distribution).length > 0 && (
        <div>
          <div className="mb-2 text-xs text-dark-500">Rating 分布</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.rating_distribution)
              .sort(([, a], [, b]) => b - a)
              .map(([rating, count]) => {
                const meta = getRatingMeta(rating)
                return (
                  <span
                    key={rating}
                    className="flex items-center gap-1.5 rounded-lg border border-dark-700/50 bg-dark-800/50 px-2.5 py-1 text-xs"
                  >
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: meta.color }} />
                    <span className="text-dark-300">{meta.label}</span>
                    <span className="text-dark-500">{count.toLocaleString()}</span>
                  </span>
                )
              })}
          </div>
        </div>
      )}
    </div>
  )
}

function StatsMode() {
  const [stats, setStats] = useState<DanbooruLabelerStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDanbooruLabelerStats().then(setStats).catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading || !stats) {
    return (
      <div className="flex h-40 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-dark-500 border-t-blue-400" />
      </div>
    )
  }

  const statCards = [
    { label: '数据库总量', value: stats.total_images, color: 'text-dark-100' },
    { label: '已标注', value: stats.total_labeled, color: 'text-blue-400' },
    { label: '喜欢', value: stats.liked, color: 'text-emerald-400' },
    { label: '不喜欢', value: stats.disliked, color: 'text-red-400' },
    { label: '跳过', value: stats.skipped, color: 'text-dark-400' },
    { label: '剩余', value: stats.remaining, color: 'text-amber-400' },
  ]

  const likeRate = stats.total_labeled > 0
    ? ((stats.liked / (stats.liked + stats.disliked || 1)) * 100).toFixed(1)
    : '0'

  return (
    <div className="space-y-6">
      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map(s => (
          <div key={s.label} className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-4 text-center">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value.toLocaleString()}</div>
            <div className="mt-1 text-xs text-dark-500">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Like rate */}
      <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
        <div className="mb-3 text-sm text-dark-300">喜欢率</div>
        <div className="flex items-end gap-3">
          <span className="text-3xl font-bold text-emerald-400">{likeRate}%</span>
          <span className="mb-1 text-sm text-dark-500">
            ({stats.liked} / {stats.liked + stats.disliked})
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-dark-800">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${likeRate}%` }} />
        </div>
      </div>

      {/* Progress */}
      <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
        <div className="mb-3 text-sm text-dark-300">标注进度</div>
        <div className="h-3 overflow-hidden rounded-full bg-dark-800">
          <div
            className="flex h-full"
            style={{ width: `${stats.total_images > 0 ? (stats.total_labeled / stats.total_images * 100) : 0}%` }}
          >
            <div className="h-full bg-emerald-500" style={{ width: `${stats.liked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-red-500" style={{ width: `${stats.disliked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-dark-600" style={{ width: `${stats.skipped / (stats.total_labeled || 1) * 100}%` }} />
          </div>
        </div>
        <div className="mt-2 flex gap-4 text-xs text-dark-500">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" />不喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-dark-600" />跳过</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-dark-800" />未标注</span>
        </div>
      </div>

      {/* AI Pre-screening progress */}
      <AiScreeningCard />

      {/* Rating stats: two columns */}
      {stats.liked > 0 && Object.keys(stats.liked_by_rating || {}).length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Left: liked rating composition */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">👍 喜欢 Rating 占比</div>
            <p className="mb-4 text-xs text-dark-500">喜欢的图片中，各 Rating 贡献了多少。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_rating)
                .sort(([, a], [, b]) => b - a)
                .map(([rating, count]) => {
                  const meta = getRatingMeta(rating)
                  const pct = ((count / stats.liked) * 100).toFixed(1)
                  return (
                    <div key={rating} className="group rounded-2xl border border-dark-700/50 bg-dark-950/60 p-3 transition-colors hover:border-dark-600/70">
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
                          style={{ width: `${(count / stats.liked) * 100}%`, backgroundColor: meta.color }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>

          {/* Right: per-rating like rate */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">📊 Rating 喜欢率</div>
            <p className="mb-4 text-xs text-dark-500">各 Rating 已审阅图片中，被喜欢的比例。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_rating)
                .map(([rating, likedCount]) => {
                  const labeledCount = (stats.labeled_by_rating || {})[rating] || 0
                  const rate = labeledCount > 0 ? (likedCount / labeledCount) * 100 : 0
                  return { rating, likedCount, labeledCount, rate }
                })
                .sort((a, b) => b.rate - a.rate)
                .map(({ rating, likedCount, labeledCount, rate }) => {
                  const meta = getRatingMeta(rating)
                  return (
                    <div key={rating} className="group rounded-2xl border border-dark-700/50 bg-dark-950/60 p-3 transition-colors hover:border-dark-600/70">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2 text-dark-200">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
                          <span>{meta.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold" style={{ color: meta.color }}>{rate.toFixed(1)}%</span>
                          <span className="text-xs text-dark-500">{likedCount}/{labeledCount}</span>
                        </div>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-dark-800">
                        <div
                          className="h-full rounded-full transition-all duration-500 group-hover:brightness-110"
                          style={{ width: `${rate}%`, backgroundColor: meta.color }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>
        </div>
      )}

      {/* Liked danbooru tags ranking — bar chart */}
      {(stats.liked_top_danbooru_tags || []).length > 0 && (() => {
        const tags = stats.liked_top_danbooru_tags.slice(0, 30)
        const maxCount = tags[0]?.count || 1
        return (
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">👍 喜欢标签排名</div>
            <p className="mb-4 text-xs text-dark-500">标记为喜欢的图片中，Danbooru 标签出现频率 Top 30。</p>
            <div className="space-y-1.5">
              {tags.map((t, i) => {
                const barPct = (t.count / maxCount) * 100
                const opacity = Math.max(0.3, 1 - i * 0.023)
                return (
                  <div key={t.tag} className="group flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-[10px] tabular-nums text-dark-600">{i + 1}</span>
                    <div className="relative flex-1 h-7 rounded-lg overflow-hidden bg-dark-800/50">
                      <div
                        className="absolute inset-y-0 left-0 rounded-lg transition-all duration-500 group-hover:brightness-125"
                        style={{
                          width: `${Math.max(barPct, 2)}%`,
                          backgroundColor: `rgba(96, 165, 250, ${opacity})`,
                        }}
                      />
                      <div className="relative flex h-full items-center justify-between px-2.5">
                        <span className="text-xs text-dark-100 drop-shadow-sm">{t.tag.replace(/_/g, ' ')}</span>
                        <span className="text-[11px] tabular-nums text-dark-300">{t.count}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      {/* User tags */}
      {stats.top_tags.length > 0 && (
        <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
          <div className="mb-3 text-sm text-dark-300">常用自定义标签</div>
          <div className="flex flex-wrap gap-2">
            {stats.top_tags.map(t => (
              <span
                key={t.tag}
                className="rounded-lg border border-dark-600 bg-dark-800 px-3 py-1.5 text-sm text-dark-200"
              >
                {t.tag} <span className="text-dark-500">×{t.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Export */}
      {(stats.liked > 0 || stats.disliked > 0) && (
        <div className="flex justify-center gap-3 flex-wrap">
          {stats.liked > 0 && (
            <a
              href={getDanbooruExportUrl('liked')}
              className="rounded-2xl bg-emerald-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
            >
              📦 导出喜欢 ({stats.liked} 张)
            </a>
          )}
          {stats.liked > 0 && (
            <a
              href={getDanbooruExportUrl('liked', undefined, 0)}
              className="rounded-2xl bg-blue-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              🖼️ 喜欢原图
            </a>
          )}
          {stats.disliked > 0 && (
            <a
              href={getDanbooruExportUrl('disliked')}
              className="rounded-2xl bg-red-600/80 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-red-500"
            >
              📦 导出不喜欢 ({stats.disliked} 张)
            </a>
          )}
          {stats.disliked > 0 && (
            <a
              href={getDanbooruExportUrl('disliked', undefined, 0)}
              className="rounded-2xl bg-orange-600/80 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-orange-500"
            >
              🖼️ 不喜欢原图
            </a>
          )}
        </div>
      )}
    </div>
  )
}

// ==========================================================================
// AI Recommended Mode
// ==========================================================================

function ScoreBadge({ score }: { score: number }) {
  const pct = (score * 100).toFixed(0)
  const color =
    score >= 0.8 ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' :
    score >= 0.5 ? 'bg-amber-500/20 text-amber-300 border-amber-500/30' :
    'bg-red-500/20 text-red-300 border-red-500/30'
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${color}`}>
      {pct}%
    </span>
  )
}

function RecommendedMode() {
  const [images, setImages] = useState<(DanbooruLabeledImage & { preference_score: number })[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [minScore, setMinScore] = useState(0.5)
  const [minScoreDisplay, setMinScoreDisplay] = useState(50)
  const [ratingFilter, setRatingFilter] = useState('')
  const [modelInfo, setModelInfo] = useState<{ auc: number; n_samples: number; model_type: string } | null>(null)
  const [selected, setSelected] = useState<(DanbooruLabeledImage & { preference_score: number }) | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetchDanbooruRecommended({
        page,
        per_page: 24,
        min_score: minScore,
        rating: ratingFilter || undefined,
      })
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
      setModelInfo(res.model_info)
    } catch (e: any) {
      setError(e?.message || '加载失败')
    }
    setLoading(false)
  }, [page, minScore, ratingFilter])

  useEffect(() => { load() }, [load])

  const handleLabel = useCallback(async (img: DanbooruLabeledImage & { preference_score: number }, verdict: string) => {
    if (acting) return
    setActing(true)
    try {
      await danbooruLabelImage(img.id, verdict, [], {
        ext: img.ext,
        score: img.score,
        rating: img.rating,
        danbooru_tags: img.danbooru_tags,
      })
      // Remove from list after labeling
      setImages(prev => prev.filter(i => i.id !== img.id))
      setTotal(t => t - 1)
      if (selected?.id === img.id) setSelected(null)
    } catch { /* ignore */ }
    setActing(false)
  }, [acting, selected])

  const selectedIndex = selected ? images.findIndex(i => i.id === selected.id) : -1
  const goPrev = useCallback(() => {
    if (selectedIndex > 0) setSelected(images[selectedIndex - 1])
  }, [selectedIndex, images])
  const goNext = useCallback(() => {
    if (selectedIndex >= 0 && selectedIndex < images.length - 1) setSelected(images[selectedIndex + 1])
  }, [selectedIndex, images])

  // Keyboard nav in modal
  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setSelected(null); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); goPrev() }
      if (e.key === 'ArrowRight') { e.preventDefault(); goNext() }
      if (e.key === 'l' || e.key === 'L') { e.preventDefault(); handleLabel(selected, 'liked') }
      if (e.key === 'h' || e.key === 'H') { e.preventDefault(); handleLabel(selected, 'disliked') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, goPrev, goNext, handleLabel])

  return (
    <div className="space-y-5">
      {/* Model info banner */}
      {modelInfo && (
        <div className="flex items-center gap-4 rounded-2xl border border-purple-500/20 bg-purple-500/5 px-5 py-3">
          <span className="text-2xl">🤖</span>
          <div className="flex-1">
            <div className="text-sm font-medium text-purple-300">AI 偏好预测</div>
            <div className="text-xs text-dark-400">
              {modelInfo.model_type} · AUC {(modelInfo.auc * 100).toFixed(1)}% · 训练样本 {modelInfo.n_samples.toLocaleString()}
            </div>
          </div>
          <button
            onClick={() => { setPage(1); load() }}
            className="rounded-xl border border-purple-500/30 bg-purple-500/10 px-4 py-1.5 text-sm text-purple-300 transition-colors hover:bg-purple-500/20"
          >
            🔄 刷新
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-4 text-xs">
        {/* Min score slider */}
        <div className="flex items-center gap-2">
          <span className="text-dark-400">最低分数:</span>
          <input
            type="range"
            min={0}
            max={100}
            value={minScoreDisplay}
            onChange={e => setMinScoreDisplay(Number(e.target.value))}
            onMouseUp={() => { setMinScore(minScoreDisplay / 100); setPage(1) }}
            onTouchEnd={() => { setMinScore(minScoreDisplay / 100); setPage(1) }}
            className="h-1 w-32 appearance-none rounded-full bg-dark-700 accent-purple-500"
          />
          <span className="min-w-[3ch] text-sm font-medium text-purple-300">{minScoreDisplay}%</span>
        </div>

        <span className="text-dark-700">|</span>

        {/* Rating filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-dark-400">Rating:</span>
          {(['', 'g', 's', 'q', 'e'] as const).map(r => (
            <button
              key={r}
              onClick={() => { setRatingFilter(r); setPage(1) }}
              className={`rounded-lg px-2 py-1 transition-all ${ratingFilter === r ? 'bg-dark-700 text-purple-400' : 'text-dark-400 hover:text-dark-200'}`}
            >
              {r === '' ? 'All' : r.toUpperCase()}
            </button>
          ))}
        </div>

        <span className="ml-auto text-dark-500">
          {total} 张推荐
        </span>
      </div>

      {/* Error state */}
      {error && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-5 text-center text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-dark-500 border-t-purple-400" />
        </div>
      ) : images.length === 0 && !error ? (
        <div className="py-20 text-center text-dark-500">
          没有找到推荐图片，试试降低最低分数
        </div>
      ) : (
        <>
          {/* Image grid */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {images.map(img => (
              <div
                key={img.id}
                className="group relative cursor-pointer overflow-hidden rounded-2xl border border-dark-700/50 bg-dark-900/30 transition-all hover:border-dark-500 hover:shadow-lg"
              >
                <div onClick={() => setSelected(img)}>
                  <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                  {/* Overlays */}
                  <div className="absolute left-2 top-2">
                    <ScoreBadge score={img.preference_score} />
                  </div>
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 p-2">
                    <div className="flex items-center justify-between">
                      <RatingBadge rating={img.rating} />
                      <span className="text-[11px] text-white/70">★ {img.score}</span>
                    </div>
                  </div>
                </div>
                {/* Quick action buttons */}
                <div className="absolute right-1 top-1 flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    onClick={(e) => { e.stopPropagation(); handleLabel(img, 'liked') }}
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/80 text-sm shadow-lg transition-transform hover:scale-110"
                    title="喜欢"
                  >
                    👍
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleLabel(img, 'disliked') }}
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/80 text-sm shadow-lg transition-transform hover:scale-110"
                    title="不喜欢"
                  >
                    👎
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Pagination */}
          {pages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-sm text-dark-300 disabled:opacity-30"
              >
                上一页
              </button>
              <span className="text-sm text-dark-400">{page} / {pages}</span>
              <button
                disabled={page >= pages}
                onClick={() => setPage(p => p + 1)}
                className="rounded-lg border border-dark-700 px-3 py-1.5 text-sm text-dark-300 disabled:opacity-30"
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}

      {/* Detail modal */}
      {selected && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4"
          onClick={() => setSelected(null)}
        >
          <button
            onClick={() => setSelected(null)}
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-black/40 text-2xl text-white/70 hover:bg-black/60 hover:text-white"
          >
            &times;
          </button>

          {selectedIndex > 0 && (
            <button
              onClick={e => { e.stopPropagation(); goPrev() }}
              className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 hover:bg-black/60 hover:text-white"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}
          {selectedIndex < images.length - 1 && (
            <button
              onClick={e => { e.stopPropagation(); goNext() }}
              className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 hover:bg-black/60 hover:text-white"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}

          <div
            className="flex max-h-[92vh] w-full max-w-5xl flex-col gap-4 lg:flex-row"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex flex-1 items-center justify-center rounded-3xl border border-white/10 bg-black/30 p-2">
              {selected.is_video ? (
                <video
                  key={selected.id}
                  src={selected.video_url || selected.preview_url}
                  className="max-h-[75vh] max-w-full rounded-2xl"
                  controls autoPlay loop
                />
              ) : (
                <img
                  key={selected.id}
                  src={selected.preview_url}
                  alt=""
                  className="max-h-[75vh] max-w-full rounded-2xl object-contain"
                />
              )}
            </div>

            <aside className="flex w-full flex-col justify-between overflow-y-auto rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-md lg:w-80">
              <div className="space-y-4">
                {/* Preference score */}
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">AI 偏好分数</div>
                  <div className="mt-2 flex items-center gap-3">
                    <ScoreBadge score={selected.preference_score} />
                    <div className="flex-1">
                      <div className="h-2 overflow-hidden rounded-full bg-dark-800">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${selected.preference_score * 100}%`,
                            backgroundColor: selected.preference_score >= 0.8 ? '#34d399' : selected.preference_score >= 0.5 ? '#fbbf24' : '#f87171',
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">信息</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-white/80">
                    <span>#{selected.id}</span>
                    <RatingBadge rating={selected.rating} />
                    <span>Score: {selected.score}</span>
                  </div>
                </div>

                {/* Danbooru tags */}
                {selected.danbooru_tags && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">Danbooru Tags</div>
                    <div className="mt-1 flex max-h-40 flex-wrap gap-1 overflow-y-auto">
                      {selected.danbooru_tags.split(' ').filter(Boolean).slice(0, 30).map(t => (
                        <span key={t} className="rounded border border-blue-500/20 bg-blue-500/10 px-1.5 py-0.5 text-[11px] text-blue-300">
                          {t.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 space-y-2">
                <div className="mb-2 text-xs text-white/40">标记</div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => handleLabel(selected, 'liked')}
                    disabled={acting}
                    className="rounded-xl border border-white/10 bg-white/5 py-2.5 text-sm font-medium text-white/70 transition-all hover:bg-emerald-500/20 hover:text-emerald-300 disabled:opacity-50"
                  >
                    👍 喜欢
                  </button>
                  <button
                    onClick={() => handleLabel(selected, 'disliked')}
                    disabled={acting}
                    className="rounded-xl border border-white/10 bg-white/5 py-2.5 text-sm font-medium text-white/70 transition-all hover:bg-red-500/20 hover:text-red-300 disabled:opacity-50"
                  >
                    👎 不喜欢
                  </button>
                </div>
                <div className="pt-2 text-center text-[10px] text-white/30">
                  {selectedIndex + 1} / {images.length} · ← → 切换 · H/L 标记 · Esc 关闭
                </div>
              </div>
            </aside>
          </div>
        </div>
      )}
    </div>
  )
}

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchLabelerNext,
  fetchLabelerStats,
  fetchLabelerHistory,
  labelImage,
  unlabelImage,
  getExportUrl,
  type LabelerNextResponse,
  type LabelerStats,
  type LabeledImage,
} from '../api'
import { getSourceMeta } from '../sourceMeta'

type ReviewImage = NonNullable<LabelerNextResponse['image']>

type LabelerTab = 'review' | 'history' | 'stats'

export default function Labeler() {
  const [tab, setTab] = useState<LabelerTab>('stats')

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      {/* Tab bar */}
      <div className="mb-6 flex items-center gap-1 rounded-2xl border border-dark-700/50 bg-dark-900/50 p-1">
        {([
          ['review', '🎯 审阅'],
          ['history', '📋 历史'],
          ['stats', '📊 统计'],
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
    </div>
  )
}

// ==========================================================================
// Review Mode - Tinder-style one-by-one
// ==========================================================================

function ReviewMode() {
  const [image, setImage] = useState<ReviewImage | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [totalLabeled, setTotalLabeled] = useState(0)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [mediaFilter, setMediaFilter] = useState<'' | 'image' | 'video'>('')
  const [lastAction, setLastAction] = useState<{ imageId: number; verdict: string } | null>(null)
  const [slideDir, setSlideDir] = useState<'left' | 'right' | 'up' | ''>('')
  const tagInputRef = useRef<HTMLInputElement>(null)

  const loadNext = useCallback(async () => {
    setLoading(true)
    setSlideDir('')
    setTags([])
    setTagInput('')
    try {
      const res = await fetchLabelerNext({ media: mediaFilter || undefined })
      setImage(res.image)
      setRemaining(res.remaining)
      setTotalLabeled(res.total_labeled)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [mediaFilter])

  useEffect(() => { loadNext() }, [loadNext])

  const handleVerdict = useCallback(async (verdict: string) => {
    if (!image || acting) return
    setActing(true)
    const dir = verdict === 'liked' ? 'right' : verdict === 'disliked' ? 'left' : 'up'
    setSlideDir(dir)
    setLastAction({ imageId: image.id, verdict })

    try {
      await labelImage(image.id, verdict, tags)
      // Wait for animation
      await new Promise(r => setTimeout(r, 300))
      await loadNext()
    } catch {
      setSlideDir('')
    } finally {
      setActing(false)
    }
  }, [image, acting, tags, loadNext])

  const handleUndo = useCallback(async () => {
    if (!lastAction) return
    try {
      await unlabelImage(lastAction.imageId)
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

  // Progress
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
        <h2 className="text-xl font-semibold text-dark-100">全部审阅完了！</h2>
        <p className="text-dark-400">共标注了 {totalLabeled} 张图片</p>
        <div className="flex gap-3">
          <a
            href={getExportUrl('liked')}
            className="rounded-xl bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出喜欢的
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
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
      {/* Progress bar */}
      <div className="w-full max-w-2xl">
        <div className="mb-2 flex items-center justify-between text-xs text-dark-400">
          <span>已标注 {totalLabeled} / {total}</span>
          <div className="flex gap-3">
            {(['', 'image', 'video'] as const).map(m => (
              <button
                key={m}
                onClick={() => setMediaFilter(m)}
                className={mediaFilter === m ? 'text-blue-400' : 'hover:text-dark-200'}
              >
                {m === '' ? '全部' : m === 'image' ? '图片' : '视频'}
              </button>
            ))}
          </div>
          <span>剩余 {remaining}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-dark-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
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
              src={`/images/${image.file_path}`}
              className="max-h-[65vh] max-w-full rounded-2xl"
              controls
              autoPlay
              loop
              muted
            />
          ) : (
            <img
              key={image.id}
              src={`/images/${image.file_path}`}
              alt=""
              className="max-h-[65vh] max-w-full rounded-2xl object-contain"
              loading="eager"
            />
          )}
        </div>

        {/* Image info bar */}
        <div className="flex items-center justify-between border-t border-dark-700/50 px-4 py-2 text-xs text-dark-400">
          <span>{image.source} · {image.source_id}</span>
          <div className="flex items-center gap-3">
            {image.vision_score != null && (
              <span
                className={[
                  'rounded-md px-1.5 py-0.5 font-mono text-[11px] font-medium',
                  image.vision_score >= 0.7
                    ? 'bg-emerald-500/20 text-emerald-400'
                    : image.vision_score >= 0.4
                      ? 'bg-amber-500/20 text-amber-400'
                      : 'bg-red-500/20 text-red-400',
                ].join(' ')}
                title="视觉模型评分"
              >
                🧠 {(image.vision_score * 100).toFixed(1)}%
              </span>
            )}
            <span>{image.date}</span>
          </div>
        </div>
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
// History Mode - browse labeled images
// ==========================================================================

function HistoryMode() {
  const [images, setImages] = useState<LabeledImage[]>([])
  const [loading, setLoading] = useState(true)
  const [verdict, setVerdict] = useState<string>('liked')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [selected, setSelected] = useState<LabeledImage | null>(null)
  const [acting, setActing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchLabelerHistory({ verdict, page, per_page: 60 })
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
    } catch { /* ignore */ }
    setLoading(false)
  }, [verdict, page])

  useEffect(() => { load() }, [load])

  const handleRelabel = useCallback(async (img: LabeledImage, newVerdict: string) => {
    if (acting) return
    setActing(true)
    try {
      await labelImage(img.id, newVerdict, img.tags || [])
      // Remove from current list if verdict changed
      if (newVerdict !== verdict) {
        setImages(prev => prev.filter(i => i.id !== img.id))
        setTotal(t => t - 1)
      } else {
        // Update in place
        setImages(prev => prev.map(i => i.id === img.id ? { ...i, verdict: newVerdict } : i))
      }
      setSelected(null)
    } catch { /* ignore */ }
    setActing(false)
  }, [acting, verdict])

  const handleRemoveLabel = useCallback(async (img: LabeledImage) => {
    if (acting) return
    setActing(true)
    try {
      await unlabelImage(img.id)
      setImages(prev => prev.filter(i => i.id !== img.id))
      setTotal(t => t - 1)
      setSelected(null)
    } catch { /* ignore */ }
    setActing(false)
  }, [acting])

  // Navigate between images in detail view
  const selectedIndex = selected ? images.findIndex(i => i.id === selected.id) : -1
  const goPrev = useCallback(() => {
    if (selectedIndex > 0) setSelected(images[selectedIndex - 1])
  }, [selectedIndex, images])
  const goNext = useCallback(() => {
    if (selectedIndex >= 0 && selectedIndex < images.length - 1) setSelected(images[selectedIndex + 1])
  }, [selectedIndex, images])

  // Keyboard for detail modal
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
            href={getExportUrl('liked')}
            className="rounded-xl bg-emerald-600/80 px-4 py-2 text-sm text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出 ZIP
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
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
                {img.is_video ? (
                  <video src={`/images/${img.file_path}`} className="aspect-square w-full object-cover" muted />
                ) : (
                  <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                )}
                {img.tags && img.tags.length > 0 && (
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 p-2">
                    <div className="flex flex-wrap gap-1">
                      {img.tags.map(t => (
                        <span key={t} className="rounded bg-white/20 px-1.5 py-0.5 text-[10px] text-white/80">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
                {/* Vision score badge */}
                {img.vision_score != null && (
                  <div className="absolute right-1.5 top-1.5 rounded px-1 py-0.5 font-mono text-[10px] font-medium backdrop-blur-sm"
                    style={{
                      background: img.vision_score >= 0.7 ? 'rgba(16,185,129,0.4)' : img.vision_score >= 0.4 ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.4)',
                      color: 'rgba(255,255,255,0.9)',
                    }}
                  >
                    {(img.vision_score * 100).toFixed(0)}%
                  </div>
                )}
                {/* Hover overlay */}
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
          {/* Close */}
          <button
            onClick={() => setSelected(null)}
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-black/40 text-2xl text-white/70 hover:bg-black/60 hover:text-white"
          >
            &times;
          </button>

          {/* Nav arrows */}
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
            {/* Image */}
            <div className="flex flex-1 items-center justify-center rounded-3xl border border-white/10 bg-black/30 p-2">
              {selected.is_video ? (
                <video
                  key={selected.id}
                  src={`/images/${selected.file_path}`}
                  className="max-h-[75vh] max-w-full rounded-2xl"
                  controls autoPlay loop
                />
              ) : (
                <img
                  key={selected.id}
                  src={`/images/${selected.file_path}`}
                  alt=""
                  className="max-h-[75vh] max-w-full rounded-2xl object-contain"
                />
              )}
            </div>

            {/* Side panel */}
            <aside className="flex w-full flex-col justify-between rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-md lg:w-72">
              <div className="space-y-4">
                {/* Current verdict */}
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">当前标记</div>
                  <div className="mt-1 text-sm">
                    {selected.verdict === 'liked' && <span className="text-emerald-400">👍 喜欢</span>}
                    {selected.verdict === 'disliked' && <span className="text-red-400">👎 不喜欢</span>}
                    {selected.verdict === 'skipped' && <span className="text-dark-400">⏭ 跳过</span>}
                  </div>
                </div>

                {/* Info */}
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">来源</div>
                  <div className="mt-1 text-sm text-white/80">{selected.source} · {selected.source_id}</div>
                </div>

                {selected.date && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">日期</div>
                    <div className="mt-1 text-sm text-white/70">{selected.date}</div>
                  </div>
                )}

                {selected.vision_scores && Object.keys(selected.vision_scores).length > 0 ? (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">视觉评分</div>
                    <div className="mt-1.5 space-y-1.5">
                      {Object.entries(selected.vision_scores).map(([model, score]) => (
                        <div key={model} className="flex items-center gap-2">
                          <span className="w-28 truncate text-[11px] text-white/50" title={model}>
                            {model.replace(/^.*\//, '').slice(0, 20)}
                          </span>
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
                            <div
                              className={[
                                'h-full rounded-full',
                                score >= 0.7 ? 'bg-emerald-500' : score >= 0.4 ? 'bg-amber-500' : 'bg-red-500',
                              ].join(' ')}
                              style={{ width: `${(score * 100).toFixed(1)}%` }}
                            />
                          </div>
                          <span className="w-12 text-right font-mono text-xs text-white/80">{(score * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : selected.vision_score != null ? (
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
                ) : null}

                {/* Tags */}
                {selected.tags && selected.tags.length > 0 && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-white/40">标签</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selected.tags.map(t => (
                        <span key={t} className="rounded-lg bg-dark-700 px-2 py-0.5 text-xs text-dark-200">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Re-label actions */}
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

function StatsMode() {
  const [stats, setStats] = useState<LabelerStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchLabelerStats().then(setStats).catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading || !stats) {
    return (
      <div className="flex h-40 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-dark-500 border-t-blue-400" />
      </div>
    )
  }

  const statCards = [
    { label: '总图片', value: stats.total_images, color: 'text-dark-100' },
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
          <div
            className="h-full rounded-full bg-emerald-500"
            style={{ width: `${likeRate}%` }}
          />
        </div>
      </div>

      {/* Progress */}
      <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
        <div className="mb-3 text-sm text-dark-300">标注进度</div>
        <div className="h-3 overflow-hidden rounded-full bg-dark-800">
          <div
            className="flex h-full"
            style={{ width: `${(stats.total_labeled / stats.total_images * 100)}%` }}
          >
            <div
              className="h-full bg-emerald-500"
              style={{ width: `${stats.liked / (stats.total_labeled || 1) * 100}%` }}
            />
            <div
              className="h-full bg-red-500"
              style={{ width: `${stats.disliked / (stats.total_labeled || 1) * 100}%` }}
            />
            <div
              className="h-full bg-dark-600"
              style={{ width: `${stats.skipped / (stats.total_labeled || 1) * 100}%` }}
            />
          </div>
        </div>
        <div className="mt-2 flex gap-4 text-xs text-dark-500">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" />不喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-dark-600" />跳过</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-dark-800" />未标注</span>
        </div>
      </div>

      {/* Top tags */}
      {stats.top_tags.length > 0 && (
        <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
          <div className="mb-3 text-sm text-dark-300">常用标签</div>
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

      {/* Source stats: two columns */}
      {stats.liked > 0 && Object.keys(stats.liked_by_source || {}).length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Left: liked composition */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">👍 喜欢来源占比</div>
            <p className="mb-4 text-xs text-dark-500">喜欢的图片中，各站点贡献了多少。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_source)
                .sort(([, a], [, b]) => b - a)
                .map(([source, count]) => {
                  const meta = getSourceMeta(source)
                  const pct = ((count / stats.liked) * 100).toFixed(1)
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
                            width: `${(count / stats.liked) * 100}%`,
                            backgroundColor: meta.color,
                          }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>

          {/* Right: per-source like rate */}
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">📊 站点喜欢率</div>
            <p className="mb-4 text-xs text-dark-500">各站点已审阅图片中，被喜欢的比例。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_source)
                .map(([source, likedCount]) => {
                  const labeledCount = (stats.labeled_by_source || {})[source] || 0
                  const rate = labeledCount > 0 ? (likedCount / labeledCount) * 100 : 0
                  return { source, likedCount, labeledCount, rate }
                })
                .sort((a, b) => b.rate - a.rate)
                .map(({ source, likedCount, labeledCount, rate }) => {
                  const meta = getSourceMeta(source)
                  return (
                    <div key={source} className="group rounded-2xl border border-dark-700/50 bg-dark-950/60 p-3 transition-colors hover:border-dark-600/70">
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
                          style={{
                            width: `${rate}%`,
                            backgroundColor: meta.color,
                          }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>
        </div>
      )}

      {/* Liked auto-tag ranking — horizontal bar chart */}
      {(stats.liked_top_auto_tags || []).length > 0 && (() => {
        const tags = stats.liked_top_auto_tags.slice(0, 30)
        const maxCount = tags[0]?.count || 1
        return (
          <div className="rounded-2xl border border-dark-700/50 bg-dark-900/50 p-5">
            <div className="mb-1 text-sm text-dark-300">👍 喜欢标签排名</div>
            <p className="mb-4 text-xs text-dark-500">标记为喜欢的图片中，AI 自动标签出现频率 Top 30。</p>
            <div className="space-y-1.5">
              {tags.map((t, i) => {
                const barPct = (t.count / maxCount) * 100
                // Gradient from bright to subtle
                const opacity = Math.max(0.3, 1 - i * 0.023)
                return (
                  <div key={t.tag} className="group flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-[10px] tabular-nums text-dark-600">{i + 1}</span>
                    <div className="relative flex-1 h-7 rounded-lg overflow-hidden bg-dark-800/50">
                      <div
                        className="absolute inset-y-0 left-0 rounded-lg transition-all duration-500 group-hover:brightness-125"
                        style={{
                          width: `${Math.max(barPct, 2)}%`,
                          backgroundColor: `rgba(52, 211, 153, ${opacity})`,
                        }}
                      />
                      <div className="relative flex h-full items-center justify-between px-2.5">
                        <span className="text-xs text-dark-100 drop-shadow-sm">{t.tag}</span>
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

      {/* Export */}
      {stats.liked > 0 && (
        <div className="flex flex-wrap justify-center gap-3">
          <a
            href={getExportUrl('liked')}
            className="rounded-2xl bg-emerald-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出喜欢的 ({stats.liked} 张)
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
            className="rounded-2xl bg-blue-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            🖼️ 导出原始分辨率
          </a>
        </div>
      )}
    </div>
  )
}

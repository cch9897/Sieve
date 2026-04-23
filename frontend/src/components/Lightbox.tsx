import { useEffect, useCallback, useRef, useState, useMemo, type ReactNode } from 'react'
import type { ImageItem } from '../types'
import { getSourceMeta } from '../sourceMeta'
import { fetchAutoTags, fetchVisionScoreCompare } from '../api'
import type { AutoTagsDetail, VisionScoreCompare } from '../api'

const RATING_COLORS: Record<string, string> = {
  general: 'border-emerald-500/30 bg-emerald-500/12 text-emerald-200',
  sensitive: 'border-amber-500/30 bg-amber-500/12 text-amber-200',
  questionable: 'border-orange-500/30 bg-orange-500/12 text-orange-200',
  explicit: 'border-rose-500/30 bg-rose-500/12 text-rose-200',
}

interface LightboxProps {
  image: ImageItem | null
  images: ImageItem[]
  onClose: () => void
  onNavigate: (img: ImageItem) => void
}

const SOURCE_LINKS: Record<string, (id: string) => string> = {
  danbooru: (id) => `https://danbooru.donmai.us/posts/${id}`,
  pixiv: (id) => `https://www.pixiv.net/artworks/${id}`,
  yandere: (id) => `https://yande.re/post/show/${id}`,
  gelbooru: (id) => `https://gelbooru.com/index.php?page=post&s=view&id=${id}`,
  konachan: (id) => `https://konachan.com/post/show/${id}`,
}

function renderScoreBar(score: number): ReactNode {
  return (
    <div className="mt-2 flex items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
        <div
          className={[
            'h-full rounded-full transition-all',
            score >= 0.7 ? 'bg-emerald-500' : score >= 0.4 ? 'bg-amber-500' : 'bg-rose-500',
          ].join(' ')}
          style={{ width: `${(score * 100).toFixed(1)}%` }}
        />
      </div>
      <span className="w-12 text-right font-mono text-[11px] text-white/78">{(score * 100).toFixed(1)}%</span>
    </div>
  )
}

const MAX_CACHE = 50

export default function Lightbox({ image, images, onClose, onNavigate }: LightboxProps) {
  const currentIndex = useMemo(
    () => image ? images.findIndex(i => i.id === image.id) : -1,
    [images, image?.id]
  )

  const goNext = useCallback(() => {
    if (currentIndex >= 0 && currentIndex < images.length - 1) onNavigate(images[currentIndex + 1])
  }, [currentIndex, images, onNavigate])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) onNavigate(images[currentIndex - 1])
  }, [currentIndex, images, onNavigate])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowRight') goNext()
    else if (e.key === 'ArrowLeft') goPrev()
  }, [onClose, goNext, goPrev])

  useEffect(() => {
    if (image) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [image, handleKeyDown])

  useEffect(() => {
    if (currentIndex < 0) return
    const toPreload = [images[currentIndex - 1], images[currentIndex + 1]].filter(Boolean)
    toPreload.forEach(img => {
      if (img && !img.is_video) {
        const preload = new Image()
        preload.src = `/images/${img.file_path}`
      }
    })
  }, [currentIndex, images])

  const [autoTags, setAutoTags] = useState<AutoTagsDetail | null>(null)
  const [tagsLoading, setTagsLoading] = useState(false)
  const [multiScores, setMultiScores] = useState<VisionScoreCompare | null>(null)

  const autoTagsCache = useRef<Map<number, AutoTagsDetail>>(new Map())
  const visionScoreCache = useRef<Map<number, VisionScoreCompare>>(new Map())
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!image) { setAutoTags(null); setMultiScores(null); return }

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    const cachedTags = autoTagsCache.current.get(image.id)
    const cachedScores = visionScoreCache.current.get(image.id)

    if (cachedTags && cachedScores) {
      setAutoTags(cachedTags)
      setMultiScores(cachedScores)
      setTagsLoading(false)
      return
    }

    setTagsLoading(true)
    if (!cachedTags) setAutoTags(null)
    else setAutoTags(cachedTags)
    if (!cachedScores) setMultiScores(null)
    else setMultiScores(cachedScores)

    if (!cachedTags) {
      fetchAutoTags(image.id, controller.signal)
        .then(t => {
          if (autoTagsCache.current.size > MAX_CACHE) {
            const firstKey = autoTagsCache.current.keys().next().value
            if (firstKey !== undefined) autoTagsCache.current.delete(firstKey)
          }
          autoTagsCache.current.set(image.id, t)
          setAutoTags(t)
        })
        .catch(e => { if (e.name !== 'AbortError') setAutoTags(null) })
        .finally(() => setTagsLoading(false))
    } else {
      setTagsLoading(false)
    }

    if (!cachedScores) {
      fetchVisionScoreCompare(image.id, controller.signal)
        .then(s => {
          if (visionScoreCache.current.size > MAX_CACHE) {
            const firstKey = visionScoreCache.current.keys().next().value
            if (firstKey !== undefined) visionScoreCache.current.delete(firstKey)
          }
          visionScoreCache.current.set(image.id, s)
          setMultiScores(s)
        })
        .catch(e => { if (e.name !== 'AbortError') setMultiScores(null) })
    }

    return () => { controller.abort() }
  }, [image?.id])

  const touchStart = useRef<{ x: number; y: number } | null>(null)
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY }
  }, [])
  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!touchStart.current) return
    const dx = e.changedTouches[0].clientX - touchStart.current.x
    const dy = e.changedTouches[0].clientY - touchStart.current.y
    touchStart.current = null
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      if (dx > 0) goPrev()
      else goNext()
    }
  }, [goPrev, goNext])

  if (!image) return null

  const meta = getSourceMeta(image.source)
  const sourceLink = SOURCE_LINKS[image.source]?.(image.source_id) || image.url
  const hasPrev = currentIndex > 0
  const hasNext = currentIndex >= 0 && currentIndex < images.length - 1
  const scoreEntries = multiScores?.scores
    ? Object.entries(multiScores.scores).map(([model, data]) => ({ model, ...data }))
    : []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(4,3,2,0.94)] p-3 md:p-6"
      role="dialog"
      aria-modal="true"
      aria-label="图片预览"
      onClick={onClose}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(159,91,82,0.18),transparent_24%),radial-gradient(circle_at_80%_14%,rgba(214,165,93,0.14),transparent_20%)]" />

      <button onClick={onClose} aria-label="关闭预览" className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--line)] bg-[rgba(19,15,12,0.78)] text-2xl text-[var(--text)] transition-colors hover:bg-[rgba(40,32,24,0.92)]">&times;</button>

      {hasPrev && <button onClick={e => { e.stopPropagation(); goPrev() }} aria-label="上一张" className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[rgba(19,15,12,0.78)] text-[var(--text)] transition-colors hover:bg-[rgba(40,32,24,0.92)]"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button>}
      {hasNext && <button onClick={e => { e.stopPropagation(); goNext() }} aria-label="下一张" className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[rgba(19,15,12,0.78)] text-[var(--text)] transition-colors hover:bg-[rgba(40,32,24,0.92)]"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg></button>}

      <div className="relative z-10 grid max-h-[calc(100vh-2rem)] w-full max-w-7xl gap-4 lg:grid-cols-[minmax(0,1.3fr)_380px]" onClick={e => e.stopPropagation()}>
        <section className="editorial-panel overflow-hidden rounded-[30px] p-3 md:p-4">
          <div className="relative flex min-h-[40vh] items-center justify-center overflow-hidden rounded-[24px] bg-[rgba(255,255,255,0.03)]">
            {image.is_video ? <video src={`/images/${image.file_path}`} controls autoPlay className="max-h-[78vh] max-w-full rounded-[20px]" /> : <img src={`/images/${image.file_path}`} alt={image.source_id} className="max-h-[78vh] max-w-full rounded-[20px] object-contain" />}
          </div>
        </section>

        <aside className="editorial-panel flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-[30px]">
          <div className="border-b border-[var(--line)] px-5 py-4">
            <div className="micro-label">Archive Entry</div>
            <div className="mt-2 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="editorial-title truncate text-2xl text-[var(--text)]">{image.source_id}</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--muted)]">来源 {meta.label} · {image.date || '未记录日期'}</p>
              </div>
              <span className="rounded-full border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-[var(--muted)]">{image.is_video ? 'Video' : 'Image'}</span>
            </div>
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
            <section>
              <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">文件</div>
              <div className="mt-2 break-all rounded-[20px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-4 py-3 text-sm text-[var(--text)] opacity-[0.88]">{image.file_path}</div>
            </section>

            {(image.vision_score != null || multiScores) && (
              <section>
                <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">Vision Score</div>
                <div className="mt-2 rounded-[20px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-4 py-3">
                  {scoreEntries.length ? (
                    <div className="space-y-3">
                      {scoreEntries.map((entry, idx) => (
                        <div key={entry.model || idx}>
                          <div className="flex items-center justify-between gap-3 text-xs text-white/72">
                            <span>{entry.model}</span>
                            <span>{entry.score.toFixed(3)}</span>
                          </div>
                          {renderScoreBar(entry.score)}
                        </div>
                      ))}
                    </div>
                  ) : image.vision_score != null ? renderScoreBar(image.vision_score) : null}
                </div>
              </section>
            )}

            <section>
              <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--muted)]">自动标签</div>
              <div className="mt-2 rounded-[20px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-4 py-3">
                {tagsLoading ? <div className="text-xs text-[var(--muted)] animate-pulse">加载中…</div> : autoTags && autoTags.found ? <div className="space-y-3">{autoTags.rating && <div className="flex flex-wrap gap-1.5">{Object.entries(autoTags.rating).sort(([, a], [, b]) => b - a).slice(0, 1).map(([rating]) => <span key={rating} className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${RATING_COLORS[rating] || 'border-white/10 bg-white/5 text-white/70'}`}>{rating}</span>)}</div>}{autoTags.characters && Object.keys(autoTags.characters).length > 0 && <div className="flex flex-wrap gap-1.5">{Object.entries(autoTags.characters).sort(([, a], [, b]) => b - a).map(([tag, score]) => <span key={tag} className="rounded-full border border-[var(--line)] bg-[rgba(159,91,82,0.14)] px-2.5 py-1 text-[11px] text-[var(--text)]">{tag}<span className="ml-1 text-[var(--muted)]">{(score * 100).toFixed(0)}%</span></span>)}</div>}{autoTags.general && Object.keys(autoTags.general).length > 0 && <div className="flex flex-wrap gap-1.5">{Object.entries(autoTags.general).sort(([, a], [, b]) => b - a).map(([tag, score]) => <span key={tag} className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-[11px] text-white/76">{tag}<span className="ml-1 text-white/40">{(score * 100).toFixed(0)}%</span></span>)}</div>}</div> : <div className="text-xs text-[var(--muted)]">暂未打标</div>}
              </div>
            </section>
          </div>

          <div className="border-t border-[var(--line)] px-5 py-4">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <a href={sourceLink} target="_blank" rel="noopener noreferrer" className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-3 py-2 text-center text-[var(--text)] transition-colors hover:bg-[rgba(255,255,255,0.07)]">打开来源页</a>
              <a href={`/images/${image.file_path}`} target="_blank" rel="noopener noreferrer" className="rounded-[18px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] px-3 py-2 text-center text-[var(--text)] transition-colors hover:bg-[rgba(255,255,255,0.07)]">查看原文件</a>
            </div>
            {images.length > 1 && <div className="mt-3 rounded-[18px] border border-[var(--line)] bg-[rgba(0,0,0,0.16)] px-3 py-2 text-xs text-[var(--muted)]">第 {currentIndex + 1} / {images.length} 项 · ← → 切换 · Esc 关闭</div>}
          </div>
        </aside>
      </div>
    </div>
  )
}

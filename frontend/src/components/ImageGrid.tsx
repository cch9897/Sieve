import React, { useState, useEffect, useRef, useCallback, memo } from 'react'
import type { ImageItem } from '../types'
import EmptyState from './EmptyState'
import { getSourceMeta } from '../sourceMeta'
import { fetchAutoTagsBatch } from '../api'

interface ImageGridProps {
  images: ImageItem[]
  onImageClick: (img: ImageItem) => void
  loading?: boolean
  onClearFilters?: () => void
}

const LazyImage = memo(function LazyImage({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false)
  const [errored, setErrored] = useState(false)
  return (
    <div className="relative overflow-hidden rounded-[22px] bg-[rgba(255,255,255,0.03)]">
      {!loaded && !errored && <div className="absolute inset-0 animate-pulse bg-[rgba(255,255,255,0.05)]" />}
      {errored ? (
        <div className="flex h-32 items-center justify-center text-xs text-[var(--muted)]">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10" /><path d="M12 8v5" /><path d="M12 16h.01" />
          </svg>
        </div>
      ) : (
        <img
          src={src}
          alt={alt}
          className={[
            'block w-full transition duration-700 will-change-transform group-hover:scale-[1.025]',
            loaded ? 'opacity-100' : 'opacity-0',
          ].join(' ')}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          onError={() => setErrored(true)}
        />
      )}
    </div>
  )
})

function SkeletonGrid() {
  // Weighted toward common art aspect ratios
  const ratios = [
    { w: 3, h: 4, weight: 3 },  // portrait
    { w: 2, h: 3, weight: 3 },  // portrait
    { w: 9, h: 16, weight: 2 }, // tall portrait
    { w: 1, h: 1, weight: 2 },  // square
    { w: 4, h: 3, weight: 2 },  // landscape
    { w: 16, h: 9, weight: 2 }, // wide landscape
    { w: 3, h: 2, weight: 1 },  // wide
  ]
  const totalWeight = ratios.reduce((s, r) => s + r.weight, 0)
  const width = 260
  function pickHeight(_: unknown, index: number): number {
    const seed = (index * 7 + 13) % totalWeight
    let r = seed
    for (const ratio of ratios) {
      r -= ratio.weight
      if (r <= 0) return Math.round((width * ratio.h) / ratio.w)
    }
    return 320
  }
  const heights = Array.from({ length: 12 }, pickHeight)
  return (
    <div className="masonry px-3 md:px-0">
      {heights.map((h, i) => (
        <div key={i} className="masonry-item">
          <div
            className="editorial-panel animate-pulse overflow-hidden rounded-[26px]"
            style={{ height: `${h}px` }}
          />
        </div>
      ))}
    </div>
  )
}

const ImageCard = memo(function ImageCard({ img, batchTag, onImageClick, onKeyDown }: {
  img: ImageItem;
  batchTag: string | undefined;
  onImageClick: (img: ImageItem) => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}) {
  const meta = getSourceMeta(img.source)
  const topTags = batchTag?.split(',').slice(0, 5).map(tag => tag.trim()).filter(Boolean) ?? []

  return (
    <div
      className="masonry-item group cursor-pointer"
      role="listitem"
      tabIndex={0}
      onClick={() => onImageClick(img)}
      onKeyDown={onKeyDown}
    >
      <article className="editorial-panel overflow-hidden rounded-[28px] transition-all duration-300 hover:-translate-y-1 hover:border-[var(--line-strong)] hover:shadow-[0_36px_90px_rgba(0,0,0,0.34)] active:scale-[0.98] active:duration-75">
        <div className="relative">
          {img.is_video ? (
            <video
              src={img.thumb_url}
              className="block w-full rounded-[22px]"
              muted
              loop
              preload="metadata"
              onMouseEnter={e => (e.target as HTMLVideoElement).play()}
              onMouseLeave={e => {
                const v = e.target as HTMLVideoElement
                v.pause()
                v.currentTime = 0
              }}
            />
          ) : (
            <LazyImage src={img.thumb_url} alt={`${img.source} ${img.source_id}`} />
          )}

          <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-black/40 via-black/12 to-transparent opacity-80" />
          <div className="absolute inset-x-0 bottom-0 h-36 bg-gradient-to-t from-black/88 via-black/35 to-transparent opacity-90" />

          <div className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-[rgba(19,15,12,0.72)] px-2.5 py-1 text-[11px] text-white/88 backdrop-blur-sm">
            <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} />
            <span>{meta.label}</span>
          </div>

          {img.is_video && (
            <div className="absolute right-3 top-3 rounded-full border border-[var(--line)] bg-[rgba(19,15,12,0.72)] px-2.5 py-1 text-[11px] tracking-[0.18em] text-[var(--text)] backdrop-blur-sm" aria-label="视频">
              VIDEO
            </div>
          )}

          <div className="pointer-events-none absolute inset-x-0 bottom-0 p-3">
            <div className="rounded-[20px] border border-white/10 bg-[rgba(10,8,7,0.5)] px-3 py-3 backdrop-blur-md">
              <div className="flex items-start gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] uppercase tracking-[0.18em] text-white/45">Source ID</div>
                  <div className="mt-1 truncate text-sm text-white/92">{img.source_id}</div>
                </div>
                {img.vision_score != null && (
                  <span className={[
                    'shrink-0 rounded-full px-2 py-1 font-mono text-[10px] font-medium',
                    img.vision_score >= 0.7 ? 'bg-emerald-500/25 text-emerald-200'
                      : img.vision_score >= 0.4 ? 'bg-amber-500/25 text-amber-200'
                      : 'bg-rose-500/25 text-rose-200',
                  ].join(' ')}>
                    {(img.vision_score * 100).toFixed(0)}%
                  </span>
                )}
              </div>

              <div className="mt-2 flex items-center gap-2 text-[11px] text-white/58">
                {img.date && <span>{img.date}</span>}
                {img.subfolder && <span className="truncate">{img.subfolder}</span>}
              </div>

              {/* Reserve min-height for tags to prevent layout shift when they load async */}
              <div className="mt-2 min-h-[24px] flex flex-wrap gap-1.5">
                {topTags.length > 0 ? topTags.map(tag => (
                  <span
                    key={tag}
                    className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[10px] text-white/62"
                  >
                    {tag}
                  </span>
                )) : (
                  /* Invisible placeholder to hold height */
                  <span className="rounded-full border border-transparent px-2 py-0.5 text-[10px] invisible" aria-hidden="true">placeholder</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </article>
    </div>
  )
})

const MAX_BATCH_TAGS = 300

const ImageGrid = React.memo(function ImageGrid({ images, onImageClick, loading, onClearFilters }: ImageGridProps) {
  const [batchTags, setBatchTags] = useState<Record<string, { top_tags: string; rating: string }>>({})
  const fetchedIdsRef = useRef<Set<number>>(new Set())
  const gridRef = useRef<HTMLDivElement>(null)

  const handleCardKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const el = e.currentTarget as HTMLElement
      const idx = Array.from(gridRef.current?.querySelectorAll('[role="listitem"]') ?? []).indexOf(el)
      if (idx >= 0) onImageClick(images[idx])
      return
    }
    // Arrow key navigation between cards
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return
    e.preventDefault()
    const cards = Array.from(gridRef.current?.querySelectorAll<HTMLElement>('[role="listitem"]') ?? [])
    const current = e.currentTarget as HTMLElement
    const idx = cards.indexOf(current)
    if (idx < 0) return

    let next = idx
    // Estimate columns from masonry layout
    const containerWidth = gridRef.current?.offsetWidth ?? 0
    const cardWidth = current.offsetWidth || 300
    const cols = Math.max(1, Math.round(containerWidth / (cardWidth + 14)))

    if (e.key === 'ArrowRight') next = Math.min(idx + 1, cards.length - 1)
    else if (e.key === 'ArrowLeft') next = Math.max(idx - 1, 0)
    else if (e.key === 'ArrowDown') next = Math.min(idx + cols, cards.length - 1)
    else if (e.key === 'ArrowUp') next = Math.max(idx - cols, 0)

    if (next !== idx && cards[next]) {
      cards[next].focus()
      cards[next].scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [images, onImageClick])

  useEffect(() => {
    if (!images.length) {
      setBatchTags({})
      fetchedIdsRef.current.clear()
      return
    }
    const newIds = images.filter(i => !fetchedIdsRef.current.has(i.id)).map(i => i.id)
    if (newIds.length === 0) return
    newIds.forEach(id => fetchedIdsRef.current.add(id))
    const controller = new AbortController()
    fetchAutoTagsBatch(newIds, controller.signal)
      .then(res => {
        if (res.tags) {
          setBatchTags(prev => {
            const next = { ...prev, ...res.tags }
            const keys = Object.keys(next)
            if (keys.length > MAX_BATCH_TAGS) {
              const toRemove = keys.slice(0, keys.length - MAX_BATCH_TAGS)
              for (const k of toRemove) delete next[k]
            }
            return next
          })
        }
      })
      .catch((e) => { if (e.name !== 'AbortError') console.error('fetchAutoTagsBatch failed:', e) })
    return () => controller.abort()
  }, [images])

  if (loading) return <SkeletonGrid />

  if (images.length === 0) {
    return (
      <div className="px-3 md:px-0">
        <EmptyState
          title="这里暂时是空的"
          description="换个来源、日期或者排序试试，也可能只是这一天还没抓到图。"
          action={onClearFilters ? (
            <button
              onClick={onClearFilters}
              className="rounded-2xl border border-[var(--line-strong)] bg-[var(--accent-soft)] px-4 py-2 text-sm text-[var(--text)] transition hover:bg-[rgba(214,165,93,0.2)]"
            >
              重置筛选
            </button>
          ) : undefined}
        />
      </div>
    )
  }

  return (
    <div ref={gridRef} className="masonry px-3 md:px-0" role="list">
      {images.map(img => (
        <ImageCard
          key={img.id}
          img={img}
          batchTag={batchTags[String(img.id)]?.top_tags}
          onImageClick={onImageClick}
          onKeyDown={handleCardKeyDown}
        />
      ))}
    </div>
  )
})

export default ImageGrid

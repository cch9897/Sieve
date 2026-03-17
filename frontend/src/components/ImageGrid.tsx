import { useState, useEffect, useRef } from 'react'
import type { ImageItem } from '../types'
import EmptyState from './EmptyState'
import { getSourceMeta } from '../sourceMeta'
import { fetchAutoTagsBatch } from '../api'

interface ImageGridProps {
  images: ImageItem[]
  onImageClick: (img: ImageItem) => void
  loading?: boolean
}

function LazyImage({ src }: { src: string }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <div className="relative overflow-hidden rounded-xl bg-dark-900">
      {!loaded && (
        <div className="absolute inset-0 animate-pulse bg-dark-800" />
      )}
      <img
        src={src}
        alt=""
        className={[
          'block w-full transition duration-500 will-change-transform group-hover:scale-[1.02]',
          loaded ? 'opacity-100' : 'opacity-0',
        ].join(' ')}
        loading="lazy"
        decoding="async"
        onLoad={() => setLoaded(true)}
      />
    </div>
  )
}

function SkeletonGrid() {
  const heights = [220, 300, 240, 340, 260, 280, 200, 320, 260, 240, 300, 230]
  return (
    <div className="masonry px-4">
      {heights.map((h, i) => (
        <div key={i} className="masonry-item">
          <div
            className="overflow-hidden rounded-2xl border border-dark-700/50 bg-dark-900 animate-pulse"
            style={{ height: `${h}px` }}
          />
        </div>
      ))}
    </div>
  )
}

export default function ImageGrid({ images, onImageClick, loading }: ImageGridProps) {
  const [batchTags, setBatchTags] = useState<Record<string, { top_tags: string; rating: string }>>({})
  const prevIdsRef = useRef('')

  useEffect(() => {
    if (!images.length) return
    const ids = images.map(i => i.id)
    const idsKey = ids.join(',')
    if (idsKey === prevIdsRef.current) return
    prevIdsRef.current = idsKey
    fetchAutoTagsBatch(ids)
      .then(res => setBatchTags(res.tags || {}))
      .catch(() => {})
  }, [images])

  if (loading) return <SkeletonGrid />

  if (images.length === 0) {
    return (
      <div className="px-4">
        <EmptyState
          title="这里暂时是空的"
          description="换个来源、日期或者排序试试，也可能只是这一天还没抓到图。"
        />
      </div>
    )
  }

  return (
    <div className="masonry px-4">
      {images.map(img => {
        const meta = getSourceMeta(img.source)
        return (
          <div
            key={img.id}
            className="masonry-item group cursor-pointer"
            onClick={() => onImageClick(img)}
          >
            <article className="overflow-hidden rounded-2xl border border-dark-700/50 bg-dark-900/70 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:border-dark-500/60 hover:shadow-xl hover:shadow-black/20">
              <div className="relative">
                {img.is_video ? (
                  <video
                    src={img.thumb_url}
                    className="block w-full"
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
                  <LazyImage src={img.thumb_url} />
                )}

                <div className="absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-black/35 via-black/10 to-transparent opacity-70" />
                <div className="absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-black/80 via-black/25 to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-100" />

                <div className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/45 px-2.5 py-1 text-[11px] text-white/85 backdrop-blur-sm">
                  <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} />
                  <span>{meta.label}</span>
                </div>

                {img.is_video && (
                  <div className="absolute right-3 top-3 rounded-full border border-white/10 bg-black/45 px-2 py-1 text-[11px] text-white/85 backdrop-blur-sm">
                    VIDEO
                  </div>
                )}

                <div className="pointer-events-none absolute inset-x-0 bottom-0 p-3 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                  <div className="rounded-xl border border-white/10 bg-black/45 px-3 py-2 backdrop-blur-sm">
                    <div className="truncate text-xs text-white/90">{img.source_id}</div>
                    <div className="mt-1 flex items-center gap-2 text-[11px] text-white/60">
                      {img.date && <span>{img.date}</span>}
                      {img.subfolder && <span className="truncate">{img.subfolder}</span>}
                    </div>
                    {batchTags[String(img.id)]?.top_tags && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {batchTags[String(img.id)].top_tags.split(',').slice(0, 5).map(tag => (
                          <span
                            key={tag}
                            className="rounded-full border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] text-white/50"
                          >
                            {tag.trim()}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </article>
          </div>
        )
      })}
    </div>
  )
}

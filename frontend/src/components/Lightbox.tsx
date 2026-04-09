import { useEffect, useCallback, useRef, useState } from 'react'
import type { ImageItem } from '../types'
import { getSourceMeta } from '../sourceMeta'
import { fetchAutoTags, fetchVisionScoreCompare } from '../api'
import type { AutoTagsDetail, VisionScoreCompare } from '../api'

const RATING_COLORS: Record<string, string> = {
  general: 'border-green-500/40 bg-green-500/15 text-green-400',
  sensitive: 'border-yellow-500/40 bg-yellow-500/15 text-yellow-400',
  questionable: 'border-orange-500/40 bg-orange-500/15 text-orange-400',
  explicit: 'border-red-500/40 bg-red-500/15 text-red-400',
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

export default function Lightbox({ image, images, onClose, onNavigate }: LightboxProps) {
  const currentIndex = image ? images.findIndex(i => i.id === image.id) : -1

  const goNext = useCallback(() => {
    if (currentIndex >= 0 && currentIndex < images.length - 1) {
      onNavigate(images[currentIndex + 1])
    }
  }, [currentIndex, images, onNavigate])

  const goPrev = useCallback(() => {
    if (currentIndex > 0) {
      onNavigate(images[currentIndex - 1])
    }
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

  useEffect(() => {
    if (!image) { setAutoTags(null); setMultiScores(null); return }
    setTagsLoading(true)
    setAutoTags(null)
    setMultiScores(null)
    fetchAutoTags(image.id)
      .then(t => setAutoTags(t))
      .catch(() => setAutoTags(null))
      .finally(() => setTagsLoading(false))
    fetchVisionScoreCompare(image.id)
      .then(s => setMultiScores(s))
      .catch(() => setMultiScores(null))
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/95 p-3 md:p-6"
      onClick={onClose}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <button
        onClick={onClose}
        className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-black/40 text-2xl text-white/70 transition-colors hover:bg-black/60 hover:text-white"
      >
        &times;
      </button>

      {hasPrev && (
        <button
          onClick={e => { e.stopPropagation(); goPrev() }}
          className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 transition-colors hover:bg-black/60 hover:text-white"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
      )}

      {hasNext && (
        <button
          onClick={e => { e.stopPropagation(); goNext() }}
          className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-white/10 bg-black/40 text-white/70 transition-colors hover:bg-black/60 hover:text-white"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
      )}

      <div
        className="grid max-h-[92vh] w-full max-w-7xl gap-4 lg:grid-cols-[minmax(0,1fr)_320px]"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex min-h-[320px] items-center justify-center rounded-3xl border border-white/10 bg-black/30 p-2 md:p-4">
          {image.is_video ? (
            <video
              key={image.id}
              src={`/images/${image.file_path}`}
              className="max-h-[78vh] max-w-full rounded-2xl"
              controls
              autoPlay
              loop
            />
          ) : (
            <img
              key={image.id}
              src={`/images/${image.file_path}`}
              alt=""
              className="max-h-[78vh] max-w-full rounded-2xl object-contain"
            />
          )}
        </div>

        <aside className="flex flex-col justify-between rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur-md">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-white/80">
              <span className={`h-2 w-2 rounded-full ${meta.dotClass}`} />
              <span>{meta.label}</span>
            </div>

            <div className="mt-4 space-y-4">
              <div>
                <div className="text-xs uppercase tracking-wide text-white/40">ID</div>
                <div className="mt-1 break-all text-sm text-white/90">{image.source_id}</div>
              </div>

              {image.date && (
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">日期</div>
                  <div className="mt-1 text-sm text-white/80">{image.date}</div>
                </div>
              )}

              {(image.vision_score != null || (multiScores && Object.keys(multiScores.scores).length > 0)) && (
                <div>
                  <div className="text-xs uppercase tracking-wide text-white/40">视觉评分</div>
                  {multiScores && Object.keys(multiScores.scores).length > 1 ? (
                    <div className="mt-1 space-y-1.5">
                      {Object.entries(multiScores.scores).map(([modelName, info]) => {
                        const shortName = modelName.split('/').pop() || modelName
                        return (
                          <div key={modelName} className="flex items-center gap-2">
                            <span className="w-20 truncate text-[11px] text-white/50" title={modelName}>{shortName}</span>
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
                              <div
                                className={[
                                  'h-full rounded-full transition-all',
                                  info.score >= 0.7 ? 'bg-emerald-500' : info.score >= 0.4 ? 'bg-amber-500' : 'bg-red-500',
                                ].join(' ')}
                                style={{ width: `${(info.score * 100).toFixed(1)}%` }}
                              />
                            </div>
                            <span className="font-mono text-[11px] text-white/80 w-12 text-right">{(info.score * 100).toFixed(1)}%</span>
                          </div>
                        )
                      })}
                    </div>
                  ) : image.vision_score != null ? (
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
                        <div
                          className={[
                            'h-full rounded-full transition-all',
                            image.vision_score >= 0.7 ? 'bg-emerald-500' : image.vision_score >= 0.4 ? 'bg-amber-500' : 'bg-red-500',
                          ].join(' ')}
                          style={{ width: `${(image.vision_score * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <span className="font-mono text-sm text-white/80">{(image.vision_score * 100).toFixed(1)}%</span>
                    </div>
                  ) : null}
                </div>
              )}

              <div>
                <div className="text-xs uppercase tracking-wide text-white/40">文件</div>
                <div className="mt-1 break-all text-sm text-white/70">{image.file_path}</div>
              </div>

              {/* Auto Tags */}
              <div>
                <div className="text-xs uppercase tracking-wide text-white/40">自动标签</div>
                {tagsLoading ? (
                  <div className="mt-2 text-xs text-white/40 animate-pulse">加载中…</div>
                ) : autoTags && autoTags.found ? (
                  <div className="mt-2 max-h-[200px] space-y-2 overflow-y-auto scrollbar-thin">
                    {/* Rating */}
                    {autoTags.rating && (
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(autoTags.rating)
                          .sort(([, a], [, b]) => b - a)
                          .slice(0, 1)
                          .map(([r]) => (
                            <span
                              key={r}
                              className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${RATING_COLORS[r] || 'border-white/10 bg-white/5 text-white/70'}`}
                            >
                              {r}
                            </span>
                          ))}
                      </div>
                    )}
                    {/* Characters */}
                    {autoTags.characters && Object.keys(autoTags.characters).length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(autoTags.characters)
                          .sort(([, a], [, b]) => b - a)
                          .map(([tag, score]) => (
                            <span
                              key={tag}
                              className="rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[11px] text-purple-300"
                            >
                              {tag}
                              <span className="ml-1 text-purple-400/50">{(score * 100).toFixed(0)}%</span>
                            </span>
                          ))}
                      </div>
                    )}
                    {/* General tags */}
                    {autoTags.general && Object.keys(autoTags.general).length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(autoTags.general)
                          .sort(([, a], [, b]) => b - a)
                          .map(([tag, score]) => (
                            <span
                              key={tag}
                              className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-[11px] text-white/70"
                            >
                              {tag}
                              <span className="ml-1 text-white/35">{(score * 100).toFixed(0)}%</span>
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="mt-2 text-xs text-white/30">暂未打标</div>
                )}
              </div>
            </div>
          </div>

          <div className="mt-6 space-y-3">
            <div className="grid grid-cols-2 gap-2 text-sm">
              <a
                href={sourceLink}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-center text-white/85 transition-colors hover:bg-white/10"
              >
                打开来源页
              </a>
              <a
                href={`/images/${image.file_path}`}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-center text-white/85 transition-colors hover:bg-white/10"
              >
                原图/原视频
              </a>
            </div>

            {images.length > 1 && (
              <div className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-xs text-white/60">
                第 {currentIndex + 1} / {images.length} 项 · ← → 切换 · Esc 关闭
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}

import { useState, useEffect, useCallback } from 'react'
import Spinner from '../Spinner'
import {
  fetchDanbooruLabelerHistory,
  danbooruLabelImage,
  danbooruUnlabelImage,
  getDanbooruExportUrl,
  type DanbooruLabeledImage,
} from '../../api'
import { RatingBadge } from './shared'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import EmptyState from '../EmptyState'

export default function HistoryMode() {
  const [images, setImages] = useState<DanbooruLabeledImage[]>([])
  const [loading, setLoading] = useState(true)
  const [verdict, setVerdict] = useState<string>('liked')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [selected, setSelected] = useState<DanbooruLabeledImage | null>(null)
  const [acting, setActing] = useState(false)
  const modalRef = useFocusTrap(!!selected)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchDanbooruLabelerHistory({ verdict, page, per_page: 60 })
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
    } catch (e) { console.error('load history failed:', e) }
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
    } catch (e) { console.error('relabel failed:', e) }
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
    } catch (e) { console.error('remove label failed:', e) }
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
      <div className="mb-4 flex items-center gap-2">
        {[
          ['liked', '👍 喜欢'],
          ['disliked', '👎 不喜欢'],
          ['skipped', '⏭ 跳过'],
        ].map(([key, label]) => (
          <button
            key={key}
            onClick={() => { setVerdict(key); setPage(1); setSelected(null) }}
            aria-pressed={verdict === key}
            className={[
              'rounded-ed-sm px-4 py-2 text-sm transition-all',
              verdict === key
                ? 'bg-[var(--surface)] text-[var(--text)]'
                : 'text-[var(--muted)] hover:text-[var(--text)]',
            ].join(' ')}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-[var(--muted)]">{total} 张</span>

        {verdict === 'liked' && total > 0 && (<>
          <a
            href={getDanbooruExportUrl('liked')}
            className="rounded-ed-sm bg-emerald-600/80 px-4 py-2 text-sm text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出 ZIP
          </a>
          <a
            href={getDanbooruExportUrl('liked', undefined, 0)}
            className="rounded-ed-sm bg-blue-600/80 px-4 py-2 text-sm text-white transition-colors hover:bg-blue-500"
          >
            🖼️ 原图
          </a>
        </>)}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner size="sm" />
        </div>
      ) : images.length === 0 ? (
        <EmptyState
          title="还没有标注过的图片"
          description="审阅一些图片后，历史记录会出现在这里。"
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
            {images.map(img => (
              <div
                key={img.id}
                onClick={() => setSelected(img)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(img) } }}
                tabIndex={0}
                role="button"
                aria-label={`图片 #${img.id} Score ${img.score}`}
                className="group relative cursor-pointer overflow-hidden rounded-ed-md border border-[var(--line)] bg-[var(--panel)] transition-all hover:border-[var(--line-strong)] hover:shadow-lg focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none"
              >
                <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 p-2">
                  <div className="flex items-center justify-between">
                    <RatingBadge rating={img.rating} />
                    <span className="text-[11px] text-[var(--muted)]">★ {img.score}</span>
                  </div>
                </div>
                {img.vision_score != null && (
                  <div className="absolute right-1.5 top-1.5 rounded px-1 py-0.5 font-mono text-[10px] font-medium backdrop-blur-sm"
                    style={{
                      background: img.vision_score >= 0.7 ? 'rgba(16,185,129,0.4)' : img.vision_score >= 0.4 ? 'rgba(245,158,11,0.4)' : 'rgba(239,68,68,0.4)',
                      color: 'rgba(255,255,255,0.9)',
                    }}
                  >
                    <span aria-hidden="true">🧠</span>{(img.vision_score * 100).toFixed(0)}%
                  </div>
                )}
                <div className="absolute inset-0 flex items-center justify-center bg-transparent opacity-0 transition-all group-hover:bg-[rgba(0,0,0,0.15)] group-hover:opacity-100">
                  <span className="text-2xl drop-shadow-lg" aria-hidden="true">🔍</span>
                </div>
              </div>
            ))}
          </div>

          {pages > 1 && (
            <div className="mt-6 flex items-center justify-center gap-2" role="navigation" aria-label="分页">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="rounded-ed-sm border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--muted)] disabled:opacity-30"
              >
                上一页
              </button>
              <span className="text-sm text-[var(--muted)]">{page} / {pages}</span>
              <button
                disabled={page >= pages}
                onClick={() => setPage(p => p + 1)}
                className="rounded-ed-sm border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--muted)] disabled:opacity-30"
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}

      {selected && (
        <div
          ref={modalRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
          role="dialog"
          aria-modal="true"
          aria-label="图片详情"
          onClick={() => setSelected(null)}
        >
          <button
            onClick={() => setSelected(null)}
            aria-label="关闭"
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-2xl text-[var(--muted)] hover:bg-[var(--panel-strong)] hover:text-[var(--text)]"
          >
            &times;
          </button>

          {selectedIndex > 0 && (
            <button
              onClick={e => { e.stopPropagation(); goPrev() }}
              aria-label="上一张"
              className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-[var(--muted)] hover:bg-[var(--panel-strong)] hover:text-[var(--text)]"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}
          {selectedIndex < images.length - 1 && (
            <button
              onClick={e => { e.stopPropagation(); goNext() }}
              aria-label="下一张"
              className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-[var(--muted)] hover:bg-[var(--panel-strong)] hover:text-[var(--text)]"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}

          <div
            className="flex max-h-[92vh] w-full max-w-5xl flex-col gap-4 lg:flex-row"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex flex-1 items-center justify-center rounded-ed-xl border border-[var(--line)] bg-[var(--bg-soft)] p-2">
              {selected.is_video ? (
                <video
                  key={selected.id}
                  src={selected.video_url || selected.preview_url}
                  className="max-h-[75vh] max-w-full rounded-ed-md"
                  controls autoPlay loop
                />
              ) : (
                <img
                  key={selected.id}
                  src={selected.preview_url}
                  alt=""
                  className="max-h-[75vh] max-w-full rounded-ed-md object-contain"
                />
              )}
            </div>

            <aside className="flex w-full flex-col justify-between overflow-y-auto rounded-ed-xl border border-[var(--line)] bg-[var(--panel-strong)] p-5 backdrop-blur-md lg:w-80">
              <div className="space-y-4">
                <div>
                  <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">当前标记</div>
                  <div className="mt-1 text-sm">
                    {selected.verdict === 'liked' && <span className="text-emerald-400">👍 喜欢</span>}
                    {selected.verdict === 'disliked' && <span className="text-red-400">👎 不喜欢</span>}
                    {selected.verdict === 'skipped' && <span className="text-[var(--muted)]">⏭ 跳过</span>}
                  </div>
                </div>

                <div>
                  <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">信息</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[var(--text)]">
                    <span>#{selected.id}</span>
                    <RatingBadge rating={selected.rating} />
                    <span>Score: {selected.score}</span>
                  </div>
                </div>

                {selected.vision_score != null && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">视觉评分</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--surface)]">
                        <div
                          className={[
                            'h-full rounded-full',
                            selected.vision_score >= 0.7 ? 'bg-emerald-500' : selected.vision_score >= 0.4 ? 'bg-amber-500' : 'bg-red-500',
                          ].join(' ')}
                          style={{ width: `${(selected.vision_score * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <span className="font-mono text-sm text-[var(--text)]">{(selected.vision_score * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                )}

                {selected.danbooru_tags && (
                  <div>
                    <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">Danbooru Tags</div>
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
                    <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">自定义标签</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selected.tags.map(t => (
                        <span key={t} className="rounded-ed-sm bg-[var(--surface)] px-2 py-0.5 text-xs text-[var(--text)]">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 space-y-2">
                <div className="mb-2 text-xs text-[var(--muted)]/50">重新标记</div>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    onClick={() => handleRelabel(selected, 'liked')}
                    disabled={acting || selected.verdict === 'liked'}
                    aria-pressed={selected.verdict === 'liked'}
                    className={[
                      'rounded-ed-sm py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'liked'
                        ? 'border border-emerald-500/50 bg-emerald-500/20 text-emerald-300'
                        : 'border border-[var(--line)] bg-[var(--surface)] text-[var(--muted)] hover:bg-emerald-500/20 hover:text-emerald-300',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👍
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'disliked')}
                    disabled={acting || selected.verdict === 'disliked'}
                    aria-pressed={selected.verdict === 'disliked'}
                    className={[
                      'rounded-ed-sm py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'disliked'
                        ? 'border border-red-500/50 bg-red-500/20 text-red-300'
                        : 'border border-[var(--line)] bg-[var(--surface)] text-[var(--muted)] hover:bg-red-500/20 hover:text-red-300',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👎
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'skipped')}
                    disabled={acting || selected.verdict === 'skipped'}
                    aria-pressed={selected.verdict === 'skipped'}
                    className={[
                      'rounded-ed-sm py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'skipped'
                        ? 'border border-[var(--line-strong)] bg-[var(--surface)] text-[var(--muted)]'
                        : 'border border-[var(--line)] bg-[var(--surface)] text-[var(--muted)] hover:bg-[var(--panel-strong)] hover:text-[var(--text)]',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    ⏭
                  </button>
                </div>
                <button
                  onClick={() => handleRemoveLabel(selected)}
                  disabled={acting}
                  className="w-full rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] py-2 text-xs text-[var(--muted)] transition-colors hover:bg-red-500/10 hover:text-red-300"
                >
                  🗑 移除标记（放回未审阅）
                </button>

                <div className="pt-2 text-center text-[10px] text-[var(--muted)]/50">
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

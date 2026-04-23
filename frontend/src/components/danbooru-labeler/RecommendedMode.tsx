import { useState, useEffect, useCallback } from 'react'
import Spinner from '../Spinner'
import {
  fetchDanbooruRecommended,
  danbooruLabelImage,
  type DanbooruLabeledImage,
} from '../../api'
import { RatingBadge, ScoreBadge } from './shared'
import { useFocusTrap } from '../../hooks/useFocusTrap'

type RecommendedImage = DanbooruLabeledImage & { preference_score: number }

export default function RecommendedMode() {
  const [images, setImages] = useState<RecommendedImage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [minScore, setMinScore] = useState(0.5)
  const [minScoreDisplay, setMinScoreDisplay] = useState(50)
  const [ratingFilter, setRatingFilter] = useState('')
  const [modelInfo, setModelInfo] = useState<{ auc: number; n_samples: number; model_type: string } | null>(null)
  const [selected, setSelected] = useState<RecommendedImage | null>(null)
  const [acting, setActing] = useState(false)
  const modalRef = useFocusTrap(!!selected)

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
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败')
    }
    setLoading(false)
  }, [page, minScore, ratingFilter])

  useEffect(() => { load() }, [load])

  const handleLabel = useCallback(async (img: RecommendedImage, verdict: string) => {
    if (acting) return
    setActing(true)
    try {
      await danbooruLabelImage(img.id, verdict, [], {
        ext: img.ext,
        score: img.score,
        rating: img.rating,
        danbooru_tags: img.danbooru_tags,
      })
      setImages(prev => prev.filter(i => i.id !== img.id))
      setTotal(t => t - 1)
      if (selected?.id === img.id) setSelected(null)
    } catch (e) { console.error('label recommended failed:', e) }
    setActing(false)
  }, [acting, selected])

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
      if (e.key === 'l' || e.key === 'L') { e.preventDefault(); handleLabel(selected, 'liked') }
      if (e.key === 'h' || e.key === 'H') { e.preventDefault(); handleLabel(selected, 'disliked') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, goPrev, goNext, handleLabel])

  return (
    <div className="space-y-5">
      {modelInfo && (
        <div className="flex items-center gap-4 rounded-ed-md border border-purple-500/20 bg-purple-500/5 px-5 py-3">
          <span className="text-2xl" aria-hidden="true">🤖</span>
          <div className="flex-1">
            <div className="text-sm font-medium text-purple-300">AI 偏好预测</div>
            <div className="text-xs text-[var(--muted)]">
              {modelInfo.model_type} · AUC {(modelInfo.auc * 100).toFixed(1)}% · 训练样本 {modelInfo.n_samples.toLocaleString()}
            </div>
          </div>
          <button
            onClick={() => { setPage(1); load() }}
            className="rounded-ed-sm border border-purple-500/30 bg-purple-500/10 px-4 py-1.5 text-sm text-purple-300 transition-colors hover:bg-purple-500/20"
          >
            🔄 刷新
          </button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-4 text-xs">
        <div className="flex items-center gap-2">
          <label className="text-[var(--muted)]" htmlFor="rec-min-score">最低分数:</label>
          <input
            id="rec-min-score"
            type="range"
            min={0}
            max={100}
            value={minScoreDisplay}
            onChange={e => setMinScoreDisplay(Number(e.target.value))}
            onMouseUp={() => { setMinScore(minScoreDisplay / 100); setPage(1) }}
            onTouchEnd={() => { setMinScore(minScoreDisplay / 100); setPage(1) }}
            className="h-1 w-32 appearance-none rounded-full bg-[var(--surface)] accent-purple-500"
          />
          <span className="min-w-[3ch] text-sm font-medium text-purple-300">{minScoreDisplay}%</span>
        </div>

        <span className="text-[var(--muted)]/50" aria-hidden="true">|</span>

        <div className="flex items-center gap-1.5" role="group" aria-label="Rating筛选">
          <span className="text-[var(--muted)]">Rating:</span>
          {(['', 'g', 's', 'q', 'e'] as const).map(r => (
            <button
              key={r}
              onClick={() => { setRatingFilter(r); setPage(1) }}
              aria-pressed={ratingFilter === r}
              className={`rounded-ed-sm px-2 py-1 transition-all ${ratingFilter === r ? 'bg-[var(--surface)] text-purple-400' : 'text-[var(--muted)] hover:text-[var(--text)]'}`}
            >
              {r === '' ? 'All' : r.toUpperCase()}
            </button>
          ))}
        </div>

        <span className="ml-auto text-[var(--muted)]">
          {total} 张推荐
        </span>
      </div>

      {error && (
        <div className="rounded-ed-md border border-red-500/30 bg-red-500/10 p-5 text-center text-sm text-red-300">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner size="sm" />
        </div>
      ) : images.length === 0 && !error ? (
        <div className="py-20 text-center text-[var(--muted)]">
          没有找到推荐图片，试试降低最低分数
        </div>
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
                aria-label={`图片 #${img.id} 偏好 ${(img.preference_score * 100).toFixed(0)}%`}
                className="group relative cursor-pointer overflow-hidden rounded-ed-md border border-[var(--line)] bg-[var(--panel)] transition-all hover:border-[var(--line-strong)] hover:shadow-lg focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none"
              >
                <img src={img.thumb_url} alt="" className="aspect-square w-full object-cover" loading="lazy" />
                <div className="absolute left-2 top-2">
                  <ScoreBadge score={img.preference_score} />
                </div>
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 p-2">
                  <div className="flex items-center justify-between">
                    <RatingBadge rating={img.rating} />
                    <span className="text-[11px] text-[var(--muted)]">★ {img.score}</span>
                  </div>
                </div>
                <div className="absolute right-1 top-1 flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    onClick={(e) => { e.stopPropagation(); handleLabel(img, 'liked') }}
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/80 text-sm shadow-lg transition-transform hover:scale-110"
                    title="喜欢"
                    aria-label="喜欢"
                  >
                    👍
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleLabel(img, 'disliked') }}
                    className="flex h-8 w-8 items-center justify-center rounded-full bg-red-500/80 text-sm shadow-lg transition-transform hover:scale-110"
                    title="不喜欢"
                    aria-label="不喜欢"
                  >
                    👎
                  </button>
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
                  <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">AI 偏好分数</div>
                  <div className="mt-2 flex items-center gap-3">
                    <ScoreBadge score={selected.preference_score} />
                    <div className="flex-1">
                      <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]">
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
                  <div className="text-xs uppercase tracking-wide text-[var(--muted)]/50">信息</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[var(--text)]">
                    <span>#{selected.id}</span>
                    <RatingBadge rating={selected.rating} />
                    <span>Score: {selected.score}</span>
                  </div>
                </div>

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
              </div>

              <div className="mt-6 space-y-2">
                <div className="mb-2 text-xs text-[var(--muted)]/50">标记</div>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => handleLabel(selected, 'liked')}
                    disabled={acting}
                    className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] py-2.5 text-sm font-medium text-[var(--muted)] transition-all hover:bg-emerald-500/20 hover:text-emerald-300 disabled:opacity-50"
                  >
                    👍 喜欢
                  </button>
                  <button
                    onClick={() => handleLabel(selected, 'disliked')}
                    disabled={acting}
                    className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] py-2.5 text-sm font-medium text-[var(--muted)] transition-all hover:bg-red-500/20 hover:text-red-300 disabled:opacity-50"
                  >
                    👎 不喜欢
                  </button>
                </div>
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

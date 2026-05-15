import { useState, useEffect, useCallback } from 'react'
import {
  fetchLabelerHistory,
  labelImage,
  unlabelImage,
  getExportUrl,
  type LabeledImage,
} from '../../api'
import { useFocusTrap } from '../../hooks/useFocusTrap'
import EmptyState from '../EmptyState'
import Spinner from '../Spinner'
import SubTabs from '../SubTabs'

export default function HistoryMode() {
  const [images, setImages] = useState<LabeledImage[]>([])
  const [loading, setLoading] = useState(true)
  const [verdict, setVerdict] = useState<string>('liked')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [pages, setPages] = useState(0)
  const [selected, setSelected] = useState<LabeledImage | null>(null)
  const [acting, setActing] = useState(false)
  const modalRef = useFocusTrap(!!selected)

  const VERDICT_TABS = [
    { key: 'liked' as const, label: '👍 喜欢' },
    { key: 'disliked' as const, label: '👎 不喜欢' },
    { key: 'skipped' as const, label: '⏭ 跳过' },
  ]

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchLabelerHistory({ verdict, page, per_page: 60 })
      setImages(res.images)
      setTotal(res.total)
      setPages(res.pages)
    } catch (e) { console.error('labeler history load failed:', e) }
    setLoading(false)
  }, [verdict, page])

  useEffect(() => { load() }, [load])

  const handleRelabel = useCallback(async (img: LabeledImage, newVerdict: string) => {
    if (acting) return
    setActing(true)
    try {
      await labelImage(img.id, newVerdict, img.tags || [])
      if (newVerdict !== verdict) {
        setImages(prev => prev.filter(i => i.id !== img.id))
        setTotal(t => t - 1)
      } else {
        setImages(prev => prev.map(i => i.id === img.id ? { ...i, verdict: newVerdict } : i))
      }
      setSelected(null)
    } catch (e) { console.error('labeler relabel failed:', e) }
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
    } catch (e) { console.error('labeler remove failed:', e) }
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
      <div className="mb-4 flex items-center gap-3">
        <SubTabs value={verdict} options={VERDICT_TABS} onChange={v => { setVerdict(v); setPage(1); setSelected(null) }} ariaLabel="筛选类型" />
        <span className="ml-auto micro-label">{total} 张</span>

        {verdict === 'liked' && total > 0 && (<>
          <a
            href={getExportUrl('liked')}
            className="rounded-ed-md border border-[var(--success)]/30 bg-[var(--success-soft)] px-4 py-1.5 text-sm text-[var(--success)] transition-colors hover:bg-[rgba(52,211,153,0.2)]"
          >
            📦 导出 ZIP
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
            className="rounded-ed-md border border-[var(--info)]/30 bg-[var(--info-soft)] px-4 py-1.5 text-sm text-[var(--info)] transition-colors hover:bg-[rgba(96,165,250,0.2)]"
          >
            🖼️ 原图
          </a>
        </>)}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Spinner size="md" />
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
                aria-label={`图片 ${img.source} ${img.source_id}`}
                className="group relative cursor-pointer overflow-hidden rounded-ed-lg border border-[var(--line)] bg-[var(--panel)] transition-all hover:border-[var(--line-strong)] hover:shadow-[var(--shadow-lg)] focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:outline-none"
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
                {img.vision_score != null && (
                  <div className="absolute right-1.5 top-1.5 rounded-ed-sm px-1 py-0.5 font-mono text-[10px] font-medium backdrop-blur-sm"
                    style={{
                      background: img.vision_score >= 0.7 ? 'rgba(52,211,153,0.4)' : img.vision_score >= 0.4 ? 'rgba(251,191,36,0.4)' : 'rgba(248,113,113,0.4)',
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
            <div className="mt-6 flex items-center justify-center gap-2" role="navigation" aria-label="分页">
              <button
                disabled={page <= 1}
                onClick={() => setPage(p => p - 1)}
                className="rounded-ed-sm border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--muted)] transition-colors hover:border-[var(--line-strong)] hover:text-[var(--text)] disabled:opacity-30"
              >
                上一页
              </button>
              <span className="text-sm text-[var(--muted)]">{page} / {pages}</span>
              <button
                disabled={page >= pages}
                onClick={() => setPage(p => p + 1)}
                className="rounded-ed-sm border border-[var(--line)] px-3 py-1.5 text-sm text-[var(--muted)] transition-colors hover:border-[var(--line-strong)] hover:text-[var(--text)] disabled:opacity-30"
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(4,3,2,0.94)] p-4"
          role="dialog"
          aria-modal="true"
          aria-label="图片详情"
          onClick={() => setSelected(null)}
        >
          <button
            onClick={() => setSelected(null)}
            aria-label="关闭"
            className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-2xl text-[var(--text)] transition-colors hover:bg-[var(--panel-strong)]"
          >
            &times;
          </button>

          {selectedIndex > 0 && (
            <button
              onClick={e => { e.stopPropagation(); goPrev() }}
              aria-label="上一张"
              className="absolute left-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-[var(--text)] transition-colors hover:bg-[var(--panel-strong)]"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4l-6 6 6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}
          {selectedIndex < images.length - 1 && (
            <button
              onClick={e => { e.stopPropagation(); goNext() }}
              aria-label="下一张"
              className="absolute right-3 top-1/2 z-10 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full border border-[var(--line)] bg-[var(--panel)] text-[var(--text)] transition-colors hover:bg-[var(--panel-strong)]"
            >
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M8 4l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/></svg>
            </button>
          )}

          <div
            className="flex max-h-[92vh] w-full max-w-5xl flex-col gap-4 lg:flex-row"
            onClick={e => e.stopPropagation()}
          >
            <div className="editorial-panel flex flex-1 items-center justify-center p-2">
              {selected.is_video ? (
                <video
                  key={selected.id}
                  src={`/images/${selected.file_path}`}
                  className="max-h-[75vh] max-w-full rounded-ed-lg"
                  controls autoPlay loop
                />
              ) : (
                <img
                  key={selected.id}
                  src={`/images/${selected.file_path}`}
                  alt=""
                  className="max-h-[75vh] max-w-full rounded-ed-lg object-contain"
                />
              )}
            </div>

            <aside className="editorial-panel flex w-full flex-col justify-between overflow-y-auto p-5 backdrop-blur-xl lg:w-72">
              <div className="space-y-4">
                <div>
                  <div className="micro-label">当前标记</div>
                  <div className="mt-1 text-sm">
                    {selected.verdict === 'liked' && <span className="text-[var(--success)]">👍 喜欢</span>}
                    {selected.verdict === 'disliked' && <span className="text-[var(--danger)]">👎 不喜欢</span>}
                    {selected.verdict === 'skipped' && <span className="text-[var(--muted)]">⏭ 跳过</span>}
                  </div>
                </div>

                <div>
                  <div className="micro-label">来源</div>
                  <div className="mt-1 text-sm text-[var(--text)]/80">{selected.source} · {selected.source_id}</div>
                </div>

                {selected.date && (
                  <div>
                    <div className="micro-label">日期</div>
                    <div className="mt-1 text-sm text-[var(--muted)]">{selected.date}</div>
                  </div>
                )}

                {selected.vision_scores && Object.keys(selected.vision_scores).length > 0 ? (
                  <div>
                    <div className="micro-label">视觉评分</div>
                    <div className="mt-1.5 space-y-1.5">
                      {Object.entries(selected.vision_scores).map(([model, score]) => (
                        <div key={model} className="flex items-center gap-2">
                          <span className="w-28 truncate text-[11px] text-[var(--muted)]/60" title={model}>
                            {model.replace(/^.*\//, '').slice(0, 20)}
                          </span>
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                            <div
                              className={[
                                'h-full rounded-full',
                                score >= 0.7 ? 'bg-[var(--success)]' : score >= 0.4 ? 'bg-[var(--warning)]' : 'bg-[var(--danger)]',
                              ].join(' ')}
                              style={{ width: `${(score * 100).toFixed(1)}%` }}
                            />
                          </div>
                          <span className="w-12 text-right font-mono text-xs text-[var(--text)]/70">{(score * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : selected.vision_score != null ? (
                  <div>
                    <div className="micro-label">视觉评分</div>
                    <div className="mt-1 flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                        <div
                          className={[
                            'h-full rounded-full',
                            selected.vision_score >= 0.7 ? 'bg-[var(--success)]' : selected.vision_score >= 0.4 ? 'bg-[var(--warning)]' : 'bg-[var(--danger)]',
                          ].join(' ')}
                          style={{ width: `${(selected.vision_score * 100).toFixed(1)}%` }}
                        />
                      </div>
                      <span className="font-mono text-sm text-[var(--text)]/70">{(selected.vision_score * 100).toFixed(1)}%</span>
                    </div>
                  </div>
                ) : null}

                {selected.tags && selected.tags.length > 0 && (
                  <div>
                    <div className="micro-label">标签</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {selected.tags.map(t => (
                        <span key={t} className="rounded-ed-sm border border-[var(--line)] bg-[var(--accent-soft)] px-2 py-0.5 text-xs text-[var(--text)]">{t}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 space-y-2">
                <div className="mb-2 micro-label">重新标记</div>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    onClick={() => handleRelabel(selected, 'liked')}
                    disabled={acting || selected.verdict === 'liked'}
                    className={[
                      'rounded-ed-md py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'liked'
                        ? 'border border-[var(--success)]/50 bg-[var(--success-soft)] text-[var(--success)]'
                        : 'border border-[var(--line)] bg-[rgba(255,255,255,0.02)] text-[var(--muted)] hover:bg-[var(--success-soft)] hover:text-[var(--success)]',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👍
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'disliked')}
                    disabled={acting || selected.verdict === 'disliked'}
                    className={[
                      'rounded-ed-md py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'disliked'
                        ? 'border border-[var(--danger)]/50 bg-[var(--danger-soft)] text-[var(--danger)]'
                        : 'border border-[var(--line)] bg-[rgba(255,255,255,0.02)] text-[var(--muted)] hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    👎
                  </button>
                  <button
                    onClick={() => handleRelabel(selected, 'skipped')}
                    disabled={acting || selected.verdict === 'skipped'}
                    className={[
                      'rounded-ed-md py-2.5 text-sm font-medium transition-all',
                      selected.verdict === 'skipped'
                        ? 'border border-[var(--muted)]/30 bg-[rgba(255,255,255,0.04)] text-[var(--muted)]'
                        : 'border border-[var(--line)] bg-[rgba(255,255,255,0.02)] text-[var(--muted)] hover:bg-[rgba(255,255,255,0.06)]',
                      acting ? 'opacity-50' : '',
                    ].join(' ')}
                  >
                    ⏭
                  </button>
                </div>
                <button
                  onClick={() => handleRemoveLabel(selected)}
                  disabled={acting}
                  className="w-full rounded-ed-md border border-[var(--line)] bg-[rgba(255,255,255,0.02)] py-2 text-xs text-[var(--muted)] transition-colors hover:border-[var(--danger)]/30 hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"
                >
                  🗑 移除标记（放回未审阅）
                </button>

                <div className="pt-2 text-center micro-label">
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

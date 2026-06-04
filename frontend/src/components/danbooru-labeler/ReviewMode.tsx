import { useState, useEffect, useCallback, useRef } from 'react'
import Spinner from '../Spinner'
import {
  fetchDanbooruLabelerNext,
  fetchDanbooruCandidateNext,
  danbooruLabelImage,
  danbooruUnlabelImage,
  markDanbooruCandidate,
  getDanbooruExportUrl,
  type DanbooruLabelerNextResponse,
} from '../../api'
import { TagCategoryDisplay, RatingBadge } from './shared'
import TagInput from '../labeler-shared/TagInput'
import VerdictButtons from '../labeler-shared/VerdictButtons'

type DanbooruReviewImage = NonNullable<DanbooruLabelerNextResponse['image']>

export default function ReviewMode() {
  const [image, setImage] = useState<DanbooruReviewImage | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [totalLabeled, setTotalLabeled] = useState(0)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const actingRef = useRef(false)
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
  const [candidateError, setCandidateError] = useState<string | null>(null)
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
    } catch (e) {
      console.error('loadNext failed:', e)
    } finally {
      setLoading(false)
    }
  }, [mediaFilter, ratingFilter, minScore, minAes, source])

  useEffect(() => { loadNext() }, [loadNext])

  const handleVerdict = useCallback(async (verdict: string) => {
    if (!image || actingRef.current) return
    actingRef.current = true
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
        await markDanbooruCandidate(image.id).catch(err => {
          console.error('markDanbooruCandidate failed:', err)
          setCandidateError('AI candidate mark failed, but label was saved.')
        })
      }
      await new Promise(r => setTimeout(r, 300))
      await loadNext()
    } catch {
      setSlideDir('')
    } finally {
      actingRef.current = false
      setActing(false)
    }
  }, [image, tags, loadNext, source])

  const handleUndo = useCallback(async () => {
    if (!lastAction) return
    try {
      await danbooruUnlabelImage(lastAction.imageId)
      setLastAction(null)
      await loadNext()
    } catch (e) { console.error('undo failed:', e) }
  }, [lastAction, loadNext])

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
        <Spinner />
      </div>
    )
  }

  if (!image) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <div className="text-5xl" aria-hidden="true">🎉</div>
        <h2 className="text-xl font-semibold text-[var(--text)]">没有更多图片了！</h2>
        <p className="text-[var(--muted)]">共标注了 {totalLabeled} 张图片，试试调整筛选条件</p>
        <div className="flex gap-3">
          <a
            href={getDanbooruExportUrl('liked')}
            className="rounded-ed-sm bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
          >
            📦 导出喜欢的
          </a>
          <a
            href={getDanbooruExportUrl('liked', undefined, 0)}
            className="rounded-ed-sm bg-blue-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            🖼️ 原始分辨率
          </a>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-5">
      <div className="w-full max-w-2xl">
        <div className="mb-2 flex items-center justify-between text-xs text-[var(--muted)]">
          <span>已标注 {totalLabeled}</span>
          <span>剩余 ~{remaining.toLocaleString()}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface)]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-500 progress-bar-fill"
            style={{ transform: `scaleX(${Math.min(progress, 100) / 100})` }}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
          <div className="flex items-center gap-1.5" role="group" aria-label="媒体筛选">
            {(['', 'image', 'video'] as const).map(m => (
              <button
                key={m}
                onClick={() => setMediaFilter(m)}
                aria-pressed={mediaFilter === m}
                className={`rounded-ed-sm px-2 py-1 transition-all ${mediaFilter === m ? 'bg-[var(--surface)] text-blue-400' : 'text-[var(--muted)] hover:text-[var(--text)]'}`}
              >
                {m === '' ? '全部' : m === 'image' ? '图片' : '视频'}
              </button>
            ))}
          </div>

          <span className="text-[var(--muted)]/50" aria-hidden="true">|</span>

          <div className="flex items-center gap-1.5" role="group" aria-label="Rating筛选">
            <span className="text-[var(--muted)]">Rating:</span>
            {(['', 'g', 's', 'q', 'e'] as const).map(r => (
              <button
                key={r}
                onClick={() => setRatingFilter(r)}
                aria-pressed={ratingFilter === r}
                className={`rounded-ed-sm px-2 py-1 transition-all ${ratingFilter === r ? 'bg-[var(--surface)] text-blue-400' : 'text-[var(--muted)] hover:text-[var(--text)]'}`}
              >
                {r === '' ? 'All' : r.toUpperCase()}
              </button>
            ))}
          </div>

          <span className="text-[var(--muted)]/50" aria-hidden="true">|</span>

          <div className="flex items-center gap-2">
            <label className="text-[var(--muted)]" htmlFor="review-min-score">Score≥</label>
            <input
              id="review-min-score"
              type="range"
              min={0}
              max={1000}
              value={minScoreDisplay}
              onChange={e => setMinScoreDisplay(Number(e.target.value))}
              onMouseUp={e => setMinScore(Number((e.target as HTMLInputElement).value))}
              onTouchEnd={e => setMinScore(Number((e.target as HTMLInputElement).value))}
              className="h-1 w-24 appearance-none rounded-full bg-[var(--surface)] accent-blue-500"
            />
            <span className="min-w-[3ch] text-[var(--muted)]">{minScoreDisplay}</span>
          </div>

          <span className="text-[var(--muted)]/50" aria-hidden="true">|</span>

          <div className="flex items-center gap-1.5" role="radiogroup" aria-label="来源">
            <span className="text-[var(--muted)]">来源:</span>
            <button
              onClick={() => setSource('random')}
              aria-checked={source === 'random'}
              role="radio"
              className={`rounded-ed-sm px-2 py-1 transition-all ${source === 'random' ? 'bg-[var(--surface)] text-blue-400' : 'text-[var(--muted)] hover:text-[var(--text)]'}`}
            >
              🎲 随机
            </button>
            <button
              onClick={() => setSource('ai')}
              aria-checked={source === 'ai'}
              role="radio"
              className={`rounded-ed-sm px-2 py-1 transition-all ${source === 'ai' ? 'bg-purple-500/20 text-purple-300 ring-1 ring-purple-500/30' : 'text-[var(--muted)] hover:text-[var(--text)]'}`}
            >
              🤖 AI推荐
            </button>
          </div>

          {source === 'ai' && (
            <>
              <span className="text-[var(--muted)]/50" aria-hidden="true">|</span>
              <div className="flex items-center gap-2">
                <label className="text-[var(--muted)]" htmlFor="review-min-aes">Aes≥</label>
                <input
                  id="review-min-aes"
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
                  className="h-1 w-24 appearance-none rounded-full bg-[var(--surface)] accent-pink-500"
                />
                <span className="min-w-[3ch] text-pink-300">{minAesDisplay}%</span>
              </div>
            </>
          )}
        </div>
      </div>

      {candidateError && (
        <div className="w-full max-w-2xl rounded-ed-md border border-[var(--warning)]/30 bg-[var(--warning-soft)] px-4 py-2 text-sm text-[var(--warning)]">
          {candidateError}
        </div>
      )}

      <div
        className={[
          'relative w-full max-w-2xl overflow-hidden rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel transition-transform-opacity duration-300',
          slideDir === 'left' ? '-translate-x-full rotate-[-8deg] opacity-0' : '',
          slideDir === 'right' ? 'translate-x-full rotate-[8deg] opacity-0' : '',
          slideDir === 'up' ? '-translate-y-full opacity-0' : '',
        ].join(' ')}
      >
        <div className="flex min-h-[50vh] items-center justify-center bg-[var(--surface)] p-2">
          {image.is_video ? (
            <video
              key={image.id}
              src={image.video_url || image.preview_url}
              className="max-h-[65vh] max-w-full rounded-ed-md"
              controls
              autoPlay
              loop
              muted
            />
          ) : (
            <img
              key={image.id}
              src={image.preview_url}
              alt={'Danbooru #' + image.id}
              className="max-h-[65vh] max-w-full rounded-ed-md object-contain"
              loading="eager"
              onError={async () => { if (source === 'ai' && image) { await markDanbooruCandidate(image.id).catch(err => { console.error('markDanbooruCandidate on error failed:', err) }); loadNext() } }}
            />
          )}
        </div>

        <div className="flex items-center justify-between border-t border-[var(--line)] px-4 py-2 text-xs text-[var(--muted)]">
          <div className="flex items-center gap-2">
            <span>#{image.id}</span>
            <RatingBadge rating={image.rating} />
            <span>Score: {image.score}</span>
            {source === 'ai' && image.preference_score != null && (
              <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${
                image.preference_score >= 0.8 ? 'border-emerald-500/30 bg-emerald-500/20 text-emerald-300' :
                image.preference_score >= 0.5 ? 'border-amber-500/30 bg-amber-500/20 text-amber-300' :
                'border-red-500/30 bg-red-500/20 text-red-300'
              }`}>
                <span aria-hidden="true">🤖</span> {(image.preference_score * 100).toFixed(0)}%
              </span>
            )}
            {source === 'ai' && image.aesthetic_score != null && (
              <span className="rounded border border-pink-500/30 bg-pink-500/20 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-pink-300">
                <span aria-hidden="true">🎨</span> {(image.aesthetic_score * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <span>{image.ext}</span>
        </div>

        {image.tag_categories && Object.keys(image.tag_categories).length > 0 && (
          <div className="border-t border-[var(--line)] px-4 py-3">
            <TagCategoryDisplay tagCategories={image.tag_categories} />
          </div>
        )}
      </div>

      <TagInput tags={tags} onTagsChange={setTags} tagInput={tagInput} onTagInputChange={setTagInput} />

      <VerdictButtons onVerdict={handleVerdict} disabled={acting} />

      <div className="flex items-center gap-4 text-xs text-[var(--muted)]">
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

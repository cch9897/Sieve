import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchLabelerNext,
  labelImage,
  unlabelImage,
  getExportUrl,
  type LabelerNextResponse,
} from '../../api'
import TagInput from '../labeler-shared/TagInput'
import VerdictButtons from '../labeler-shared/VerdictButtons'
import Spinner from '../Spinner'

type ReviewImage = NonNullable<LabelerNextResponse['image']>

export default function ReviewMode() {
  const [image, setImage] = useState<ReviewImage | null>(null)
  const [remaining, setRemaining] = useState(0)
  const [totalLabeled, setTotalLabeled] = useState(0)
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState(false)
  const [tagInput, setTagInput] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [mediaFilter, setMediaFilter] = useState<'' | 'image' | 'video'>('')
  const [lastAction, setLastAction] = useState<{ imageId: number; verdict: string; image: ReviewImage } | null>(null)
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
    } catch (e) {
      console.error('labeler loadNext failed:', e)
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
    setLastAction({ imageId: image.id, verdict, image })

    try {
      await labelImage(image.id, verdict, tags)
      await new Promise(r => setTimeout(r, 300))
      await loadNext()
    } catch (e) {
      console.error('labeler verdict failed:', e)
      setSlideDir('')
    } finally {
      setActing(false)
    }
  }, [image, acting, tags, loadNext])

  const handleUndo = useCallback(async () => {
    if (!lastAction) return
    try {
      await unlabelImage(lastAction.imageId)
      setImage(lastAction.image)
      setRemaining(r => r + 1)
      setTotalLabeled(t => t - 1)
      setLastAction(null)
    } catch (e) { console.error('labeler undo failed:', e) }
  }, [lastAction])

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
        <Spinner size="lg" />
      </div>
    )
  }

  if (!image) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-4 text-center">
        <div className="text-5xl">🎉</div>
        <h2 className="editorial-title text-2xl text-[var(--text)]">全部审阅完了！</h2>
        <p className="text-[var(--muted)]">共标注了 {totalLabeled} 张图片</p>
        <div className="flex gap-3">
          <a
            href={getExportUrl('liked')}
            className="rounded-ed-md border border-[var(--success)]/30 bg-[var(--success-soft)] px-5 py-2.5 text-sm font-medium text-[var(--success)] transition-colors hover:bg-[rgba(52,211,153,0.2)]"
          >
            📦 导出喜欢的
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
            className="rounded-ed-md border border-[var(--info)]/30 bg-[var(--info-soft)] px-5 py-2.5 text-sm font-medium text-[var(--info)] transition-colors hover:bg-[rgba(96,165,250,0.2)]"
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
          <span>已标注 {totalLabeled} / {total}</span>
          <div className="flex gap-3">
            {(['', 'image', 'video'] as const).map(m => (
              <button
                key={m}
                onClick={() => setMediaFilter(m)}
                className={mediaFilter === m ? 'text-[var(--accent)]' : 'hover:text-[var(--text)]'}
              >
                {m === '' ? '全部' : m === 'image' ? '图片' : '视频'}
              </button>
            ))}
          </div>
          <span>剩余 {remaining}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-[rgba(255,255,255,0.05)]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[var(--info)] to-[var(--success)] progress-bar-fill"
            style={{ transform: `scaleX(${progress / 100})` }}
          />
        </div>
      </div>

      <div
        className={[
          'editorial-panel relative w-full max-w-2xl overflow-hidden rounded-ed-xl transition-transform-opacity duration-300',
          slideDir === 'left' ? '-translate-x-full rotate-[-8deg] opacity-0' : '',
          slideDir === 'right' ? 'translate-x-full rotate-[8deg] opacity-0' : '',
          slideDir === 'up' ? '-translate-y-full opacity-0' : '',
        ].join(' ')}
      >
        <div className="flex min-h-[50vh] items-center justify-center bg-[rgba(0,0,0,0.15)] p-2">
          {image.is_video ? (
            <video
              key={image.id}
              src={`/images/${image.file_path}`}
              className="max-h-[65vh] max-w-full rounded-ed-lg"
              controls
              autoPlay
              loop
              muted
            />
          ) : (
            <img
              key={image.id}
              src={`/images/${image.file_path}`}
              alt={image.source + ' ' + image.source_id}
              className="max-h-[65vh] max-w-full rounded-ed-lg object-contain"
              loading="eager"
            />
          )}
        </div>

        <div className="hairline" />

        <div className="flex items-center justify-between px-4 py-2 text-xs text-[var(--muted)]">
          <span>{image.source} · {image.source_id}</span>
          <div className="flex items-center gap-3">
            {image.vision_score != null && (
              <span
                className={[
                  'rounded-ed-sm px-1.5 py-0.5 font-mono text-[11px] font-medium',
                  image.vision_score >= 0.7
                    ? 'bg-[var(--success-soft)] text-[var(--success)]'
                    : image.vision_score >= 0.4
                      ? 'bg-[var(--warning-soft)] text-[var(--warning)]'
                      : 'bg-[var(--danger-soft)] text-[var(--danger)]',
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

      <TagInput tags={tags} onTagsChange={setTags} tagInput={tagInput} onTagInputChange={setTagInput} />

      <VerdictButtons onVerdict={handleVerdict} disabled={acting} />

      <div className="flex items-center gap-4 text-xs text-[var(--muted)]/60">
        {lastAction && (
          <button onClick={handleUndo} className="text-[var(--info)] hover:text-[var(--info)]/80">
            ↩ 撤销上一个
          </button>
        )}
        <span>← 不喜欢 · ↓ 跳过 · → 喜欢 · T 标签 · Ctrl+Z 撤销</span>
      </div>
    </div>
  )
}

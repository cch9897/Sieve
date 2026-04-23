import { useState, useEffect } from 'react'
import DOMPurify from 'dompurify'
import { fetchNovelDetail } from '../api'
import type { NovelItem, NovelDetail } from '../types'
import { formatNum, processNovelText } from '../utils'

interface NovelReaderProps {
  novel: NovelItem
  onBack: () => void
}

export default function NovelReader({ novel, onBack }: NovelReaderProps) {
  const [detail, setDetail] = useState<NovelDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [fontSize, setFontSize] = useState(17)
  const [showMeta, setShowMeta] = useState(false)

  useEffect(() => {
    setLoading(true)
    const controller = new AbortController()
    fetchNovelDetail(novel.id, controller.signal)
      .then(d => setDetail(d))
      .catch(e => { if (!(e instanceof DOMException)) setDetail(null) })
      .finally(() => setLoading(false))
    window.scrollTo(0, 0)
    return () => controller.abort()
  }, [novel.id])

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="h-10 w-28 animate-pulse rounded-ed-sm bg-[rgba(255,255,255,0.05)]" />
        <div className="mt-6 h-8 w-3/4 animate-pulse rounded-ed-sm bg-[rgba(255,255,255,0.05)]" />
        <div className="mt-3 h-5 w-1/2 animate-pulse rounded-ed-sm bg-[rgba(255,255,255,0.05)]" />
        <div className="mt-8 h-[28rem] animate-pulse rounded-ed-xl bg-[rgba(255,255,255,0.05)]" />
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="flex items-center justify-center h-64 text-[var(--muted)]">
        加载小说失败
        <button onClick={() => window.location.reload()} className="ml-3 text-[var(--info)] hover:text-[var(--info)]/80">刷新重试</button>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 pb-24 md:pb-6">
      <div className="sticky z-20 mb-5 flex flex-wrap items-center gap-3 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 backdrop-blur-md md:top-[var(--header-height)] top-[72px]">
        <button
          onClick={onBack}
          className="rounded-ed-sm bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--text)] transition-colors hover:bg-[rgba(255,255,255,0.1)]"
        >
          ← 返回列表
        </button>

        <div className="ml-auto flex items-center gap-2 rounded-ed-sm border border-[var(--line)] bg-[var(--panel)] px-2 py-1.5">
          <span className="px-1 text-xs text-[var(--muted)]">字号</span>
          <button
            onClick={() => setFontSize(f => Math.max(13, f - 1))}
            aria-label="减小字号"
            className="flex h-8 w-8 items-center justify-center rounded-ed-sm bg-[rgba(255,255,255,0.06)] text-[var(--text)]/80 transition-colors hover:bg-[rgba(255,255,255,0.1)]"
          >
            A-
          </button>
          <span className="w-8 text-center text-sm text-[var(--text)]/80">{fontSize}</span>
          <button
            onClick={() => setFontSize(f => Math.min(26, f + 1))}
            aria-label="增大字号"
            className="flex h-8 w-8 items-center justify-center rounded-ed-sm bg-[rgba(255,255,255,0.06)] text-[var(--text)]/80 transition-colors hover:bg-[rgba(255,255,255,0.1)]"
          >
            A+
          </button>
        </div>
      </div>

      <article className="editorial-panel rounded-ed-xl p-5 md:p-8">
        <header className="border-b border-[var(--line)] pb-6">
          <div className="flex flex-wrap items-center gap-2">
            {detail.r18 && <span className="rounded-full bg-[var(--danger-soft)] px-2.5 py-1 text-xs text-[var(--danger)]">R18</span>}
            {detail.series_title && <span className="rounded-full bg-[rgba(255,255,255,0.05)] px-2.5 py-1 text-xs text-[var(--muted)]">系列作品</span>}
          </div>

          <h1 className="mt-3 text-2xl font-bold leading-relaxed text-[var(--text)]">
            {detail.title}
          </h1>

          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-[var(--muted)]">
            <span>✏️ {detail.author || '未知作者'}</span>
            <span>{formatNum(detail.text_length)} 字</span>
            <span>❤️ {formatNum(detail.total_bookmarks)}</span>
            <span>👁 {formatNum(detail.total_view)}</span>
            {detail.series_title && (
              <span className="text-[var(--muted)]">📚 {detail.series_title}</span>
            )}
            <a
              href={detail.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--info)] transition-colors hover:text-[var(--info)]/80"
            >
              打开 Pixiv →
            </a>
          </div>

          <button
            onClick={() => setShowMeta(!showMeta)}
            className="mt-4 rounded-ed-sm px-2 py-1 text-xs text-[var(--muted)] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)]/90"
          >
            {showMeta ? '收起详情 ▲' : '展开详情 ▼'}
          </button>

          {showMeta && (
            <div className="mt-3 space-y-3 rounded-ed-md border border-[var(--line)] bg-[rgba(0,0,0,0.16)] p-4">
              <div className="flex flex-wrap gap-2">
                {detail.tags.map((tag, i) => (
                  <span
                    key={i}
                    className="rounded-full border border-[var(--line)] bg-[rgba(0,0,0,0.16)] px-2.5 py-1 text-xs text-[var(--text)]/80"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              {detail.caption && (
                <div
                  className="text-sm leading-relaxed text-[var(--muted)]"
                  dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(detail.caption) }}
                />
              )}
            </div>
          )}
        </header>

        <div
          className="mx-auto mt-8 max-w-none text-[var(--text)]/90 whitespace-pre-wrap break-words leading-[2.05] md:max-w-3xl"
          style={{ fontSize: `${fontSize}px` }}
        >
          {processNovelText(detail.text)}
        </div>
      </article>

      <div className="mt-8 flex justify-center">
        <button
          onClick={onBack}
          className="rounded-ed-sm bg-[rgba(255,255,255,0.06)] px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-[rgba(255,255,255,0.1)]"
        >
          ← 返回列表
        </button>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { fetchNovelDetail } from '../api'
import type { NovelItem, NovelDetail } from '../types'

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
    fetchNovelDetail(novel.id)
      .then(d => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false))
    window.scrollTo(0, 0)
  }, [novel.id])

  const formatNum = (n: number) => {
    if (n >= 10000) return (n / 10000).toFixed(1) + '万'
    if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
    return String(n)
  }

  const processText = (text: string): string => {
    if (!text) return ''
    text = text.replace(/\[newpage\]/g, '\n\n─────────────\n\n')
    text = text.replace(/\[chapter:(.*?)\]/g, '\n\n【$1】\n\n')
    text = text.replace(/\[pixivimage:(\d+)(?:-(\d+))?\]/g, '🖼️ [插图 pixiv/$1]')
    text = text.replace(/\[jump:(\d+)\]/g, '')
    text = text.replace(/\[\[rb:(.*?)\s*>\s*(.*?)\]\]/g, '$1($2)')
    return text
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <div className="h-10 w-28 animate-pulse rounded-xl bg-dark-900" />
        <div className="mt-6 h-8 w-3/4 animate-pulse rounded-xl bg-dark-900" />
        <div className="mt-3 h-5 w-1/2 animate-pulse rounded-xl bg-dark-900" />
        <div className="mt-8 h-[28rem] animate-pulse rounded-3xl bg-dark-900" />
      </div>
    )
  }

  if (!detail) {
    return (
      <div className="flex items-center justify-center h-64 text-dark-500">
        Failed to load novel
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6 pb-24 md:pb-6">
      <div className="sticky top-[72px] z-20 mb-5 flex flex-wrap items-center gap-3 rounded-2xl border border-dark-700/50 bg-dark-950/85 px-4 py-3 backdrop-blur-xl md:top-20">
        <button
          onClick={onBack}
          className="rounded-xl bg-dark-800 px-3 py-2 text-sm text-dark-200 transition-colors hover:bg-dark-700 hover:text-white"
        >
          ← 返回列表
        </button>

        <div className="ml-auto flex items-center gap-2 rounded-xl border border-dark-700/60 bg-dark-900 px-2 py-1.5">
          <span className="px-1 text-xs text-dark-500">字号</span>
          <button
            onClick={() => setFontSize(f => Math.max(13, f - 1))}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-dark-800 text-dark-300 transition-colors hover:bg-dark-700"
          >
            A-
          </button>
          <span className="w-8 text-center text-sm text-dark-300">{fontSize}</span>
          <button
            onClick={() => setFontSize(f => Math.min(26, f + 1))}
            className="flex h-8 w-8 items-center justify-center rounded-lg bg-dark-800 text-dark-300 transition-colors hover:bg-dark-700"
          >
            A+
          </button>
        </div>
      </div>

      <article className="rounded-[28px] border border-dark-700/50 bg-dark-900/80 p-5 shadow-sm md:p-8">
        <header className="border-b border-dark-800/70 pb-6">
          <div className="flex flex-wrap items-center gap-2">
            {detail.r18 && <span className="rounded-full bg-rose-500/15 px-2.5 py-1 text-xs text-rose-200">R18</span>}
            {detail.series_title && <span className="rounded-full bg-dark-800 px-2.5 py-1 text-xs text-dark-400">系列作品</span>}
          </div>

          <h1 className="mt-3 text-2xl font-bold leading-relaxed text-dark-50">
            {detail.title}
          </h1>

          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-dark-400">
            <span>✏️ {detail.author || '未知作者'}</span>
            <span>{formatNum(detail.text_length)} 字</span>
            <span>❤️ {formatNum(detail.total_bookmarks)}</span>
            <span>👁 {formatNum(detail.total_view)}</span>
            {detail.series_title && (
              <span className="text-dark-500">📚 {detail.series_title}</span>
            )}
            <a
              href={detail.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 transition-colors hover:text-blue-300"
            >
              打开 Pixiv →
            </a>
          </div>

          <button
            onClick={() => setShowMeta(!showMeta)}
            className="mt-4 rounded-lg px-2 py-1 text-xs text-dark-500 transition-colors hover:bg-dark-800 hover:text-dark-200"
          >
            {showMeta ? '收起详情 ▲' : '展开详情 ▼'}
          </button>

          {showMeta && (
            <div className="mt-3 space-y-3 rounded-2xl border border-dark-700/50 bg-dark-950/70 p-4">
              <div className="flex flex-wrap gap-2">
                {detail.tags.map((tag, i) => (
                  <span
                    key={i}
                    className="rounded-full border border-dark-700/70 bg-dark-900 px-2.5 py-1 text-xs text-dark-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              {detail.caption && (
                <div
                  className="text-sm leading-relaxed text-dark-400"
                  dangerouslySetInnerHTML={{ __html: detail.caption }}
                />
              )}
            </div>
          )}
        </header>

        <div
          className="mx-auto mt-8 max-w-none text-dark-200 whitespace-pre-wrap break-words leading-[2.05] md:max-w-3xl"
          style={{ fontSize: `${fontSize}px` }}
        >
          {processText(detail.text)}
        </div>
      </article>

      <div className="mt-8 flex justify-center">
        <button
          onClick={onBack}
          className="rounded-xl bg-dark-800 px-4 py-2 text-sm text-dark-200 transition-colors hover:bg-dark-700 hover:text-white"
        >
          ← 返回列表
        </button>
      </div>
    </div>
  )
}

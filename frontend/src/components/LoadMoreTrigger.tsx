import { useEffect, useRef } from 'react'

interface LoadMoreTriggerProps {
  hasMore: boolean
  loading?: boolean
  onLoadMore?: () => void
  summary?: string
  endText?: string
}

export default function LoadMoreTrigger({
  hasMore,
  loading = false,
  onLoadMore,
  summary,
  endText = '已经到底了',
}: LoadMoreTriggerProps) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hasMore || loading || !ref.current || !onLoadMore) return

    const observer = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting) onLoadMore()
      },
      { rootMargin: '240px 0px' },
    )

    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [hasMore, loading, onLoadMore])

  return (
    <div className="px-4 py-6">
      <div
        ref={ref}
        className="mx-auto flex max-w-3xl flex-col items-center gap-3 rounded-2xl border border-dark-700/60 bg-dark-900/70 px-4 py-4 text-center"
      >
        {summary && <div className="text-sm text-dark-400">{summary}</div>}

        {hasMore ? (
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="rounded-xl bg-dark-700 px-4 py-2 text-sm text-dark-100 transition-colors hover:bg-dark-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? '加载中…' : '加载更多'}
          </button>
        ) : (
          <div className="text-xs text-dark-600">{endText}</div>
        )}
      </div>
    </div>
  )
}

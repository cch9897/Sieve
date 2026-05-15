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
        className="editorial-panel mx-auto flex max-w-3xl flex-col items-center gap-3 px-4 py-4 text-center"
      >
        {summary && <div className="text-sm text-[var(--muted)]">{summary}</div>}

        {hasMore ? (
          <button
            onClick={onLoadMore}
            disabled={loading}
            className="rounded-ed-md border border-[var(--line-strong)] bg-[var(--accent-soft)] px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-[rgba(214,165,93,0.2)] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? '加载中…' : '加载更多'}
          </button>
        ) : (
          <div className="micro-label">{endText}</div>
        )}
      </div>
    </div>
  )
}

import { memo } from 'react'

interface PaginationProps {
  page: number
  pages: number
  onPageChange: (p: number) => void
}

export default memo(function Pagination({ page, pages, onPageChange }: PaginationProps) {
  if (pages <= 1) return null

  const range: number[] = []
  const start = Math.max(1, page - 2)
  const end = Math.min(pages, page + 2)
  for (let i = start; i <= end; i++) range.push(i)

  return (
    <div className="px-4 py-8" role="navigation" aria-label="分页导航">
      <div className="editorial-panel mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-2 px-4 py-3">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-ed-sm px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          上一页
        </button>

        {start > 1 && (
          <>
            <button onClick={() => onPageChange(1)} className="rounded-ed-sm px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)]" aria-label="第1页">1</button>
            {start > 2 && <span className="px-1 text-[var(--muted)]/50" aria-hidden="true">…</span>}
          </>
        )}

        {range.map(p => (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            className={[
              'min-w-10 rounded-ed-sm px-3 py-2 text-sm transition-all duration-200',
              p === page
                ? 'border border-[var(--line-strong)] bg-[linear-gradient(180deg,rgba(214,165,93,0.24),rgba(159,91,82,0.14))] text-[var(--text)] shadow-[0_8px_20px_rgba(0,0,0,0.2)]'
                : 'text-[var(--muted)] hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)]',
            ].join(' ')}
            aria-current={p === page ? 'page' : undefined}
            aria-label={`第${p}页`}
          >
            {p}
          </button>
        ))}

        {end < pages && (
          <>
            {end < pages - 1 && <span className="px-1 text-[var(--muted)]/50" aria-hidden="true">…</span>}
            <button onClick={() => onPageChange(pages)} className="rounded-ed-sm px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)]" aria-label={`第${pages}页`}>{pages}</button>
          </>
        )}

        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          className="rounded-ed-sm px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[rgba(255,255,255,0.04)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-30"
        >
          下一页
        </button>

        <span className="ml-2 micro-label">第 {page} / {pages} 页</span>
      </div>
    </div>
  )
})

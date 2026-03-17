interface PaginationProps {
  page: number
  pages: number
  onPageChange: (p: number) => void
}

export default function Pagination({ page, pages, onPageChange }: PaginationProps) {
  if (pages <= 1) return null

  const range: number[] = []
  const start = Math.max(1, page - 2)
  const end = Math.min(pages, page + 2)
  for (let i = start; i <= end; i++) range.push(i)

  return (
    <div className="px-4 py-8">
      <div className="mx-auto flex max-w-3xl flex-wrap items-center justify-center gap-2 rounded-2xl border border-dark-700/60 bg-dark-900/70 px-4 py-3 shadow-sm">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="rounded-xl px-3 py-2 text-sm text-dark-300 transition-colors hover:bg-dark-800 disabled:cursor-not-allowed disabled:opacity-30"
        >
          上一页
        </button>

        {start > 1 && (
          <>
            <button onClick={() => onPageChange(1)} className="rounded-xl px-3 py-2 text-sm text-dark-400 transition-colors hover:bg-dark-800">1</button>
            {start > 2 && <span className="px-1 text-dark-600">…</span>}
          </>
        )}

        {range.map(p => (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            className={[
              'min-w-10 rounded-xl px-3 py-2 text-sm transition-colors',
              p === page
                ? 'bg-dark-700 text-dark-50 shadow-sm'
                : 'text-dark-400 hover:bg-dark-800',
            ].join(' ')}
          >
            {p}
          </button>
        ))}

        {end < pages && (
          <>
            {end < pages - 1 && <span className="px-1 text-dark-600">…</span>}
            <button onClick={() => onPageChange(pages)} className="rounded-xl px-3 py-2 text-sm text-dark-400 transition-colors hover:bg-dark-800">{pages}</button>
          </>
        )}

        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          className="rounded-xl px-3 py-2 text-sm text-dark-300 transition-colors hover:bg-dark-800 disabled:cursor-not-allowed disabled:opacity-30"
        >
          下一页
        </button>

        <span className="ml-2 text-xs text-dark-500">第 {page} / {pages} 页</span>
      </div>
    </div>
  )
}

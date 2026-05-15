export const TAG_CAT_COLORS: Record<string, { bg: string; text: string; label: string }> = {
  artist: { bg: 'border-[rgba(248,113,113,0.3)] bg-[var(--danger-soft)]', text: 'text-[var(--danger)]', label: '画师' },
  character: { bg: 'border-[rgba(52,211,153,0.3)] bg-[var(--success-soft)]', text: 'text-[var(--success)]', label: '角色' },
  copyright: { bg: 'border-[rgba(167,139,250,0.3)] bg-[var(--purple-soft)]', text: 'text-[var(--purple)]', label: '作品' },
  general: { bg: 'border-[rgba(96,165,250,0.3)] bg-[var(--info-soft)]', text: 'text-[var(--info)]', label: '通用' },
  meta: { bg: 'border-[rgba(251,191,36,0.3)] bg-[var(--warning-soft)]', text: 'text-[var(--warning)]', label: '元' },
}

export function TagCategoryDisplay({ tagCategories }: { tagCategories: Record<string, string[]> }) {
  const order = ['artist', 'character', 'copyright', 'general', 'meta']
  const entries = order
    .filter(cat => tagCategories[cat] && tagCategories[cat].length > 0)
    .map(cat => ({ cat, tags: tagCategories[cat] }))

  if (entries.length === 0) return null

  return (
    <div className="space-y-2">
      {entries.map(({ cat, tags }) => {
        const colors = TAG_CAT_COLORS[cat] || TAG_CAT_COLORS.general
        return (
          <div key={cat}>
            <div className={`mb-1 text-[10px] uppercase tracking-[0.2em] ${colors.text}`}>
              {colors.label} ({tags.length})
            </div>
            <div className="flex flex-wrap gap-1">
              {tags.slice(0, 20).map(t => (
                <span
                  key={t}
                  className={`rounded border px-1.5 py-0.5 text-[11px] ${colors.bg} ${colors.text}`}
                >
                  {t.replace(/_/g, ' ')}
                </span>
              ))}
              {tags.length > 20 && (
                <span className="px-1 text-[11px] text-[var(--muted)]">+{tags.length - 20}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function RatingBadge({ rating }: { rating: string }) {
  const colors: Record<string, string> = {
    s: 'border-[rgba(52,211,153,0.3)] bg-[var(--success-soft)] text-[var(--success)]',
    q: 'border-[rgba(251,191,36,0.3)] bg-[var(--warning-soft)] text-[var(--warning)]',
    e: 'border-[rgba(248,113,113,0.3)] bg-[var(--danger-soft)] text-[var(--danger)]',
    g: 'border-[rgba(96,165,250,0.3)] bg-[var(--info-soft)] text-[var(--info)]',
  }
  const labels: Record<string, string> = { s: 'Safe', q: 'Questionable', e: 'Explicit', g: 'General' }
  return (
    <span className={`rounded border px-2 py-0.5 text-xs ${colors[rating] || 'border-[var(--line)] bg-[rgba(255,255,255,0.03)] text-[var(--muted)]'}`}>
      {labels[rating] || rating}
    </span>
  )
}

export function ScoreBadge({ score }: { score: number }) {
  const pct = (score * 100).toFixed(0)
  const color =
    score >= 0.8 ? 'border-[rgba(52,211,153,0.3)] bg-[var(--success-soft)] text-[var(--success)]' :
    score >= 0.5 ? 'border-[rgba(251,191,36,0.3)] bg-[var(--warning-soft)] text-[var(--warning)]' :
    'border-[rgba(248,113,113,0.3)] bg-[var(--danger-soft)] text-[var(--danger)]'
  return (
    <span className={`rounded border px-1.5 py-0.5 text-[11px] font-semibold tabular-nums ${color}`}>
      {pct}%
    </span>
  )
}

export const RATING_META: Record<string, { label: string; color: string }> = {
  g: { label: 'General', color: '#60a5fa' },
  s: { label: 'Safe', color: '#34d399' },
  q: { label: 'Questionable', color: '#fbbf24' },
  e: { label: 'Explicit', color: '#f87171' },
}

export function getRatingMeta(r: string) {
  return RATING_META[r] || { label: r, color: '#b7a58a' }
}

interface FilterChipProps {
  label: string
  value: string
  onDismiss: () => void
  ariaLabel?: string
}

export default function FilterChip({ label, value, onDismiss, ariaLabel }: FilterChipProps) {
  return (
    <button
      onClick={onDismiss}
      aria-label={ariaLabel || `移除筛选：${value}`}
      className="inline-flex items-center gap-1 rounded-full border border-[var(--line)] bg-[var(--panel-strong)] px-2.5 py-1 text-xs transition-colors hover:border-[var(--line-strong)] hover:text-[var(--text)]/80"
    >
      <span className="text-[10px] uppercase tracking-[0.18em] text-[var(--muted)]/80">{label}</span>
      <span>{value}</span>
      <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-[var(--muted)]">
        <path d="M4 4l8 8M12 4l-8 8"/>
      </svg>
    </button>
  )
}

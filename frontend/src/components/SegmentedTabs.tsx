interface SegmentedTabsProps<T extends string> {
  value: T
  options: Array<{ key: T; label: string; badge?: string | number }>
  onChange: (value: T) => void
  ariaLabel?: string
}

export default function SegmentedTabs<T extends string>({ value, options, onChange, ariaLabel }: SegmentedTabsProps<T>) {
  return (
    <div
      className="inline-flex items-center gap-1 rounded-[22px] border border-[var(--line)] bg-[rgba(12,10,8,0.72)] p-1.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
      role="tablist"
      aria-label={ariaLabel}
    >
      {options.map(option => {
        const active = option.key === value
        return (
          <button
            key={option.key}
            onClick={() => onChange(option.key)}
            role="tab"
            aria-selected={active}
            className={[
              'inline-flex items-center gap-2 rounded-2xl px-3.5 py-2 text-sm transition-all duration-200',
              active
                ? 'border border-[var(--line-strong)] bg-[linear-gradient(180deg,rgba(214,165,93,0.24),rgba(159,91,82,0.14))] text-[var(--text)] shadow-[0_12px_30px_rgba(0,0,0,0.24)]'
                : 'border border-transparent text-[var(--muted)] hover:border-[var(--line)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--text)]',
            ].join(' ')}
          >
            <span>{option.label}</span>
            {option.badge !== undefined && (
              <span
                className={[
                  'rounded-full px-1.5 py-0.5 text-[10px] leading-none',
                  active ? 'bg-black/20 text-[var(--text)]' : 'bg-white/5 text-[var(--muted)]',
                ].join(' ')}
              >
                {option.badge}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

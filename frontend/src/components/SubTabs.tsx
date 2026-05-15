interface SubTabsProps<T extends string> {
  value: T
  options: Array<{ key: T; label: string }>
  onChange: (value: T) => void
  ariaLabel?: string
}

export default function SubTabs<T extends string>({ value, options, onChange, ariaLabel }: SubTabsProps<T>) {
  return (
    <div
      className="inline-flex items-center gap-1 rounded-ed-md border border-[var(--line)] bg-[rgba(12,10,8,0.72)] p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]"
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
              'rounded-ed-sm px-3.5 py-1.5 text-sm transition-all duration-200',
              active
                ? 'border border-[var(--line-strong)] bg-[linear-gradient(180deg,rgba(214,165,93,0.24),rgba(159,91,82,0.14))] text-[var(--text)] shadow-[0_8px_20px_rgba(0,0,0,0.2)]'
                : 'border border-transparent text-[var(--muted)] hover:border-[var(--line)] hover:bg-[rgba(255,255,255,0.03)] hover:text-[var(--text)]',
            ].join(' ')}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

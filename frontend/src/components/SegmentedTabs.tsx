interface SegmentedTabsProps<T extends string> {
  value: T
  options: Array<{ key: T; label: string; badge?: string | number }>
  onChange: (value: T) => void
}

export default function SegmentedTabs<T extends string>({ value, options, onChange }: SegmentedTabsProps<T>) {
  return (
    <div className="inline-flex items-center gap-1 rounded-xl border border-dark-700/70 bg-dark-900/80 p-1 shadow-sm">
      {options.map(option => {
        const active = option.key === value
        return (
          <button
            key={option.key}
            onClick={() => onChange(option.key)}
            className={[
              'inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-all',
              active
                ? 'bg-dark-700 text-dark-50 shadow-sm'
                : 'text-dark-400 hover:bg-dark-800 hover:text-dark-200',
            ].join(' ')}
          >
            <span>{option.label}</span>
            {option.badge !== undefined && (
              <span className={[
                'rounded-full px-1.5 py-0.5 text-[10px] leading-none',
                active ? 'bg-dark-600 text-dark-100' : 'bg-dark-800 text-dark-500',
              ].join(' ')}>
                {option.badge}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

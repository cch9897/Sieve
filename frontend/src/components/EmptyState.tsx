interface EmptyStateProps {
  title: string
  description?: string
  action?: React.ReactNode
}

export default function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-[18rem] flex-col items-center justify-center rounded-2xl border border-dashed border-dark-700/70 bg-dark-900/40 px-6 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-dark-800 text-dark-300">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <path d="M5 7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 5 16.5v-9Z" stroke="currentColor" strokeWidth="1.5"/>
          <path d="m8 15 2.2-2.2a1 1 0 0 1 1.4 0L13 14l1.7-1.7a1 1 0 0 1 1.4 0L17 13.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <circle cx="9" cy="9" r="1" fill="currentColor"/>
        </svg>
      </div>
      <h3 className="text-base font-medium text-dark-100">{title}</h3>
      {description && <p className="mt-2 max-w-md text-sm text-dark-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

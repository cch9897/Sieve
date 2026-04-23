interface EmptyStateProps {
  title: string
  description?: string
  action?: React.ReactNode
}

export default function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="editorial-panel flex min-h-[20rem] flex-col items-center justify-center rounded-[30px] px-6 text-center">
      <div className="micro-label">No Material Found</div>
      <div className="mt-4 mb-4 flex h-14 w-14 items-center justify-center rounded-[22px] border border-[var(--line)] bg-[rgba(255,255,255,0.03)] text-[var(--accent)]">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M5 7.5A2.5 2.5 0 0 1 7.5 5h9A2.5 2.5 0 0 1 19 7.5v9a2.5 2.5 0 0 1-2.5 2.5h-9A2.5 2.5 0 0 1 5 16.5v-9Z" stroke="currentColor" strokeWidth="1.5"/>
          <path d="m8 15 2.2-2.2a1 1 0 0 1 1.4 0L13 14l1.7-1.7a1 1 0 0 1 1.4 0L17 13.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          <circle cx="9" cy="9" r="1" fill="currentColor"/>
        </svg>
      </div>
      <h3 className="editorial-title text-2xl text-[var(--text)]">{title}</h3>
      {description && <p className="mt-3 max-w-md text-sm leading-6 text-[var(--muted)]">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

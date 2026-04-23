interface VerdictButtonsProps {
  onVerdict: (verdict: string) => void
  disabled: boolean
}

export default function VerdictButtons({ onVerdict, disabled }: VerdictButtonsProps) {
  return (
    <div className="flex items-center gap-4">
      <button
        onClick={() => onVerdict('disliked')}
        disabled={disabled}
        className="group flex h-16 w-16 items-center justify-center rounded-full border-2 border-[var(--danger)]/30 bg-[var(--danger-soft)] text-2xl transition-all hover:border-[var(--danger)] hover:bg-[rgba(248,113,113,0.2)] hover:scale-110 active:scale-95 disabled:opacity-50"
        title="不喜欢 (← / H)"
      >
        <span className="transition-transform group-hover:scale-110">👎</span>
      </button>

      <button
        onClick={() => onVerdict('skipped')}
        disabled={disabled}
        className="group flex h-12 w-12 items-center justify-center rounded-full border-2 border-[var(--muted)]/20 bg-[rgba(255,255,255,0.03)] text-lg transition-all hover:border-[var(--muted)]/40 hover:bg-[rgba(255,255,255,0.06)] hover:scale-110 active:scale-95 disabled:opacity-50"
        title="跳过 (↓ / Space)"
      >
        <span className="transition-transform group-hover:scale-110">⏭</span>
      </button>

      <button
        onClick={() => onVerdict('liked')}
        disabled={disabled}
        className="group flex h-16 w-16 items-center justify-center rounded-full border-2 border-[var(--success)]/30 bg-[var(--success-soft)] text-2xl transition-all hover:border-[var(--success)] hover:bg-[rgba(52,211,153,0.2)] hover:scale-110 active:scale-95 disabled:opacity-50"
        title="喜欢 (→ / L)"
      >
        <span className="transition-transform group-hover:scale-110">👍</span>
      </button>
    </div>
  )
}

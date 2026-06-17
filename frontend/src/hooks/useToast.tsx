import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

export type ToastKind = 'success' | 'error' | 'info' | 'warning'

interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastContextValue {
  toast: (message: string, kind?: ToastKind) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextId++
    setToasts(prev => [...prev, { id, kind, message }])
    window.setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id))
    }, 3500)
  }, [])

  const dismiss = useCallback((id: number) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div
        className="fixed bottom-20 right-4 z-[60] flex flex-col gap-2 md:bottom-6"
        role="region"
        aria-label="通知"
        aria-live="polite"
      >
        {toasts.map(t => (
          <div
            key={t.id}
            className={[
              'flex items-center gap-3 rounded-ed-md border px-4 py-3 text-sm shadow-lg shadow-black/30 backdrop-blur-md transition-all duration-300',
              'animate-[slide-in_0.2s_ease]',
              t.kind === 'success' ? 'border-[var(--success)]/30 bg-[rgba(16,42,32,0.92)] text-[var(--success)]'
                : t.kind === 'error' ? 'border-[var(--danger)]/30 bg-[rgba(42,16,16,0.92)] text-[var(--danger)]'
                : t.kind === 'warning' ? 'border-[var(--warning)]/30 bg-[rgba(42,34,12,0.92)] text-[var(--warning)]'
                : 'border-[var(--line-strong)] bg-[var(--panel-strong)] text-[var(--text)]',
            ].join(' ')}
          >
            <span aria-hidden="true">
              {t.kind === 'success' ? '✓' : t.kind === 'error' ? '✕' : t.kind === 'warning' ? '⚠' : 'ℹ'}
            </span>
            <span className="flex-1">{t.message}</span>
            <button
              onClick={() => dismiss(t.id)}
              aria-label="关闭通知"
              className="text-[var(--muted)] transition-colors hover:text-[var(--text)]"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}

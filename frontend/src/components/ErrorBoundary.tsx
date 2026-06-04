import { Component, type ReactNode, type ErrorInfo } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  errorKey: number
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, errorKey: 0 }

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div key={this.state.errorKey} className="archive-shell flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-[var(--text)]">
          <h2 className="editorial-title text-2xl text-[var(--text)]">页面出现错误</h2>
          <button
            onClick={() => this.setState({ hasError: false, errorKey: this.state.errorKey + 1 })}
            className="rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.04)] px-4 py-2 text-sm transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            重试
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-2xl border border-[var(--line)] bg-[rgba(255,255,255,0.04)] px-4 py-2 text-sm transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

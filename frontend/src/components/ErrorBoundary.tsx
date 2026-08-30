import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, info.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    const { error } = this.state
    if (error) {
      if (this.props.fallback) return this.props.fallback(error, this.reset)
      return (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
          <p className="font-medium">Something went wrong rendering this content.</p>
          <p className="mt-1 text-xs text-red-400/80">{error.message}</p>
          <button
            onClick={this.reset}
            className="mt-2 rounded-lg border border-red-500/30 px-3 py-1 text-xs font-medium hover:bg-red-500/10"
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

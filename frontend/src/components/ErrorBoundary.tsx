'use client'

import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, info: { componentStack: string }) => void
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * ErrorBoundary ловит ошибки рендеринга в дочерних компонентах.
 * Используй на уровне страниц чтобы одна сломанная страница
 * не роняла всё приложение.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error('[ErrorBoundary]', error, info.componentStack)
    this.props.onError?.(error, info)
  }

  reset = () => this.setState({ hasError: false, error: null })

  render() {
    if (!this.state.hasError) return this.props.children

    if (this.props.fallback) return this.props.fallback

    return (
      <div style={{
        padding: 32,
        textAlign: 'center',
        color: 'var(--color-text)',
      }}>
        <div style={{ fontSize: 36, marginBottom: 12 }}>⚠️</div>
        <div style={{ fontWeight: 500, marginBottom: 8 }}>
          Что-то пошло не так
        </div>
        <div style={{
          fontSize: 12,
          color: 'var(--color-text-muted)',
          marginBottom: 20,
          maxWidth: 400,
          margin: '0 auto 20px',
          fontFamily: 'monospace',
          background: 'var(--color-surface)',
          padding: '8px 12px',
          borderRadius: 6,
        }}>
          {this.state.error?.message ?? 'Неизвестная ошибка'}
        </div>
        <button
          onClick={this.reset}
          style={{
            padding: '7px 16px',
            borderRadius: 7,
            border: '1px solid var(--color-border)',
            background: 'var(--color-accent)',
            color: '#fff',
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          Попробовать снова
        </button>
      </div>
    )
  }
}

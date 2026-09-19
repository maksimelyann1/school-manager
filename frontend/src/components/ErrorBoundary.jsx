import React from 'react'

export class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props)
        this.state = { hasError: false, error: null }
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error }
    }

    componentDidCatch(error, errorInfo) {
        console.error('ErrorBoundary caught an error:', error, errorInfo)
    }

    handleReset = () => {
        this.setState({ hasError: false, error: null })
        if (this.props.onReset) {
            this.props.onReset()
        }
    }

    render() {
        if (this.state.hasError) {
            return (
                <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: '260px',
                    padding: '32px',
                    textAlign: 'center',
                    background: 'var(--card-bg, #1e293b)',
                    borderRadius: '12px',
                    margin: '24px',
                    border: '1px solid var(--border-color, #334155)',
                    color: 'var(--text-primary, #f8fafc)'
                }}>
                    <h3 style={{ marginBottom: '8px', fontSize: '1.2rem' }}>
                        Виникла помилка під час відображення цієї сторінки
                    </h3>
                    <p style={{ color: 'var(--text-secondary, #94a3b8)', marginBottom: '16px', maxWidth: '500px', fontSize: '0.9rem' }}>
                        {this.state.error?.message || 'Невідома помилка'}
                    </p>
                    <div style={{ display: 'flex', gap: '8px' }}>
                        <button
                            type='button'
                            className='btn btn-primary btn-sm'
                            onClick={this.handleReset}
                        >
                            Спробувати знову
                        </button>
                        <button
                            type='button'
                            className='btn btn-secondary btn-sm'
                            onClick={() => window.location.reload()}
                        >
                            Перезавантажити сторінку
                        </button>
                    </div>
                </div>
            )
        }

        return this.props.children
    }
}

export default ErrorBoundary


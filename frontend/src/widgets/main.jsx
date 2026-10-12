import React from 'react'
import { createRoot } from 'react-dom/client'
import WidgetSurface from './WidgetSurface'
import './Widgets.css'
import { reportClientError } from '../api/client'

window.addEventListener('error', event => reportClientError('Widgets', event.message))
window.addEventListener('unhandledrejection', event => reportClientError('Widgets', event.reason?.message || 'Помилка віджета'))
class WidgetBoundary extends React.Component {
    state = { failed: false }
    static getDerivedStateFromError() { return { failed: true } }
    componentDidCatch(error) { reportClientError('Widgets', error.message) }
    render() { return this.state.failed ? <div className="desktop-widget widget-fallback"><p>Не вдалося показати віджет.</p><button onClick={() => location.reload()}>Спробувати ще раз</button></div> : this.props.children }
}
createRoot(document.getElementById('root')).render(<WidgetBoundary><WidgetSurface /></WidgetBoundary>)

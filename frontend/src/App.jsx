import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ParentsReport from './pages/ParentsReport'
import SendMessage from './pages/SendMessage'
import AutoMessages from './pages/AutoMessages'
import Settings from './pages/Settings'
import Templates from './pages/Templates'
import Logs from './pages/Logs'
import Info from './pages/Info'
import ErrorBoundary from './components/ErrorBoundary'
import AppContextMenu from './components/AppContextMenu'
import TelegramAuthPanel from './components/TelegramAuthPanel'
import Sidebar from './components/Sidebar'
import StartupStatusProvider from './components/StartupStatusContext'
import logoUrl from './assets/logo.png'
import { API_URL, reportClientError } from './api/client'

const TaskPlanner = lazy(() => import('./pages/TaskPlanner'))


function AuthGate() {
    const navigate = useNavigate()
    const { pathname } = useLocation()
    const isPlanner = pathname === '/tasks' || pathname === '/tasks/widget'
    const [checking, setChecking] = useState(true)
    const [isConnected, setIsConnected] = useState(true)
    const [checkError, setCheckError] = useState('')

    const hasUsableTelegramAuth = (status) => {
        return !!status?.is_connected || !!status?.has_session
    }

    const checkTelegramAuth = async () => {
        setChecking(true)
        try {
            const res = await fetch(`${API_URL}/settings/bot`)
            const data = await res.json()
            if (!res.ok) throw new Error(data.detail || data.error || 'Не вдалося перевірити авторизацію Telegram')
            setIsConnected(hasUsableTelegramAuth(data))
            setCheckError('')
        } catch (error) {
            setIsConnected(false)
            setCheckError(error.message || 'Не вдалося перевірити авторизацію Telegram')
        } finally {
            setChecking(false)
        }
    }

    useEffect(() => {
        const handleGlobalError = (event) => {
            reportClientError('Frontend', event.message || event.error?.message || 'Помилка клієнта')
        }
        const handleRejection = (event) => {
            reportClientError('Frontend', `Невідловлена помилка: ${event.reason?.message || event.reason}`)
        }
        window.addEventListener('error', handleGlobalError)
        window.addEventListener('unhandledrejection', handleRejection)
        checkTelegramAuth()
        return () => {
            window.removeEventListener('error', handleGlobalError)
            window.removeEventListener('unhandledrejection', handleRejection)
        }
    }, [])

    useEffect(() => {
        const handleStatus = (event) => {
            if (typeof event.detail?.isConnected === 'boolean') {
                const nextIsAvailable = event.detail.isConnected || !!event.detail?.raw?.has_session
                setIsConnected(nextIsAvailable)
                if (event.detail.isConnected) {
                    setCheckError('')
                    if (!isConnected && !isPlanner) navigate('/', { replace: true })
                }
            }
        }
        window.addEventListener('telegram-auth-status', handleStatus)
        return () => window.removeEventListener('telegram-auth-status', handleStatus)
    }, [isConnected, isPlanner, navigate])

    if (checking || isConnected || isPlanner) return null

    return (
        <div className="modal-overlay auth-required-overlay" role="presentation">
            <div className="modal auth-required-modal" role="dialog" aria-modal="true" aria-labelledby="auth-required-title">
                <div className="auth-required-hero">
                    <img src={logoUrl} alt="" className="auth-required-logo" />
                    <div>
                        <h2 id="auth-required-title">Потрібна авторизація Telegram</h2>
                        <p>Підключіть робочий Telegram акаунт, щоб програма могла синхронізувати групи та планувати повідомлення.</p>
                    </div>
                </div>
                {checkError && (
                    <div className="alert alert-error">
                        {checkError}
                    </div>
                )}
                <TelegramAuthPanel
                    mode="modal"
                    showLogoutActions={false}
                    onAuthorized={async () => {
                        await checkTelegramAuth()
                        navigate('/', { replace: true })
                    }}
                    onStatusChange={({ isConnected: nextIsConnected, raw }) => {
                        if (nextIsConnected || raw?.has_session) {
                            setIsConnected(true)
                            if (nextIsConnected) navigate('/', { replace: true })
                        }
                    }}
                />
                <button className="btn btn-secondary" onClick={() => navigate('/tasks')}>
                    Відкрити задачник без Telegram
                </button>
            </div>
        </div>
    )
}

function App() {
    return (
        <BrowserRouter>
            <StartupStatusProvider>
            <div className="app">
                <Sidebar />

                {/* Основний контент */}
                <main className="main-content">
                    <ErrorBoundary>
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/parents-report" element={<ParentsReport />} />
                        <Route path="/tasks" element={<Suspense fallback={<p role="status">Завантаження календаря…</p>}><ErrorBoundary><TaskPlanner /></ErrorBoundary></Suspense>} />
                        <Route path="/tasks/widget" element={<Suspense fallback={<p role="status">Завантаження задач…</p>}><ErrorBoundary><TaskPlanner widget /></ErrorBoundary></Suspense>} />
                        <Route path="/messages" element={<SendMessage />} />
                        <Route path="/auto-messages" element={<AutoMessages />} />
                        <Route path="/settings" element={<Settings />} />
                        <Route path="/templates" element={<Templates />} />
                        <Route path="/logs" element={<Logs />} />
                        <Route path="/info" element={<Info />} />
                    </Routes>
                    </ErrorBoundary>
                </main>
            </div>
            <AuthGate />
            <AppContextMenu />
            </StartupStatusProvider>
        </BrowserRouter>
    )
}

export default App

import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, NavLink, useNavigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ParentsReport from './pages/ParentsReport'
import SendMessage from './pages/SendMessage'
import AutoMessages from './pages/AutoMessages'
import Settings from './pages/Settings'
import Templates from './pages/Templates'
import Logs from './pages/Logs'
import Info from './pages/Info'
import AppContextMenu from './components/AppContextMenu'
import TelegramAuthPanel from './components/TelegramAuthPanel'
import logoUrl from './assets/logo.png'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

// Іконки SVG
const Icons = {
    message: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
    ),
    clock: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <polyline points="12 6 12 12 16 14" />
        </svg>
    ),
    settings: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
    ),
    telegram: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .37z" />
        </svg>
    ),
    template: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
        </svg>
    ),
    logs: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="4 7 4 4 20 4 20 7" />
            <line x1="9" y1="20" x2="15" y2="20" />
            <line x1="12" y1="4" x2="12" y2="20" />
        </svg>
    ),
    dashboard: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <rect x="3" y="3" width="7" height="9"></rect>
            <rect x="14" y="3" width="7" height="5"></rect>
            <rect x="14" y="12" width="7" height="9"></rect>
            <rect x="3" y="16" width="7" height="5"></rect>
        </svg>
    ),
    parentsReport: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="M8 13h8" />
            <path d="M8 17h5" />
            <path d="M8 9h2" />
        </svg>
    ),
    info: (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
    )
}

function AuthGate() {
    const navigate = useNavigate()
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
        checkTelegramAuth()
    }, [])

    useEffect(() => {
        const handleStatus = (event) => {
            if (typeof event.detail?.isConnected === 'boolean') {
                const nextIsAvailable = event.detail.isConnected || !!event.detail?.raw?.has_session
                setIsConnected(nextIsAvailable)
                if (event.detail.isConnected) {
                    setCheckError('')
                    if (!isConnected) navigate('/', { replace: true })
                }
            }
        }
        window.addEventListener('telegram-auth-status', handleStatus)
        return () => window.removeEventListener('telegram-auth-status', handleStatus)
    }, [isConnected, navigate])

    if (checking || isConnected) return null

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
            </div>
        </div>
    )
}

function App() {
    return (
        <BrowserRouter>
            <div className="app">
                {/* Бічна панель */}
                <aside className="sidebar">
                    <div className="sidebar-logo">
                        <img src={logoUrl} alt="" className="sidebar-logo-image" />
                        <h1>Менеджер Груп</h1>
                    </div>

                    <nav className="sidebar-nav">
                        <ul className="nav-menu">
                            <li>
                                <NavLink
                                    to="/"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                    end
                                >
                                    {Icons.dashboard}
                                    <span>Головна</span>
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/parents-report"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.parentsReport}
                                    <span>Звіт батькам</span>
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/messages"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.message}
                                    <span>Повідомлення</span>
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/auto-messages"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.clock}
                                    <span>Автоповідомлення</span>
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/templates"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.template}
                                    <span>Шаблони</span>
                                </NavLink>
                            </li>
                            <li>
                                <NavLink
                                    to="/logs"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.logs}
                                    <span>Журнал подій</span>
                                </NavLink>
                            </li>
                        </ul>
                        <ul className="nav-menu nav-menu-service">
                            <li>
                                <NavLink
                                    to="/settings"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.settings}
                                    <span>Налаштування</span>
                                </NavLink>
                            </li>
                        </ul>
                        <ul className="nav-menu nav-menu-bottom">
                            <li>
                                <NavLink
                                    to="/info"
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                >
                                    {Icons.info}
                                    <span>Інфо</span>
                                </NavLink>
                            </li>
                        </ul>
                    </nav>
                </aside>

                {/* Основний контент */}
                <main className="main-content">
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/parents-report" element={<ParentsReport />} />
                        <Route path="/messages" element={<SendMessage />} />
                        <Route path="/auto-messages" element={<AutoMessages />} />
                        <Route path="/settings" element={<Settings />} />
                        <Route path="/templates" element={<Templates />} />
                        <Route path="/logs" element={<Logs />} />
                        <Route path="/info" element={<Info />} />
                    </Routes>
                </main>
            </div>
            <AuthGate />
            <AppContextMenu />
        </BrowserRouter>
    )
}

export default App

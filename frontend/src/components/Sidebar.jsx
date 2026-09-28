import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { NavLink } from 'react-router-dom'
import SidebarIcon from './SidebarIcon'
import logoUrl from '../assets/logo.png'
import { api } from '../api/client'
import { useToast } from './ToastProvider'
import './Sidebar.css'

const STORAGE_KEY = 'school-manager.sidebar-collapsed'
const sections = [
    { items: [
        ['/', 'home', 'Головна'],
        ['/parents-report', 'report', 'Звіт батькам'],
        ['/tasks', 'planner', 'Задачник'],
        ['/messages', 'message', 'Повідомлення'],
        ['/auto-messages', 'scheduled', 'Автоповідомлення'],
        ['/templates', 'template', 'Шаблони'],
        ['/logs', 'journal', 'Журнал подій'],
    ] },
    { className: 'nav-menu-service', items: [['/settings', 'settings', 'Налаштування']] },
    { className: 'nav-menu-bottom', items: [['/info', 'help', 'Допомога']] },
]

export default function Sidebar() {
    const [collapsed, setCollapsed] = useState(() => {
        try { return localStorage.getItem(STORAGE_KEY) === 'true' } catch { return false }
    })
    const [tooltip, setTooltip] = useState(null)
    const [settingsLoaded, setSettingsLoaded] = useState(false)
    const [saving, setSaving] = useState(false)
    const saveInFlight = useRef(false)
    const { showToast } = useToast()

    useEffect(() => {
        const controller = new AbortController()
        api.get('/settings/interface', { signal: controller.signal })
            .then(settings => {
                if (!controller.signal.aborted) setCollapsed(settings.sidebar_collapsed)
            })
            .catch(error => {
                if (!controller.signal.aborted) console.error('Не вдалося прочитати стан меню:', error)
            })
            .finally(() => { if (!controller.signal.aborted) setSettingsLoaded(true) })
        return () => controller.abort()
    }, [])

    useEffect(() => {
        try { localStorage.setItem(STORAGE_KEY, String(collapsed)) } catch { /* Storage may be unavailable. */ }
    }, [collapsed])

    const toggleSidebar = async () => {
        if (!settingsLoaded || saveInFlight.current) return
        const previous = collapsed
        const next = !previous
        saveInFlight.current = true
        setSaving(true)
        setTooltip(null)
        setCollapsed(next)
        try {
            await api.put('/settings/interface', { sidebar_collapsed: next }, { keepalive: true })
        } catch {
            setCollapsed(previous)
            showToast({ type: 'error', text: 'Не вдалося зберегти стан меню. Спробуйте ще раз.' })
        } finally {
            saveInFlight.current = false
            setSaving(false)
        }
    }

    useEffect(() => {
        if (!tooltip) return
        const dismiss = () => setTooltip(null)
        const handleKey = (event) => { if (event.key === 'Escape') dismiss() }
        window.addEventListener('resize', dismiss)
        window.addEventListener('scroll', dismiss, true)
        window.addEventListener('keydown', handleKey)
        return () => {
            window.removeEventListener('resize', dismiss)
            window.removeEventListener('scroll', dismiss, true)
            window.removeEventListener('keydown', handleKey)
        }
    }, [tooltip])

    const showTooltip = (event, id, label) => {
        if (!window.matchMedia('(min-width: 769px)').matches) return
        const rect = event.currentTarget.getBoundingClientRect()
        setTooltip({ id, label, left: rect.right + 12, top: Math.max(24, Math.min(window.innerHeight - 24, rect.top + rect.height / 2)) })
    }
    const hideTooltip = (event) => {
        if (!event.relatedTarget?.closest?.('.sidebar-tooltip')) setTooltip(null)
    }
    const toggleLabel = collapsed ? 'Розгорнути меню' : 'Згорнути меню'

    return (
        <aside className={`sidebar sidebar-collapsible${collapsed ? ' sidebar--collapsed' : ''}`}>
            <div className="sidebar-logo">
                <img src={logoUrl} alt={collapsed ? 'Менеджер Груп' : ''} className="sidebar-logo-image" />
                <h1>Менеджер Груп</h1>
            </div>
            <button type="button" className="sidebar-toggle" aria-label={toggleLabel}
                aria-expanded={!collapsed} aria-controls="sidebar-navigation"
                disabled={!settingsLoaded || saving} aria-busy={saving}
                aria-describedby={tooltip?.id === 'toggle' ? 'sidebar-tooltip' : undefined}
                onClick={toggleSidebar}
                onMouseEnter={event => showTooltip(event, 'toggle', toggleLabel)} onMouseLeave={hideTooltip}
                onFocus={event => showTooltip(event, 'toggle', toggleLabel)} onBlur={() => setTooltip(null)}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={collapsed ? 'm9 6 6 6-6 6' : 'm15 6-6 6 6 6'} />
                </svg>
            </button>
            <nav id="sidebar-navigation" className="sidebar-nav" aria-label="Основна навігація">
                {sections.map((section, index) => (
                    <ul key={index} className={`nav-menu ${section.className || ''}`}>
                        {section.items.map(([path, icon, label]) => (
                            <li key={path}>
                                <NavLink to={path} end={path === '/'} aria-label={label}
                                    aria-describedby={tooltip?.id === icon ? 'sidebar-tooltip' : undefined}
                                    className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
                                    onMouseEnter={event => { if (collapsed) showTooltip(event, icon, label) }}
                                    onFocus={event => { if (collapsed) showTooltip(event, icon, label) }}
                                    onMouseLeave={hideTooltip} onBlur={() => setTooltip(null)} onClick={() => setTooltip(null)}>
                                    <SidebarIcon name={icon} />
                                    <span className="nav-label">{label}</span>
                                </NavLink>
                            </li>
                        ))}
                    </ul>
                ))}
            </nav>
            {tooltip && createPortal(
                <div id="sidebar-tooltip" className="sidebar-tooltip" role="tooltip"
                    style={{ left: tooltip.left, top: tooltip.top }} onMouseLeave={() => setTooltip(null)}>
                    {tooltip.label}
                </div>, document.body,
            )}
        </aside>
    )
}

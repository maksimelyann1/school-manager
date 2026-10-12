import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

const sections = new Set(['/', '/parents-report', '/tasks', '/auto-messages'])

export default function NotificationNavigation() {
    const navigate = useNavigate()
    useEffect(() => {
        const activate = () => {
            const target = window.__schoolManagerPendingNavigation
            delete window.__schoolManagerPendingNavigation
            if (typeof target !== 'string' || !target.startsWith('/') || target.startsWith('//')) return
            const url = new URL(target, window.location.origin)
            if (url.origin !== window.location.origin || !sections.has(url.pathname)) return
            navigate(url.pathname + url.search, { state: { notification: true } })
        }
        window.addEventListener('school-manager-navigate', activate)
        activate()
        return () => window.removeEventListener('school-manager-navigate', activate)
    }, [navigate])
    return null
}

export function useNotificationFocus(id, ready, activationKey) {
    useEffect(() => {
        if (!id || !ready) return
        const frame = requestAnimationFrame(() => {
            const element = document.getElementById(id)
            element?.scrollIntoView({ block: 'center', inline: 'nearest' })
            element?.focus({ preventScroll: true })
        })
        return () => cancelAnimationFrame(frame)
    }, [id, ready, activationKey])
}

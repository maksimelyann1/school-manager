import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

const ToastContext = createContext(null)

let nextToastId = 1

function normalizeToast(input, fallbackText) {
    if (typeof input === 'string') {
        return { type: input, text: fallbackText || '' }
    }
    return {
        type: input?.type || 'info',
        text: input?.text || input?.message || fallbackText || '',
        duration: input?.duration
    }
}

export function ToastProvider({ children }) {
    const [toasts, setToasts] = useState([])
    const timersRef = useRef(new Map())

    const removeToast = useCallback((id) => {
        const timer = timersRef.current.get(id)
        if (timer) {
            window.clearTimeout(timer)
            timersRef.current.delete(id)
        }
        setToasts(prev => prev.filter(toast => toast.id !== id))
    }, [])

    const showToast = useCallback((input, fallbackText) => {
        const toast = normalizeToast(input, fallbackText)
        if (!toast.text) return null

        const id = nextToastId++
        const duration = Number.isFinite(toast.duration) ? toast.duration : 4500
        setToasts(prev => [...prev, { ...toast, id }].slice(-5))

        if (duration > 0) {
            const timer = window.setTimeout(() => removeToast(id), duration)
            timersRef.current.set(id, timer)
        }

        return id
    }, [removeToast])

    const value = useMemo(() => ({
        showToast,
        showAlert: showToast,
        removeToast
    }), [removeToast, showToast])

    return (
        <ToastContext.Provider value={value}>
            {children}
            <div className="toast-root" aria-live="polite" aria-atomic="true">
                {toasts.map(toast => (
                    <div key={toast.id} className={`toast-item toast-${toast.type}`}>
                        {toast.text}
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    )
}

export function useToast() {
    const context = useContext(ToastContext)
    if (!context) {
        return {
            showToast: () => null,
            showAlert: () => null,
            removeToast: () => {}
        }
    }
    return context
}

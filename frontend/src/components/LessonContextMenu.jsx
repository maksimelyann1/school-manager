import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export default function LessonContextMenu({ menu, onClose, onPostpone, onCancel, onPause, disabled }) {
    const ref = useRef(null)
    const [position, setPosition] = useState({ left: menu.x, top: menu.y })
    useLayoutEffect(() => {
        const bounds = ref.current.getBoundingClientRect()
        setPosition({
            left: Math.max(8, Math.min(menu.x, window.innerWidth - bounds.width - 8)),
            top: Math.max(8, Math.min(menu.y, window.innerHeight - bounds.height - 8))
        })
        ref.current.querySelector('button:not(:disabled)')?.focus({ preventScroll: true })
    }, [menu])
    useEffect(() => {
        const closeOutside = event => {
            if (event.type === 'contextmenu' && event.defaultPrevented) return
            if (!ref.current?.contains(event.target)) onClose()
        }
        window.addEventListener('pointerdown', closeOutside)
        window.addEventListener('contextmenu', closeOutside)
        window.addEventListener('scroll', closeOutside, true)
        window.addEventListener('resize', onClose)
        return () => {
            window.removeEventListener('pointerdown', closeOutside)
            window.removeEventListener('contextmenu', closeOutside)
            window.removeEventListener('scroll', closeOutside, true)
            window.removeEventListener('resize', onClose)
        }
    }, [onClose])
    const run = action => {
        onClose()
        action()
    }
    const handleKeyDown = event => {
        if (event.key === 'Escape' || event.key === 'Tab') {
            onClose()
            if (event.key === 'Escape') {
                event.preventDefault()
                menu.anchor?.closest('tr')?.focus({ preventScroll: true })
            }
            return
        }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
        event.preventDefault()
        const buttons = [...ref.current.querySelectorAll('button:not(:disabled)')]
        const current = buttons.indexOf(document.activeElement)
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
            : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
        buttons[index]?.focus()
    }
    return createPortal(
        <div ref={ref} className="app-context-menu parents-lesson-menu" role="menu"
            aria-label="Дії з уроком" style={position} onKeyDown={handleKeyDown}
            onContextMenu={event => event.preventDefault()}>
            <div className="parents-lesson-menu-title">{menu.lesson.group_name}</div>
            <button type="button" role="menuitem" className="app-context-menu-item" disabled={disabled}
                onClick={() => run(() => onPostpone(menu.lesson, menu.anchor))}>
                {menu.lesson.is_postponed ? 'Редагувати перенесення' : 'Перенести урок'}
            </button>
            {menu.lesson.is_postponed && <button type="button" role="menuitem"
                className="app-context-menu-item" disabled={disabled}
                onClick={() => run(() => onCancel(menu.lesson.id))}>Скасувати перенесення</button>}
            <div className="app-context-menu-separator" role="separator" />
            <button type="button" role="menuitem" className="app-context-menu-item" disabled={disabled}
                onClick={() => run(() => onPause(menu.lesson))}>
                {menu.lesson.is_paused ? 'Відновити групу' : 'Поставити групу на паузу'}
            </button>
        </div>, document.body
    )
}

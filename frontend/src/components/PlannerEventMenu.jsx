import { useLayoutEffect, useRef, useState, useEffect } from 'react'
import './PlannerEventMenu.css'

const colors = [
    ['Лавандовий', '#a4bdfc'], ['Шавлія', '#7ae7bf'], ['Виноградний', '#dbadff'],
    ['Фламінго', '#ff887c'], ['Банановий', '#fbd75b'], ['Мандариновий', '#ffb878'],
    ['Бірюзовий', '#46d6db'], ['Графітовий', '#e1e1e1'], ['Чорничний', '#5484ed'],
    ['Базиліковий', '#51b749'], ['Томатний', '#dc2127'],
]

export default function PlannerEventMenu({ item, x, y, busy, onColor, onDelete, onClose }) {
    const menuRef = useRef(null)
    const [position, setPosition] = useState({ x, y })

    useLayoutEffect(() => {
        const menu = menuRef.current
        if (!menu) return
        const box = menu.getBoundingClientRect()
        setPosition({
            x: Math.max(8, Math.min(x, window.innerWidth - box.width - 8)),
            y: Math.max(8, Math.min(y, window.innerHeight - box.height - 8)),
        })
    }, [x, y])

    useEffect(() => {
        const dismiss = event => { if (!menuRef.current?.contains(event.target)) onClose() }
        const escape = event => { if (event.key === 'Escape') onClose() }
        document.addEventListener('pointerdown', dismiss)
        document.addEventListener('keydown', escape)
        window.addEventListener('resize', onClose)
        window.addEventListener('scroll', onClose, true)
        return () => {
            document.removeEventListener('pointerdown', dismiss)
            document.removeEventListener('keydown', escape)
            window.removeEventListener('resize', onClose)
            window.removeEventListener('scroll', onClose, true)
        }
    }, [onClose])

    return <div ref={menuRef} className="planner-event-menu" role="menu" aria-label={`Дії з подією: ${item.title}`} style={{ left: position.x, top: position.y }} onContextMenu={event => event.preventDefault()}>
        <button type="button" className="planner-event-menu__delete" role="menuitem" disabled={busy || item.read_only} title={item.read_only ? 'Видалення цієї події недоступне' : undefined} onClick={onDelete}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14M10 10v7m4-7v7" /></svg>
            Видалити
        </button>
        <div className="planner-event-menu__section">
            <span className="planner-event-menu__label">Колір події</span>
            <div className="planner-event-menu__colors" role="group" aria-label="Оберіть колір">
                {colors.map(([name, color]) => <button key={color} type="button" className={`planner-event-menu__swatch ${item.color?.toLowerCase() === color.toLowerCase() ? 'is-selected' : ''}`} aria-label={name} aria-pressed={item.color?.toLowerCase() === color.toLowerCase()} title={name} style={{ backgroundColor: color }} disabled={busy || item.read_only} onClick={() => onColor(color)}>{item.color?.toLowerCase() === color.toLowerCase() ? '✓' : ''}</button>)}
            </div>
            <button type="button" className="planner-event-menu__default" role="menuitem" disabled={busy || item.read_only} onClick={() => onColor(null)}><span className="planner-event-menu__default-dot">{!item.color ? '✓' : ''}</span>За замовчуванням</button>
        </div>
    </div>
}

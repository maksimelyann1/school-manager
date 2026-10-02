import { useLayoutEffect, useRef, useState, useEffect } from 'react'
import './PlannerEventMenu.css'

const colors = [
    ['Малиновий', '#C75072'], ['Рожевий', '#DF6A80'], ['Кораловий', '#E47A77'], ['Теракотовий', '#DD6D50'],
    ['Помаранчевий', '#E9843B'], ['Бурштиновий', '#D99732'], ['Жовтий', '#D7B34B'], ['Пісочний', '#D1C063'],
    ['Лаймовий', '#A6C755'], ['Зелений', '#79B45D'], ['Смарагдовий', '#3DA66E'], ['М’ятний', '#56B690'],
    ['Бірюзовий', '#3FA7A4'], ['Блакитний', '#4D9ED3'], ['Синій', '#5A83D6'], ['Індиго', '#7172C9'],
    ['Лавандовий', '#9E8BCB'], ['Бузковий', '#A77ABE'], ['Пурпуровий', '#A467C0'], ['Сливовий', '#9B688B'],
    ['Сірий', '#6B7280'], ['Тауповий', '#8A8179'], ['Графітовий', '#566070'], ['Темно-зелений', '#417A62'],
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
                {colors.map(([name, color]) => <button key={color} type="button" className={`planner-event-menu__swatch ${item.color?.toLowerCase() === color.toLowerCase() ? 'is-selected' : ''}`} aria-label={name} aria-pressed={item.color?.toLowerCase() === color.toLowerCase()} title={name} style={{ backgroundColor: color }} disabled={busy} onClick={() => onColor(color)}>{item.color?.toLowerCase() === color.toLowerCase() ? '✓' : ''}</button>)}
            </div>
            <button type="button" className="planner-event-menu__default" role="menuitem" disabled={busy} onClick={() => onColor(null)}><span className="planner-event-menu__default-dot">{!item.color ? '✓' : ''}</span>За замовчуванням</button>
        </div>
    </div>
}

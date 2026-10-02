import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { DateTime } from 'luxon'
import { taskCategories } from './PlannerEditor'
import { buildApiUrl } from '../api/client'
import SidebarIcon from './SidebarIcon'
import PlannerDescriptionView from './PlannerDescriptionView'
import './PlannerEventPreview.css'

const formatDay = value => DateTime.fromISO(value).setLocale('uk').toFormat('cccc, d LLLL yyyy')

function formatSchedule(item) {
    if (!item.date) return 'Без дати'
    const startDay = formatDay(item.date)
    if (!item.time) return item.end_date && item.end_date !== item.date
        ? `${startDay} — ${formatDay(item.end_date)} · Увесь день`
        : `${startDay} · Увесь день`
    if (item.end_date && item.end_date !== item.date) {
        return `${startDay}, ${item.time} — ${formatDay(item.end_date)}, ${item.end_time || ''}`
    }
    return `${startDay} · ${item.time}${item.end_time ? ` – ${item.end_time}` : ''}`
}

export default function PlannerEventPreview({ item, anchor, color, busy, onEdit, onDelete, onMore, onClose }) {
    const previewRef = useRef(null)
    const [position, setPosition] = useState({ left: anchor.right + 12, top: anchor.top })

    useLayoutEffect(() => {
        const card = previewRef.current
        if (!card) return
        const box = card.getBoundingClientRect()
        const rightSide = anchor.right + box.width + 12 <= window.innerWidth - 8
        const left = rightSide ? anchor.right + 12 : anchor.left - box.width - 12
        setPosition({
            left: Math.max(8, Math.min(left, window.innerWidth - box.width - 8)),
            top: Math.max(8, Math.min(anchor.top, window.innerHeight - box.height - 8)),
        })
    }, [anchor])

    useEffect(() => {
        const dismiss = event => { if (!previewRef.current?.contains(event.target)) onClose() }
        const onKeyDown = event => {
            if (event.key === 'Escape') onClose()
            if (event.key !== 'Delete' || event.repeat || event.defaultPrevented || busy || item.read_only) return
            if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable], [role="textbox"]')) return
            event.preventDefault()
            onDelete()
        }
        document.addEventListener('pointerdown', dismiss)
        document.addEventListener('keydown', onKeyDown)
        window.addEventListener('resize', onClose)
        window.addEventListener('scroll', onClose, true)
        return () => {
            document.removeEventListener('pointerdown', dismiss)
            document.removeEventListener('keydown', onKeyDown)
            window.removeEventListener('resize', onClose)
            window.removeEventListener('scroll', onClose, true)
        }
    }, [onClose, onDelete, busy, item.read_only])

    return <section ref={previewRef} className="planner-event-preview" role="dialog" aria-label={`Деталі: ${item.title}`} style={position}>
        <div className="planner-event-preview__actions">
            <button type="button" aria-label="Редагувати" title={item.read_only ? 'Редагування недоступне' : 'Редагувати'} disabled={busy || item.read_only} onClick={onEdit}><SidebarIcon name="edit" /></button>
            <button type="button" aria-label="Видалити" title={item.read_only ? 'Видалення недоступне' : 'Видалити'} disabled={busy || item.read_only} onClick={onDelete}><SidebarIcon name="delete" /></button>
            <button type="button" aria-label="Ще дії" title="Ще дії" disabled={busy} onClick={onMore}><SidebarIcon name="more" /></button>
            <button type="button" aria-label="Закрити" title="Закрити" onClick={onClose}><SidebarIcon name="close" /></button>
        </div>
        <div className="planner-event-preview__main">
            <span className="planner-event-preview__marker" style={{ background: color }} aria-hidden="true" />
            <div className="planner-event-preview__content">
                <h3>{item.title}</h3>
                <p className="planner-event-preview__schedule">{formatSchedule(item)}</p>
                <p className="planner-event-preview__meta">{taskCategories[item.category] || 'Подія'} · {item.source === 'google' ? 'Google Календар' : 'У застосунку'}</p>
                {!!item.recurrence?.length && <p className="planner-event-preview__meta">↻ Повторювана подія · зміни для всієї серії</p>}
                {item.sync_error && <p className="planner-error" role="status">{item.sync_error}</p>}
                {item.location && <p className="planner-event-preview__meta">{item.location}</p>}
                {item.meet_url && /^https:\/\/meet\.google\.com\//.test(item.meet_url) && <a className="planner-preview-meet" href={item.meet_url} target="_blank" rel="noreferrer">Приєднатися в Google Meet ↗</a>}
                {item.meet_requested && !item.meet_url && <p className="planner-event-preview__meta">{item.meet_status === 'failure' ? 'Не вдалося створити Meet — відкрийте редактор і збережіть повторно' : 'Meet — очікує синхронізації'}</p>}
                {!!item.attendees?.length && <div className="planner-preview-guests">{item.attendees.map(guest => <p key={guest.email}>{guest.email}<small>{({ accepted: 'Прийнято', declined: 'Відхилено', tentative: 'Під питанням' })[guest.responseStatus] || 'Очікує відповіді'}</small></p>)}</div>}
                {item.description && <div className="planner-event-preview__description"><PlannerDescriptionView value={item.description} /></div>}
                {!!item.attachments?.length && <div className="planner-event-preview__attachments">{item.attachments.map(file => <a key={file.id} href={buildApiUrl(`/tasks/${item.id}/attachments/${file.id}`)}>{file.name}</a>)}</div>}
            </div>
        </div>
    </section>
}

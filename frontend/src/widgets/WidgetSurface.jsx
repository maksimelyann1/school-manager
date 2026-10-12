import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DateTime } from 'luxon'
import { IconLock, IconLockOpen, IconX, IconPlus, IconExternalLink, IconChevronLeft, IconChevronRight, IconRefresh, IconPin, IconGripVertical, IconBell, IconArrowDownRight } from '@tabler/icons-react'
import { api } from '../api/client'
import { announceChange, desktopCall, widgetChannel, widgetKinds } from './bridge'

const TZ = 'Europe/Kyiv'
const now = () => DateTime.now().setZone(TZ)
const day = () => now().toISODate()
const labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']
const itemOnDay = (item, date) => {
    const start = item.time ? DateTime.fromISO(item.start).setZone(TZ).toISODate() : item.date
    const end = item.time ? DateTime.fromISO(item.end || item.start).setZone(TZ).minus({ milliseconds: 1 }).toISODate() : item.end_date || item.date
    return start && start <= date && end >= date
}

export default function WidgetSurface() {
    const id = new URLSearchParams(location.search).get('id')
    const [widget, setWidget] = useState(null)
    const [items, setItems] = useState([])
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(true)
    const [month, setMonth] = useState(() => now().startOf('month').toISODate())
    const [selected, setSelected] = useState(day)
    const [today, setToday] = useState(day)
    const [draft, setDraft] = useState(null)
    const [saving, setSaving] = useState(false)
    const [google, setGoogle] = useState(null)
    const controller = useRef(null)
    const mounted = useRef(false)
    const busy = useRef(false)
    const requestGeneration = useRef(0)
    const resizeStart = useRef(null)
    const resizeOutput = useRef(null)
    const [resizeHint, setResizeHint] = useState(null)
    const first = DateTime.fromISO(month).startOf('week')
    const from = widget?.kind === 'calendar' ? first.toISODate() : today
    const until = widget?.kind === 'calendar' ? first.plus({ days: 42 }).toISODate() : DateTime.fromISO(today).plus({ days: 14 }).toISODate()

    const readSettings = useCallback(async () => {
        if (!window.pywebview?.api?.get_widget_state) return
        const data = await desktopCall('get_widget_state')
        if (mounted.current) { setWidget(data.widget); if (data.error) setError(data.error) }
    }, [])
    useEffect(() => {
        mounted.current = true
        const settings = () => readSettings().catch(() => { if (mounted.current) setError('Не вдалося прочитати налаштування віджета.') })
        settings()
        window.addEventListener('pywebviewready', settings)
        window.addEventListener('widget-settings-changed', settings)
        return () => { mounted.current = false; controller.current?.abort(); window.removeEventListener('pywebviewready', settings); window.removeEventListener('widget-settings-changed', settings) }
    }, [readSettings])

    const load = useCallback(async () => {
        if (!widget) return
        controller.current?.abort()
        const current = new AbortController()
        controller.current = current
        const generation = ++requestGeneration.current
        try {
            const params = new URLSearchParams({ bucket: 'calendar', start: from, end: until, limit: 300, track_activity: false })
            const result = await api.get(widget.kind === 'lessons' ? '/widgets/lessons' : `/tasks?${params}`, { signal: current.signal })
            let entries = result.items
            if (!Array.isArray(entries)) throw new Error('Некоректний список подій')
            if (widget.kind === 'agenda') {
                const undated = await api.get('/tasks?bucket=undated&limit=30&track_activity=false', { signal: current.signal })
                if (!Array.isArray(undated.items)) throw new Error('Некоректний список справ')
                entries = [...entries, ...undated.items]
            }
            if (current.signal.aborted || !mounted.current || generation !== requestGeneration.current) return
            setItems(entries); setError('')
        } catch (err) {
            if (err.name !== 'AbortError' && mounted.current) setError('Не вдалося оновити дані. Попередні записи збережено.')
        } finally { if (!current.signal.aborted && mounted.current) setLoading(false) }
    }, [widget?.kind, from, until])
    useEffect(() => {
        load()
        const refresh = () => { if (!document.hidden) { setToday(day()); load() } }
        const timer = setInterval(refresh, 60000)
        window.addEventListener('focus', refresh)
        const channel = window.BroadcastChannel ? new BroadcastChannel(widgetChannel) : null
        if (channel) channel.onmessage = refresh
        return () => { clearInterval(timer); controller.current?.abort(); window.removeEventListener('focus', refresh); channel?.close() }
    }, [load])

    const changeSettings = async values => {
        try { const result = await desktopCall('update_widget', values); if (mounted.current) setWidget(result.widget); announceChange() }
        catch { setError('Не вдалося зберегти налаштування віджета.') }
    }
    const createDraft = date => {
        setSelected(date)
        setDraft({ title: '', date, time: '09:00', kind: widget?.kind === 'agenda' ? 'task' : 'event', reminder: '0', google_enabled: false, google_calendar_id: '', request_id: crypto.randomUUID() })
        api.get('/planner/google/status').then(data => { if (mounted.current) setGoogle(data) }).catch(() => { if (mounted.current) setGoogle(null) })
    }
    const create = async event => {
        event.preventDefault()
        if (busy.current) return
        if (draft.reminder !== '0' && DateTime.fromISO(`${draft.date}T${draft.time}`, { zone: TZ }).minus({ minutes: Number(draft.reminder) }) <= now()) {
            setError('Нагадування має бути в майбутньому. Змініть дату або час.')
            return
        }
        busy.current = true; setSaving(true); setError('')
        let savedItem = draft.savedItem
        try {
            const { title, date, time, kind, google_enabled, request_id, google_calendar_id } = draft
            const value = draft.savedItem || await api.post('/tasks', { title, date, time, kind, google_enabled, request_id, google_calendar_id: google_enabled ? Number(google_calendar_id) : null })
            savedItem = value
            if (draft.reminder !== '0') {
                setDraft(previous => previous ? { ...previous, savedItem: value } : previous)
                const at = DateTime.fromISO(`${date}T${time}`, { zone: TZ }).minus({ minutes: Number(draft.reminder) })
                await api.post(`/tasks/${value.id}/reminders`, { channel: 'system', date: at.toISODate(), time: at.toFormat('HH:mm'), revision: value.revision })
            }
            setDraft(null); announceChange(); await load()
        } catch (err) { setError(savedItem ? 'Подію збережено, але нагадування не створено. Спробуйте ще раз.' : typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося зберегти. Спробуйте ще раз.') }
        finally { busy.current = false; if (mounted.current) setSaving(false) }
    }
    const complete = async item => {
        if (busy.current) return
        busy.current = true; setSaving(true)
        try { await api.patch(`/tasks/${item.id}`, { status: 'done', revision: item.revision }); announceChange(); await load() }
        catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося відмітити виконання.'); await load() }
        finally { busy.current = false; if (mounted.current) setSaving(false) }
    }
    const open = async item => {
        try { await desktopCall('open_widget_target', item?.date || selected, item?.id || null) }
        catch { setError('Не вдалося відкрити запис у програмі.') }
    }
    const navigateMonth = offset => {
        const next = DateTime.fromISO(month).plus({ months: offset }).startOf('month')
        setMonth(next.toISODate())
        setSelected(next.set({ day: Math.min(DateTime.fromISO(selected).day, next.daysInMonth) }).toISODate())
    }
    useEffect(() => {
        const move = event => {
            if (!resizeStart.current) return
            const width = Math.max(280, Math.min(1000, Math.round(resizeStart.current.width + event.screenX - resizeStart.current.x)))
            const height = Math.max(300, Math.min(1200, Math.round(resizeStart.current.height + event.screenY - resizeStart.current.y)))
            if (resizeOutput.current) resizeOutput.current.textContent = `${width} × ${height}`
        }
        const finish = event => {
            const start = resizeStart.current
            if (!start) return
            resizeStart.current = null; setResizeHint(null)
            desktopCall('resize_widget', event.screenX - start.x, event.screenY - start.y, start.pixelRatio).catch(() => setError('Не вдалося змінити розмір.'))
        }
        const cancel = () => { resizeStart.current = null; setResizeHint(null) }
        window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish)
        window.addEventListener('pointercancel', cancel); window.addEventListener('blur', cancel)
        return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', cancel); window.removeEventListener('blur', cancel) }
    }, [])
    const calendarDays = useMemo(() => Array.from({ length: 42 }, (_, index) => first.plus({ days: index })), [month])
    const rows = widget?.kind === 'calendar' ? items.filter(item => itemOnDay(item, selected)) : items
    const calendars = (google?.calendars || []).filter(calendar => calendar.writable && calendar.visible)
    if (!widget) return <div className="desktop-widget widget-fallback"><p role="status">{error || 'Завантаження віджета…'}</p></div>
    return <article className={`desktop-widget desktop-widget--${widget.kind}`}>
        <header className="widget-bar">
            <div className={`widget-drag ${widget.locked ? 'is-locked' : ''}`} onPointerDown={event => { if (!widget.locked && event.button === 0) { event.preventDefault(); desktopCall('begin_widget_drag').catch(() => setError('Не вдалося перемістити віджет.')) } }}><IconGripVertical size={15} /><strong>{widgetKinds[widget.kind]}</strong></div>
            <div className="widget-buttons"><button aria-label={widget.locked ? 'Розблокувати позицію' : 'Закріпити позицію'} title={widget.locked ? 'Розблокувати позицію' : 'Закріпити на цьому екрані'} className={widget.locked ? 'is-active' : ''} onClick={() => changeSettings({ locked: !widget.locked })}>{widget.locked ? <IconLock size={16} /> : <IconLockOpen size={16} />}</button>
                <button aria-label="Поверх інших вікон" title="Поверх інших вікон" aria-pressed={widget.on_top} className={widget.on_top ? 'is-active' : ''} onClick={() => changeSettings({ on_top: !widget.on_top })}><IconPin size={16} /></button>
                <button aria-label="Приховати віджет" title="Приховати" onClick={() => desktopCall('hide_widget').catch(() => setError('Не вдалося приховати віджет.'))}><IconX size={16} /></button></div>
        </header>
        <div className="widget-content">
            {error && <div className="widget-error" role="alert">{error}<button title="Повторити оновлення" aria-label="Повторити оновлення" onClick={load}><IconRefresh size={15} /></button></div>}
            {widget.kind === 'calendar' && <>
                <div className="widget-month-nav"><button aria-label="Попередній місяць" onClick={() => navigateMonth(-1)}><IconChevronLeft size={18} /></button><button className="widget-month-title" title="Поточний місяць" onClick={() => { setMonth(now().startOf('month').toISODate()); setSelected(day()) }}>{DateTime.fromISO(month).setLocale('uk').toFormat('LLLL yyyy')}</button><button aria-label="Наступний місяць" onClick={() => navigateMonth(1)}><IconChevronRight size={18} /></button></div>
                <div className="widget-month" role="group" aria-label="Дати календаря">{labels.map(label => <span className="widget-weekday" key={label}>{label}</span>)}
                    {calendarDays.map(date => { const key = date.toISODate(); const count = items.filter(item => itemOnDay(item, key)).length; return <button key={key} aria-label={`${date.setLocale('uk').toFormat('d MMMM yyyy')}${count ? `, подій: ${count}` : ''}`} aria-pressed={selected === key} className={`${date.month !== DateTime.fromISO(month).month ? 'outside-month' : ''} ${key === today ? 'is-today' : ''} ${selected === key ? 'is-selected' : ''}`} onClick={() => createDraft(key)}><span>{date.day}</span>{count > 0 && <i />}</button> })}
                </div>
            </>}
            <div className="widget-day-heading"><div><strong>{widget.kind === 'calendar' ? DateTime.fromISO(selected).setLocale('uk').toFormat('d MMMM, ccc') : widget.kind === 'agenda' ? 'Найближчі 14 днів' : 'За розкладом'}</strong><span>{rows.length}{loading ? ' · оновлення…' : ''}</span></div>{widget.kind !== 'lessons' && <button aria-label="Створити подію або справу" title="Створити" onClick={() => createDraft(selected)}><IconPlus size={19} /></button>}</div>
            <div className="widget-items" aria-busy={loading}>
                {rows.map(item => <div className="widget-item" key={item.occurrence_id || item.id}>{item.kind === 'task' && !item.read_only && <input type="checkbox" aria-label={`Виконано: ${item.title}`} disabled={saving} checked={false} onChange={() => complete(item)} />}<button className="widget-item-body" onClick={() => widget.kind === 'lessons' ? desktopCall('open_widget_lesson', item.id).catch(() => setError('Не вдалося відкрити урок.')) : open(item)}><strong>{item.title}</strong><small>{item.start && !item.all_day ? DateTime.fromISO(item.start).setZone(TZ).toFormat('dd.LL · HH:mm') : item.date ? `${DateTime.fromISO(item.date).toFormat('dd.LL')} · Увесь день` : 'Без дати'}{item.read_only ? ' · лише перегляд' : ''}{item.postponed ? ' · перенесено' : ''}</small>{item.lesson_code && <small>{item.lesson_code} · {item.lesson_title}</small>}</button></div>)}
                {!rows.length && <p className="widget-empty">{loading ? 'Завантаження…' : widget.kind === 'lessons' ? 'Немає активних уроків у розкладі' : 'Поки немає справ'}</p>}
            </div>
        </div>
        <footer className="widget-footer"><button onClick={() => open()}><IconExternalLink size={14} />Відкрити задачник</button><button aria-label="Оновити віджет" title="Оновити" onClick={load}><IconRefresh size={15} /></button></footer>
        {!widget.locked && <button className="widget-resize" aria-label="Змінити розмір віджета" title="Потягніть, щоб змінити розмір" onPointerDown={event => { event.currentTarget.setPointerCapture(event.pointerId); resizeStart.current = { x: event.screenX, y: event.screenY, width: innerWidth, height: innerHeight, pixelRatio: devicePixelRatio }; setResizeHint({ width: innerWidth, height: innerHeight }) }}><IconArrowDownRight size={14} /></button>}
        {resizeHint && <output ref={resizeOutput} className="widget-resize-hint">{resizeHint.width} × {resizeHint.height}</output>}
        {draft && <div className="widget-dialog-overlay"><form className="widget-quick-form" onSubmit={create} aria-label="Створити подію"><header><strong>{draft.savedItem ? 'Додати нагадування' : 'Нова подія'}</strong><button type="button" aria-label="Скасувати створення" disabled={saving} onClick={() => setDraft(null)}><IconX size={17} /></button></header>
            {error && <p className="widget-error" role="alert">{error}</p>}
            <fieldset disabled={saving || !!draft.savedItem}><label>Назва<input autoFocus required maxLength={240} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="Що заплановано?" /></label>
                <div className="widget-form-row"><label>Дата<input required type="date" value={draft.date} onChange={e => setDraft({ ...draft, date: e.target.value })} /></label><label>Час<input required type="time" value={draft.time} onChange={e => setDraft({ ...draft, time: e.target.value })} /></label></div>
                <label>Тип<select value={draft.kind} onChange={e => setDraft({ ...draft, kind: e.target.value })}><option value="event">Подія</option><option value="task">Справа</option></select></label>
                <label><span><IconBell size={14} />Нагадати на комп’ютері</span><select value={draft.reminder} onChange={e => setDraft({ ...draft, reminder: e.target.value })}><option value="0">Без нагадування</option><option value="10">За 10 хвилин</option><option value="30">За 30 хвилин</option><option value="60">За годину</option></select></label>
                {calendars.length > 0 && <><label className="widget-check"><input type="checkbox" checked={draft.google_enabled} onChange={e => setDraft({ ...draft, google_enabled: e.target.checked, google_calendar_id: draft.google_calendar_id || calendars.find(c => c.managed)?.id || calendars[0].id })} />Google Календар</label>{draft.google_enabled && <label>Календар<select value={draft.google_calendar_id} onChange={e => setDraft({ ...draft, google_calendar_id: e.target.value })}>{calendars.map(calendar => <option key={calendar.id} value={calendar.id}>{calendar.name}</option>)}</select></label>}</>}
            </fieldset><button className="widget-save" disabled={saving || !draft.title.trim()} type="submit">{saving ? 'Збереження…' : draft.savedItem ? 'Повторити нагадування' : 'Зберегти'}</button>
        </form></div>}
    </article>
}

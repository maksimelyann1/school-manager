import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import listPlugin from '@fullcalendar/list'
import interactionPlugin from '@fullcalendar/interaction'
import luxonPlugin from '@fullcalendar/luxon3'
import ukLocale from '@fullcalendar/core/locales/uk'
import { DateTime } from 'luxon'
import { api } from '../api/client'
import PlannerEditor, { syncLabels, taskCategories } from '../components/PlannerEditor'
import PlannerGoogle from '../components/PlannerGoogle'
import RefreshButton from '../components/RefreshButton'
import PlannerEventMenu from '../components/PlannerEventMenu'
import PlannerEventPreview from '../components/PlannerEventPreview'
import { AppSelect } from '../components/FormControls'
import './TaskPlanner.css'

const TZ = 'Europe/Kyiv'
const today = () => DateTime.now().setZone(TZ).toISODate()
const categoryColors = { lesson: '#0284c7', substitution: '#b45309', preparation: '#6366f1', event: '#0f766e', other: '#64748b' }
const isLightColor = color => {
    const red = parseInt(color.slice(1, 3), 16)
    const green = parseInt(color.slice(3, 5), 16)
    const blue = parseInt(color.slice(5, 7), 16)
    return (red * 299 + green * 587 + blue * 114) / 1000 >= 150
}
const plugins = [dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin, luxonPlugin]
const timeGridEventContent = info => {
    const { start, end, allDay, title } = info.event
    const time = !allDay && start
        ? `${DateTime.fromJSDate(start).setZone(TZ).toFormat('HH:mm')}${end ? ` - ${DateTime.fromJSDate(end).setZone(TZ).toFormat('HH:mm')}` : ''}`
        : null
    return <div className="planner-calendar-event"><div className="planner-calendar-event-title">{title}</div>{time && <div className="planner-calendar-event-time">{time}</div>}</div>
}

export default function TaskPlanner({ widget = false }) {
    const calendar = useRef(null)
    const calendarShell = useRef(null)
    const [bucket, setBucket] = useState('calendar')
    const [view, setView] = useState('timeGridWeek')
    const [range, setRange] = useState({ start: today(), end: DateTime.now().setZone(TZ).plus({ days: 7 }).toISODate(), title: '' })
    const [selectedDay, setSelectedDay] = useState(today())
    const [items, setItems] = useState([])
    const itemsRef = useRef(items)
    itemsRef.current = items
    const [total, setTotal] = useState(0)
    const [search, setSearch] = useState('')
    const [query, setQuery] = useState('')
    const [category, setCategory] = useState('')
    const [source, setSource] = useState('')
    const [completed, setCompleted] = useState(false)
    const [editor, setEditor] = useState(null)
    const [editorAnchor, setEditorAnchor] = useState(null)
    const [contextMenu, setContextMenu] = useState(null)
    const [preview, setPreview] = useState(null)
    const [contextBusy, setContextBusy] = useState(false)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [refresh, setRefresh] = useState(0)
    const changed = useCallback(() => setRefresh(n => n + 1), [])
    const closeContextMenu = useCallback(() => setContextMenu(null), [])
    const closePreview = useCallback(() => setPreview(null), [])
    useEffect(() => {
        if (bucket !== 'calendar' || widget || !calendarShell.current) return
        let width = 0, frame
        const observer = new ResizeObserver(entries => {
            const nextWidth = entries[0].contentRect.width
            if (nextWidth === width) return
            width = nextWidth
            cancelAnimationFrame(frame)
            frame = requestAnimationFrame(() => calendar.current?.getApi().updateSize())
        })
        observer.observe(calendarShell.current)
        return () => { observer.disconnect(); cancelAnimationFrame(frame) }
    }, [bucket, widget])
    useEffect(() => { const timer = setTimeout(() => setQuery(search), 250); return () => clearTimeout(timer) }, [search])
    useEffect(() => {
        const controller = new AbortController()
        const params = new URLSearchParams({ bucket, start: range.start, end: range.end, q: query, category, source, completed, limit: 500 })
        setLoading(true)
        api.get(`/tasks?${params}`, { signal: controller.signal }).then(data => { setItems(data.items); setTotal(data.total) }).catch(err => {
            if (err.name !== 'AbortError') setError('Не вдалося завантажити задачі. Спробуйте оновити список.')
        }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
        return () => controller.abort()
    }, [bucket, range.start, range.end, query, category, source, completed, refresh])
    useEffect(() => {
        const update = () => { if (!document.hidden) { if (widget) setRange(previous => ({ ...previous, start: today(), end: DateTime.now().setZone(TZ).plus({ days: 7 }).toISODate() })); changed() } }
        const timer = setInterval(update, 60000)
        window.addEventListener('focus', update)
        return () => { clearInterval(timer); window.removeEventListener('focus', update) }
    }, [changed, widget])
    const mutate = async (item, values) => {
        setError('')
        try { await api.patch(`/tasks/${item.id}`, { ...values, revision: item.revision }); changed(); return true }
        catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося зберегти зміни'); changed(); return false }
    }
    const events = useMemo(() => items.filter(item => item.start).map(item => ({ id: item.occurrence_id || item.id, title: `${item.status === 'done' ? '✓ ' : ''}${item.title}`, start: item.start, end: item.end, allDay: item.all_day, backgroundColor: item.color || categoryColors[item.category], editable: !item.read_only && !item.recurrence?.length, classNames: [item.read_only ? 'planner-readonly-event' : '', item.status === 'done' ? 'planner-done' : '', item.color && isLightColor(item.color) ? 'planner-event-light' : ''], extendedProps: { item } })), [items])
    const contextItem = contextMenu ? items.find(item => (item.occurrence_id || item.id) === contextMenu.itemId) : null
    const previewItem = preview ? items.find(item => (item.occurrence_id || item.id) === preview.itemId) : null
    const updateEventColor = async (item, color) => {
        setContextBusy(true)
        setError('')
        try {
            const updated = await api.patch(`/tasks/${item.id}/color`, { revision: item.revision, color })
            setItems(current => current.map(entry => entry.id === item.id ? { ...entry, color: updated.color, revision: updated.revision, ...(entry.series_master ? { series_master: { ...entry.series_master, color: updated.color, revision: updated.revision } } : {}) } : entry))
            closeContextMenu()
            changed()
        } catch (err) {
            setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося змінити колір події')
            closeContextMenu()
            changed()
        } finally { setContextBusy(false) }
    }
    const deleteFromContext = async item => {
        if (item.read_only) return
        if (item.recurrence?.length && !window.confirm('Видалити всю серію повторюваних подій?')) return
        setContextBusy(true)
        setError('')
        try {
            await api.delete(`/tasks/${item.id}?revision=${item.revision}`)
            setItems(current => current.filter(entry => entry.id !== item.id))
            closeContextMenu()
            closePreview()
            changed()
        } catch (err) {
            setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося видалити подію')
            closeContextMenu()
            closePreview()
            changed()
        } finally { setContextBusy(false) }
    }
    const drop = async info => {
        const event = info.event
        const start = DateTime.fromJSDate(event.start).setZone(TZ)
        const end = DateTime.fromJSDate(event.end || event.start).setZone(TZ)
        if (!await mutate(event.extendedProps.item, { date: start.toISODate(), time: event.allDay ? null : start.toFormat('HH:mm'), end_date: (event.allDay ? end.minus({ days: 1 }) : end).toISODate(), end_time: event.allDay ? null : end.toFormat('HH:mm'), timezone: TZ })) info.revert()
    }
    const openEditor = (item, anchor = null) => { setEditorAnchor(anchor); setEditor(item.series_master || item) }
    const anchorFromElement = element => { const box = element.getBoundingClientRect(); return { x: box.left, y: box.bottom } }
    const newItem = (date = selectedDay, time = '', anchor = null, kind = 'task') => openEditor({ date, time, kind }, anchor)
    const rows = bucket === 'calendar' && !widget ? items.filter(item => {
        const start = item.time ? DateTime.fromISO(item.start).setZone(TZ).toISODate() : item.date
        const end = item.time ? DateTime.fromISO(item.end).setZone(TZ).minus({ milliseconds: 1 }).toISODate() : item.end_date
        return start <= selectedDay && end >= selectedDay
    }) : items
    const row = item => <article className={`planner-row ${item.status === 'done' ? 'planner-done' : ''}`} key={item.occurrence_id || item.id}>
        {item.kind === 'task' && !item.read_only && !item.deleted_at ? <input aria-label={`Виконано: ${item.title}`} type="checkbox" checked={item.status === 'done'} onChange={e => mutate(item, { status: e.target.checked ? 'done' : 'open' })} /> : <span className="planner-dot" style={{ background: categoryColors[item.category] }} />}
        <button className="planner-row-body" onClick={event => openEditor(item, anchorFromElement(event.currentTarget))}><strong>{item.title}</strong><small>{item.date ? `${DateTime.fromISO(item.date).toFormat('dd.LL')} · ${item.time || 'Увесь день'}` : 'Без дати'} · {taskCategories[item.category]}</small><small>{item.read_only ? 'Google · лише перегляд' : syncLabels[item.sync_state] || 'Очікує синхронізації'}</small></button>
        {item.kind === 'event' && !item.deleted_at && <button className="planner-prepare" title="Створити задачу підготовки" onClick={event => openEditor({ title: `Підготовка: ${item.title}`, category: 'preparation', parent_id: item.id, date: DateTime.fromISO(item.date).minus({ days: 1 }).toISODate() }, anchorFromElement(event.currentTarget))}>+ Підготовка</button>}
    </article>
    return <div className={`planner ${widget ? 'planner-widget' : ''}`}>
        <header className="page-header"><div><h2>{widget ? 'Мої задачі' : 'Задачник'}</h2><p>{widget ? 'Найближчі 7 днів' : 'Уроки, підготовка та особисті справи'}</p></div><div className="planner-actions"><RefreshButton onClick={changed} busy={loading} />{!widget && <button className="btn btn-secondary" onClick={async () => { if (window.pywebview?.api?.open_task_widget) await window.pywebview.api.open_task_widget(); else window.open('/tasks/widget', 'school-manager-tasks', 'width=380,height=560') }}>Віджет</button>}<button className="btn btn-primary" onClick={event => newItem(selectedDay, '', anchorFromElement(event.currentTarget))}>+ {widget ? 'Задача' : 'Створити'}</button></div></header>
        {widget ? <button className="planner-open-main" onClick={async () => { if (window.pywebview?.api?.open_planner) await window.pywebview.api.open_planner(); else window.open('/tasks', 'school-manager-main') }}>Відкрити повний задачник ↗</button> : <PlannerGoogle onChanged={changed} />}
        <div className="planner-toolbar"><div className="planner-tabs" role="group" aria-label="Розділ задачника">{[['calendar', 'Календар'], ['undated', 'Без дати'], ['overdue', 'Прострочені'], ['trash', 'Кошик']].map(([key, label]) => <button key={key} className={key === bucket ? 'active' : ''} onClick={() => setBucket(key)}>{label}</button>)}</div>{!widget && <><input aria-label="Пошук задач" placeholder="Знайти задачу…" value={search} onChange={e => setSearch(e.target.value)} /><AppSelect menuClassName="planner-filter-menu" className="planner-filter-select" ariaLabel="Категорія задач" value={category} onChange={setCategory} options={[{ value: '', label: 'Усі категорії' }, ...Object.entries(taskCategories).map(([value, label]) => ({ value, label }))]} /><AppSelect menuClassName="planner-filter-menu" className="planner-filter-select" ariaLabel="Джерело задач" value={source} onChange={setSource} options={[{ value: '', label: 'Усі джерела' }, { value: 'local', label: 'Створені тут' }, { value: 'google', label: 'Із Google' }]} /><button type="button" className="planner-completed-toggle" role="switch" aria-checked={completed} onClick={() => setCompleted(value => !value)}><span className="planner-completed-track"><span className="planner-completed-thumb" /></span><span>Виконані</span></button></>}</div>
        {error && <p className="planner-error" role="alert">{error}</p>}
        {total > 500 && <p className="planner-error">Показано перші 500 записів. Уточніть пошук або період.</p>}
        <div className={`planner-layout ${bucket !== 'calendar' || widget ? 'planner-list-layout' : ''}`} aria-busy={loading}>
            {bucket === 'calendar' && !widget && <section ref={calendarShell} className={`planner-calendar ${view === 'dayGridMonth' ? 'planner-calendar--month' : ''}`} aria-label="Календар задач"><div className="planner-calendar-toolbar"><div className="planner-actions"><button className="btn btn-secondary" aria-label="Попередній період" onClick={() => calendar.current.getApi().prev()}>‹</button><button className="btn btn-secondary" onClick={() => { calendar.current.getApi().today(); setSelectedDay(today()) }}>Сьогодні</button><button className="btn btn-secondary" aria-label="Наступний період" onClick={() => calendar.current.getApi().next()}>›</button></div><strong>{range.title}</strong><AppSelect menuClassName="planner-filter-menu" className="planner-filter-select planner-view-select" ariaLabel="Вигляд календаря" value={view} onChange={value => { setView(value); calendar.current.getApi().changeView(value) }} options={[{ value: 'timeGridWeek', label: 'Тиждень' }, { value: 'dayGridMonth', label: 'Місяць' }, { value: 'listMonth', label: 'Список' }]} /></div>
                <FullCalendar ref={calendar} plugins={plugins} locale={ukLocale} timeZone={TZ} initialView={view} views={{ timeGridWeek: { eventContent: timeGridEventContent } }} firstDay={1} headerToolbar={false} height={view === 'dayGridMonth' ? 'auto' : 'clamp(360px, calc(100vh - 280px), 760px)'} nowIndicator eventInteractive eventMinHeight={28} eventShortHeight={36} displayEventEnd={false} eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }} editable eventDurationEditable slotLabelInterval="01:00:00" slotLabelFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }} slotMinTime="06:00:00" slotMaxTime="24:00:00" scrollTime="09:00:00" allDayText="Весь день" dayMaxEvents={view === 'dayGridMonth' ? 3 : false} events={events}
                    datesSet={info => { const start = info.startStr.slice(0, 10), end = info.endStr.slice(0, 10); setRange({ start, end, title: info.view.title }); setSelectedDay(day => day >= start && day < end ? day : start) }}
                    dateClick={info => { const value = DateTime.fromJSDate(info.date).setZone(TZ); setSelectedDay(value.toISODate()); newItem(value.toISODate(), info.allDay ? '' : value.toFormat('HH:mm'), { x: info.jsEvent.clientX, y: info.jsEvent.clientY }, 'event') }}
                    dayCellClassNames={info => DateTime.fromJSDate(info.date).setZone(TZ).toISODate() === selectedDay ? ['planner-selected-day'] : []}
                    dayHeaderClassNames={info => info.view.type === 'timeGridWeek' ? ['planner-clickable-day-header', ...(DateTime.fromJSDate(info.date).setZone(TZ).toISODate() === selectedDay ? ['planner-selected-day-header'] : [])] : []}
                    dayHeaderContent={info => info.view.type === 'timeGridWeek' ? <button type="button" className="planner-day-header-button" aria-pressed={DateTime.fromJSDate(info.date).setZone(TZ).toISODate() === selectedDay} onClick={() => { setSelectedDay(DateTime.fromJSDate(info.date).setZone(TZ).toISODate()); closePreview(); closeContextMenu() }}>{info.text}</button> : info.text}
                    eventDidMount={info => {
                        info.el.title = info.event.title
                        info.el.oncontextmenu = event => {
                            event.preventDefault()
                            event.stopPropagation()
                            const box = info.el.getBoundingClientRect()
                            closePreview()
                            setContextMenu({ itemId: info.event.id, x: event.clientX || box.left, y: event.clientY || box.top })
                        }
                    }}
                    eventWillUnmount={info => { info.el.oncontextmenu = null }}
                    eventClick={info => {
                        const clickedDate = info.jsEvent.target.closest('[data-date]')?.getAttribute('data-date') || DateTime.fromJSDate(info.event.start).setZone(TZ).toISODate()
                        setSelectedDay(clickedDate)
                        if (info.jsEvent.detail > 1) {
                            closePreview()
                            closeContextMenu()
                            const item = itemsRef.current.find(value => (value.occurrence_id || value.id) === info.event.id)
                            if (item) openEditor(item, { x: info.jsEvent.clientX, y: info.jsEvent.clientY })
                            return
                        }
                        const box = info.el.getBoundingClientRect()
                        closeContextMenu()
                        setPreview({ itemId: info.event.id, anchor: { left: box.left, right: box.right, top: box.top } })
                    }} eventDrop={drop} eventResize={drop} eventAllow={(_, event) => !event.extendedProps.item.read_only && !event.extendedProps.item.recurrence?.length} />
            </section>}
            <aside className="planner-day"><header><h3>{bucket === 'calendar' && !widget ? DateTime.fromISO(selectedDay).setLocale('uk').toFormat('cccc, d MMMM') : ({ calendar: 'Найближчі справи', undated: 'Без дати', overdue: 'Потребують уваги', trash: 'Видалені задачі' })[bucket]}</h3><span>{rows.length}</span></header>{rows.map(row)}{!rows.length && <div className="planner-empty"><p>{loading ? 'Завантаження…' : bucket === 'trash' ? 'Кошик порожній' : 'Тут поки немає задач'}</p>{bucket !== 'trash' && <button className="btn btn-secondary" onClick={event => newItem(bucket === 'undated' ? '' : selectedDay, '', anchorFromElement(event.currentTarget))}>+ Додати задачу</button>}</div>}</aside>
        </div>
        {previewItem && <PlannerEventPreview item={previewItem} anchor={preview.anchor} color={previewItem.color || categoryColors[previewItem.category]} busy={contextBusy} onEdit={event => { const anchor = anchorFromElement(event.currentTarget); closePreview(); openEditor(previewItem, anchor) }} onDelete={() => deleteFromContext(previewItem)} onMore={event => { const box = event.currentTarget.getBoundingClientRect(); setContextMenu({ itemId: previewItem.occurrence_id || previewItem.id, x: box.left, y: box.bottom + 6 }); closePreview() }} onClose={closePreview} />}
        {contextItem && <PlannerEventMenu item={contextItem} x={contextMenu.x} y={contextMenu.y} busy={contextBusy} onColor={color => updateEventColor(contextItem, color)} onDelete={() => deleteFromContext(contextItem)} onClose={closeContextMenu} />}
        {editor && <PlannerEditor key={editor.id || 'new'} item={editor} anchor={editorAnchor} onClose={() => setEditor(null)} onChanged={changed} />}
    </div>
}

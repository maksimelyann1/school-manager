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
import './TaskPlanner.css'

const TZ = 'Europe/Kyiv'
const today = () => DateTime.now().setZone(TZ).toISODate()
const categoryColors = { lesson: '#0284c7', substitution: '#b45309', preparation: '#6366f1', event: '#0f766e', other: '#64748b' }
const plugins = [dayGridPlugin, timeGridPlugin, listPlugin, interactionPlugin, luxonPlugin]

export default function TaskPlanner({ widget = false }) {
    const calendar = useRef(null)
    const calendarShell = useRef(null)
    const [bucket, setBucket] = useState('calendar')
    const [view, setView] = useState('timeGridWeek')
    const [range, setRange] = useState({ start: today(), end: DateTime.now().setZone(TZ).plus({ days: 7 }).toISODate(), title: '' })
    const [selectedDay, setSelectedDay] = useState(today())
    const [items, setItems] = useState([])
    const [total, setTotal] = useState(0)
    const [search, setSearch] = useState('')
    const [query, setQuery] = useState('')
    const [category, setCategory] = useState('')
    const [source, setSource] = useState('')
    const [completed, setCompleted] = useState(false)
    const [editor, setEditor] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [refresh, setRefresh] = useState(0)
    const changed = useCallback(() => setRefresh(n => n + 1), [])
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
    const events = useMemo(() => items.filter(item => item.start).map(item => ({ id: item.id, title: `${item.status === 'done' ? '✓ ' : ''}${item.title}`, start: item.start, end: item.end, allDay: item.all_day, backgroundColor: categoryColors[item.category], borderColor: categoryColors[item.category], editable: !item.read_only, classNames: [item.read_only ? 'planner-readonly-event' : '', item.status === 'done' ? 'planner-done' : ''], extendedProps: { item } })), [items])
    const drop = async info => {
        const event = info.event
        const start = DateTime.fromJSDate(event.start).setZone(TZ)
        const end = DateTime.fromJSDate(event.end || event.start).setZone(TZ)
        if (!await mutate(event.extendedProps.item, { date: start.toISODate(), time: event.allDay ? null : start.toFormat('HH:mm'), end_date: (event.allDay ? end.minus({ days: 1 }) : end).toISODate(), end_time: event.allDay ? null : end.toFormat('HH:mm'), timezone: TZ })) info.revert()
    }
    const newItem = (date = selectedDay, time = '') => setEditor({ date, time })
    const rows = bucket === 'calendar' && !widget ? items.filter(item => {
        const start = item.time ? DateTime.fromISO(item.start).setZone(TZ).toISODate() : item.date
        const end = item.time ? DateTime.fromISO(item.end).setZone(TZ).minus({ milliseconds: 1 }).toISODate() : item.end_date
        return start <= selectedDay && end >= selectedDay
    }) : items
    const row = item => <article className={`planner-row ${item.status === 'done' ? 'planner-done' : ''}`} key={item.id}>
        {item.kind === 'task' && !item.read_only && !item.deleted_at ? <input aria-label={`Виконано: ${item.title}`} type="checkbox" checked={item.status === 'done'} onChange={e => mutate(item, { status: e.target.checked ? 'done' : 'open' })} /> : <span className="planner-dot" style={{ background: categoryColors[item.category] }} />}
        <button className="planner-row-body" onClick={() => setEditor(item)}><strong>{item.title}</strong><small>{item.date ? `${DateTime.fromISO(item.date).toFormat('dd.LL')} · ${item.time || 'Увесь день'}` : 'Без дати'} · {taskCategories[item.category]}</small><small>{item.read_only ? 'Google · лише перегляд' : syncLabels[item.sync_state] || 'Очікує синхронізації'}</small></button>
        {item.kind === 'event' && !item.deleted_at && <button className="planner-prepare" title="Створити задачу підготовки" onClick={() => setEditor({ title: `Підготовка: ${item.title}`, category: 'preparation', parent_id: item.id, date: DateTime.fromISO(item.date).minus({ days: 1 }).toISODate() })}>+ Підготовка</button>}
    </article>
    return <div className={`planner ${widget ? 'planner-widget' : ''}`}>
        <header className="page-header"><div><h2>{widget ? 'Мої задачі' : 'Задачник'}</h2><p>{widget ? 'Найближчі 7 днів' : 'Уроки, підготовка та особисті справи'}</p></div><div className="planner-actions"><button className="btn btn-secondary" onClick={changed} disabled={loading} aria-label="Оновити задачі">↻</button>{!widget && <button className="btn btn-secondary" onClick={async () => { if (window.pywebview?.api?.open_task_widget) await window.pywebview.api.open_task_widget(); else window.open('/tasks/widget', 'school-manager-tasks', 'width=380,height=560') }}>Віджет</button>}<button className="btn btn-primary" onClick={() => newItem()}>+ {widget ? 'Задача' : 'Створити'}</button></div></header>
        {widget ? <button className="planner-open-main" onClick={async () => { if (window.pywebview?.api?.open_planner) await window.pywebview.api.open_planner(); else window.open('/tasks', 'school-manager-main') }}>Відкрити повний задачник ↗</button> : <PlannerGoogle onChanged={changed} />}
        <div className="planner-toolbar"><div className="planner-tabs" role="group" aria-label="Розділ задачника">{[['calendar', 'Календар'], ['undated', 'Без дати'], ['overdue', 'Прострочені'], ['trash', 'Кошик']].map(([key, label]) => <button key={key} className={key === bucket ? 'active' : ''} onClick={() => setBucket(key)}>{label}</button>)}</div>{!widget && <><input aria-label="Пошук задач" placeholder="Знайти задачу…" value={search} onChange={e => setSearch(e.target.value)} /><select aria-label="Категорія задач" value={category} onChange={e => setCategory(e.target.value)}><option value="">Усі категорії</option>{Object.entries(taskCategories).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><select aria-label="Джерело задач" value={source} onChange={e => setSource(e.target.value)}><option value="">Усі джерела</option><option value="local">Створені тут</option><option value="google">Із Google</option></select><label className="planner-check"><input type="checkbox" checked={completed} onChange={e => setCompleted(e.target.checked)} />Виконані</label></>}</div>
        {error && <p className="planner-error" role="alert">{error}</p>}
        {total > 500 && <p className="planner-error">Показано перші 500 записів. Уточніть пошук або період.</p>}
        <div className={`planner-layout ${bucket !== 'calendar' || widget ? 'planner-list-layout' : ''}`} aria-busy={loading}>
            {bucket === 'calendar' && !widget && <section ref={calendarShell} className="planner-calendar" aria-label="Календар задач"><div className="planner-calendar-toolbar"><div className="planner-actions"><button className="btn btn-secondary" aria-label="Попередній період" onClick={() => calendar.current.getApi().prev()}>‹</button><button className="btn btn-secondary" onClick={() => { calendar.current.getApi().today(); setSelectedDay(today()) }}>Сьогодні</button><button className="btn btn-secondary" aria-label="Наступний період" onClick={() => calendar.current.getApi().next()}>›</button></div><strong>{range.title}</strong><select aria-label="Вигляд календаря" value={view} onChange={e => { setView(e.target.value); calendar.current.getApi().changeView(e.target.value) }}><option value="timeGridWeek">Тиждень</option><option value="dayGridMonth">Місяць</option><option value="listMonth">Список</option></select></div>
                <FullCalendar ref={calendar} plugins={plugins} locale={ukLocale} timeZone={TZ} initialView={view} firstDay={1} headerToolbar={false} height="clamp(360px, calc(100vh - 280px), 760px)" nowIndicator eventInteractive eventMinHeight={28} eventShortHeight={36} displayEventEnd={false} eventTimeFormat={{ hour: 'numeric', minute: '2-digit', omitZeroMinute: true, hour12: false }} editable eventDurationEditable slotMinTime="06:00:00" slotMaxTime="24:00:00" scrollTime="09:00:00" allDayText="Весь день" dayMaxEvents={3} events={events}
                    datesSet={info => { const start = info.startStr.slice(0, 10), end = info.endStr.slice(0, 10); setRange({ start, end, title: info.view.title }); setSelectedDay(day => day >= start && day < end ? day : start) }}
                    dateClick={info => { const value = DateTime.fromJSDate(info.date).setZone(TZ); setSelectedDay(value.toISODate()); if (!info.allDay) newItem(value.toISODate(), value.toFormat('HH:mm')) }}
                    dayCellClassNames={info => DateTime.fromJSDate(info.date).setZone(TZ).toISODate() === selectedDay ? ['planner-selected-day'] : []}
                    eventDidMount={info => { info.el.title = info.event.title }}
                    eventClick={info => setEditor(info.event.extendedProps.item)} eventDrop={drop} eventResize={drop} eventAllow={(_, event) => !event.extendedProps.item.read_only} />
            </section>}
            <aside className="planner-day"><header><h3>{bucket === 'calendar' && !widget ? DateTime.fromISO(selectedDay).setLocale('uk').toFormat('cccc, d MMMM') : ({ calendar: 'Найближчі справи', undated: 'Без дати', overdue: 'Потребують уваги', trash: 'Видалені задачі' })[bucket]}</h3><span>{rows.length}</span></header>{rows.map(row)}{!rows.length && <div className="planner-empty"><p>{loading ? 'Завантаження…' : bucket === 'trash' ? 'Кошик порожній' : 'Тут поки немає задач'}</p>{bucket !== 'trash' && <button className="btn btn-secondary" onClick={() => newItem(bucket === 'undated' ? '' : selectedDay)}>+ Додати задачу</button>}</div>}</aside>
        </div>
        {editor && <PlannerEditor key={editor.id || 'new'} item={editor} onClose={() => setEditor(null)} onChanged={changed} />}
    </div>
}

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { DateTime } from 'luxon'
import { api, buildApiUrl } from '../api/client'
import { AppSelect } from './FormControls'
import PlannerDescriptionEditor from './PlannerDescriptionEditor'
import PlannerRecurrence from './PlannerRecurrence'

export const taskCategories = { lesson: 'Урок', substitution: 'Заміна', preparation: 'Підготовка', event: 'Захід', other: 'Інше' }
export const syncLabels = { local: 'На цьому комп’ютері', synced: 'Синхронізовано', pending: 'Очікує синхронізації', conflict: 'Є конфлікт змін', error: 'Помилка синхронізації' }
export const reminderLabels = { pending: 'Очікує', scheduled: 'Заплановано', sent: 'Відправлено', cancelled: 'Скасовано', cancel_pending: 'Скасування', error: 'Помилка', uncertain: 'Потрібна перевірка', missed: 'Пропущено', elapsed: 'Час нагадування минув' }

export default function PlannerEditor({ item, anchor, onClose, onChanged }) {
    const dialog = useRef(null)
    const fileInput = useRef(null)
    const drag = useRef(null)
    const movedByUser = useRef(false)
    const positionRef = useRef(null)
    const [expanded, setExpanded] = useState(false)
    const [multipleDays, setMultipleDays] = useState(!!item.end_date && item.end_date !== item.date)
    const [position, setPosition] = useState(null)
    const [current, setCurrent] = useState(item)
    const [form, setForm] = useState({ title: '', description: '', location: '', recurrence: [], attendees: [], meet_requested: false, kind: 'task', category: 'preparation', status: 'open', date: '', time: '', end_date: '', end_time: '', timezone: 'Europe/Kyiv', google_enabled: false, ...item })
    const [guestInput, setGuestInput] = useState('')
    const [google, setGoogle] = useState(null)
    const [requestId] = useState(() => crypto.randomUUID())
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const [groups, setGroups] = useState([])
    const [relations, setRelations] = useState(null)
    const [attachments, setAttachments] = useState(item.attachments || [])
    const [pendingFiles, setPendingFiles] = useState([])
    const [reminder, setReminder] = useState({ channel: 'system', date: item.date || DateTime.now().setZone('Europe/Kyiv').toISODate(), time: '09:00' })
    const readOnly = current.read_only || current.deleted_at
    const selectProps = { disabled: !!readOnly || busy, portalContainerRef: dialog, menuClassName: 'planner-editor-select-menu' }
    useLayoutEffect(() => {
        const el = dialog.current
        el.showModal()
        el.querySelector('input:not([disabled])')?.focus()
        return () => el.close()
    }, [])
    useLayoutEffect(() => {
        const place = () => {
            const box = dialog.current?.getBoundingClientRect()
            if (!box) return
            const margin = 8
            const keepMovedPosition = movedByUser.current && positionRef.current
            let left = keepMovedPosition ? positionRef.current.left : anchor ? anchor.x + 14 : (window.innerWidth - box.width) / 2
            let top = keepMovedPosition ? positionRef.current.top : anchor ? anchor.y + 14 : (window.innerHeight - box.height) / 2
            if (!keepMovedPosition && anchor && left + box.width > window.innerWidth - margin) left = anchor.x - box.width - 14
            if (!keepMovedPosition && anchor && top + box.height > window.innerHeight - margin) top = anchor.y - box.height - 14
            const next = {
                left: Math.max(margin, Math.min(left, window.innerWidth - box.width - margin)),
                top: Math.max(margin, Math.min(top, window.innerHeight - box.height - margin)),
            }
            positionRef.current = next
            setPosition(next)
        }
        place()
        const observer = new ResizeObserver(place)
        observer.observe(dialog.current)
        window.addEventListener('resize', place)
        return () => { observer.disconnect(); window.removeEventListener('resize', place) }
    }, [anchor, expanded])
    useEffect(() => {
        if (!current.id) return
        const controller = new AbortController()
        api.get(`/tasks/${current.id}`, { signal: controller.signal }).then(data => { setRelations(data); setAttachments(data.attachments || []) }).catch(() => {})
        return () => controller.abort()
    }, [current.id, current.revision])
    useEffect(() => {
        const controller = new AbortController()
        api.get('/groups', { signal: controller.signal }).then(data => setGroups(Array.isArray(data) ? data : data.groups || [])).catch(() => {})
        api.get('/planner/google/status', { signal: controller.signal }).then(setGoogle).catch(() => {})
        return () => controller.abort()
    }, [])
    const change = (name, value) => {
        if (name === 'kind' && value === 'task') setGuestInput('')
        setForm(previous => {
        const next = { ...previous, [name]: value }
        if (name === 'date' && previous.date && value && previous.end_date) {
            const shift = DateTime.fromISO(value).diff(DateTime.fromISO(previous.date), 'days').days
            next.end_date = DateTime.fromISO(previous.end_date).plus({ days: shift }).toISODate()
        }
        if (name === 'date' && !value) Object.assign(next, { time: '', end_date: '', end_time: '', google_enabled: false })
        if (name === 'time' && value && previous.date) {
            const before = DateTime.fromISO(`${previous.date}T${previous.time || value}`, { zone: previous.timezone })
            const oldEnd = previous.end_time ? DateTime.fromISO(`${previous.end_date || previous.date}T${previous.end_time}`, { zone: previous.timezone }) : before.plus({ minutes: 30 })
            const end = DateTime.fromISO(`${previous.date}T${value}`, { zone: previous.timezone }).plus(oldEnd.diff(before))
            next.end_date = end.toISODate(); next.end_time = end.toFormat('HH:mm')
        }
        if (name === 'kind' && value === 'event' && previous.status === 'done') next.status = 'open'
        if (name === 'kind' && value === 'task') Object.assign(next, { recurrence: [], attendees: [], meet_requested: false })
        if (name === 'meet_requested' && value) next.google_enabled = true
        return next
        })
    }
    const guestValues = () => [...new Map([...(form.attendees || []), ...guestInput.split(/[,;\s]+/).filter(Boolean).map(email => ({ email: email.toLowerCase() }))].map(guest => [guest.email.toLowerCase(), guest])).values()]
    const addGuests = () => { change('attendees', guestValues()); if (guestInput.trim()) change('google_enabled', true); setGuestInput('') }
    const startDrag = event => {
        if (event.pointerType === 'mouse' && event.button !== 0) return
        if (event.target.closest('button')) return
        const box = dialog.current.getBoundingClientRect()
        drag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, left: box.left, top: box.top }
        movedByUser.current = true
        event.currentTarget.setPointerCapture(event.pointerId)
        event.preventDefault()
    }
    const moveDrag = event => {
        if (drag.current?.pointerId !== event.pointerId) return
        const box = dialog.current.getBoundingClientRect()
        const next = {
            left: Math.max(8, Math.min(drag.current.left + event.clientX - drag.current.x, window.innerWidth - box.width - 8)),
            top: Math.max(8, Math.min(drag.current.top + event.clientY - drag.current.y, window.innerHeight - box.height - 8)),
        }
        positionRef.current = next
        setPosition(next)
    }
    const stopDrag = event => {
        if (drag.current?.pointerId !== event.pointerId) return
        drag.current = null
        if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    }
    const run = async (action, close = false) => {
        setBusy(true); setError('')
        try {
            const result = await action()
            if (result?.id) setCurrent(result)
            onChanged()
            if (close) onClose()
        } catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося зберегти. Перевірте поля та спробуйте ще раз.') }
        finally { setBusy(false) }
    }
    const addFiles = event => {
        const selected = Array.from(event.target.files || [])
        event.target.value = ''
        if (selected.some(file => file.size > 25 * 1024 * 1024)) { setError('Максимальний розмір одного файлу — 25 МБ'); return }
        if (attachments.length + pendingFiles.length + selected.length > 10) { setError('До одного запису можна додати не більше 10 файлів'); return }
        setPendingFiles(previous => [...previous, ...selected])
        setError('')
    }
    const removeAttachment = async file => {
        setBusy(true); setError('')
        try {
            await api.delete(`/tasks/${current.id}/attachments/${file.id}`)
            setAttachments(previous => previous.filter(entry => entry.id !== file.id))
        } catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося видалити файл') }
        finally { setBusy(false) }
    }
    const save = (event) => {
        event.preventDefault()
        const keys = ['title', 'description', 'location', 'recurrence', 'attendees', 'meet_requested', 'kind', 'category', 'status', 'date', 'time', 'end_date', 'end_time', 'timezone', 'fold', 'parent_id', 'group_id', 'google_enabled', 'google_calendar_id']
        const values = Object.fromEntries(keys.filter(key => form[key] !== undefined).map(key => [key, form[key] === '' && !['title', 'description', 'location'].includes(key) ? null : form[key]]))
        if (form.kind === 'event') { values.attendees = guestValues(); if (guestInput.trim()) values.google_enabled = true }
        if (!values.date) Object.assign(values, { time: null, end_date: null, end_time: null })
        if (!values.time) values.end_time = null
        if (values.kind === 'event' && values.status === 'done') values.status = 'open'
        run(async () => {
            const saved = current.id ? await api.patch(`/tasks/${current.id}`, { ...values, revision: current.revision }) : await api.post('/tasks', { ...values, request_id: requestId })
            setCurrent(saved)
            try {
                for (const file of pendingFiles) {
                    const data = new FormData()
                    data.append('file', file)
                    const uploaded = await api.form(`/tasks/${saved.id}/attachments`, data)
                    setAttachments(previous => [...previous, uploaded])
                    setPendingFiles(previous => previous.filter(entry => entry !== file))
                }
            } catch (error) { onChanged(); throw error }
            return saved
        }, true)
    }
    return <dialog ref={dialog} className={`planner-dialog ${expanded ? 'planner-dialog--expanded' : 'planner-dialog--compact'}`} style={position || { visibility: 'hidden' }} onCancel={event => { if (busy) event.preventDefault(); else onClose() }} aria-labelledby="planner-editor-title">
        <form onSubmit={save}>
            <header onPointerDown={startDrag} onPointerMove={moveDrag} onPointerUp={stopDrag} onPointerCancel={stopDrag}><div><span className="planner-dialog__eyebrow">Задачник</span><h2 id="planner-editor-title">{current.deleted_at ? 'У кошику' : current.read_only ? 'Подія Google' : current.id ? 'Редагування' : form.kind === 'event' ? 'Нова подія' : 'Нова задача'}</h2></div><button type="button" className="planner-dialog__close" aria-label="Закрити" disabled={busy} onClick={onClose}>×</button></header>
            <div className="planner-dialog__body">
            {error && <p className="planner-error" role="alert">{error} {error.includes('вже змінилася') && <button type="button" onClick={() => run(async () => { const fresh = await api.get(`/tasks/${current.id}`); setForm({ ...form, ...fresh }); return fresh })}>Завантажити актуальну</button>}</p>}
            {current.sync_error && <p className="planner-error" role="status">{current.sync_error}</p>}
            {relations?.parent && <p className="planner-relation">Підготовка до: <strong>{relations.parent.title}</strong>{relations.parent.deleted_at || relations.parent.status === 'cancelled' ? ' · подію видалено або скасовано' : ''}</p>}
            {!!relations?.preparations?.length && <div className="planner-relation">Пов’язана підготовка:{relations.preparations.map(value => <p key={value.id}>{value.status === 'done' ? '✓ ' : '□ '}{value.title} · {value.date || 'Без дати'}</p>)}</div>}
            <fieldset className="planner-quick-fields" disabled={!!readOnly || busy}>
                <input className="planner-quick-title" aria-label="Назва" autoFocus required maxLength={240} value={form.title} onChange={event => change('title', event.target.value)} placeholder="Додайте назву" />
                <div className="planner-kind-switch" role="group" aria-label="Тип запису">
                    <button type="button" className={form.kind === 'event' ? 'active' : ''} aria-pressed={form.kind === 'event'} onClick={() => change('kind', 'event')}>Подія</button>
                    <button type="button" className={form.kind === 'task' ? 'active' : ''} aria-pressed={form.kind === 'task'} onClick={() => change('kind', 'task')}>Задача</button>
                </div>
                <div className="planner-quick-schedule">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
                    <div className="planner-quick-schedule__fields">
                        <div className={`planner-date-line ${form.time ? 'planner-date-line--timed' : ''}`}><input aria-label="Дата початку" type="date" required={form.kind === 'event'} value={form.date || ''} onChange={event => change('date', event.target.value)} />{form.time ? <><input aria-label="Час початку" type="time" value={form.time} onChange={event => change('time', event.target.value)} /><span aria-hidden="true">–</span><input aria-label="Час завершення" type="time" value={form.end_time || ''} onChange={event => change('end_time', event.target.value)} /></> : <><span aria-hidden="true">–</span><input aria-label="Дата завершення" type="date" min={form.date || undefined} value={form.end_date || form.date || ''} onChange={event => change('end_date', event.target.value)} /></>}</div>
                        {form.time && (multipleDays || (form.end_date && form.end_date !== form.date)) && <label>Дата завершення<input type="date" min={form.date || undefined} value={form.end_date || form.date || ''} onChange={event => change('end_date', event.target.value)} /></label>}
                        {form.time && !multipleDays && (!form.end_date || form.end_date === form.date) && <button className="planner-quick-time-toggle" type="button" onClick={() => setMultipleDays(true)}>Кілька днів</button>}
                        <div className="planner-quick-schedule__options"><label className="planner-check"><input type="checkbox" checked={!form.time} disabled={!form.date} onChange={event => { if (event.target.checked) { change('time', ''); change('end_time', '') } else change('time', '09:00') }} />Увесь день</label><span>{form.timezone}</span></div>
                        {form.kind === 'event' && form.date && <PlannerRecurrence form={form} onChange={value => change('recurrence', value)} selectProps={selectProps} />}
                    </div>
                </div>
                {form.kind === 'event' && <>
                    <div className="planner-quick-detail-row planner-guests"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="9" cy="7" r="3" /><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 4a3 3 0 0 1 0 6M18 14a5 5 0 0 1 3 4v2" /></svg><div className="planner-detail-content">
                        <div className="planner-guest-input"><input aria-label="Гості — email" placeholder="Додайте гостей за email" value={guestInput} onChange={event => setGuestInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addGuests() } }} /><button type="button" aria-label="Додати гостей" disabled={!guestInput.trim()} onClick={addGuests}>+</button></div>
                        {!!form.attendees?.length && <div className="planner-guest-chips">{form.attendees.map(guest => <span key={guest.email} title={({ accepted: 'Прийнято', declined: 'Відхилено', tentative: 'Під питанням', needsAction: 'Очікує відповіді' })[guest.responseStatus] || 'Запрошення після синхронізації'}>{guest.responseStatus === 'accepted' ? '✓ ' : guest.responseStatus === 'declined' ? '× ' : ''}{guest.email}<button type="button" aria-label={`Прибрати гостя ${guest.email}`} onClick={() => change('attendees', form.attendees.filter(value => value.email !== guest.email))}>×</button></span>)}</div>}
                    </div></div>
                    <div className="planner-quick-detail-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="5" width="12" height="14" rx="3" /><path d="m15 9 6-3v12l-6-3" /></svg><div className="planner-detail-content">
                        {!form.meet_requested ? <button type="button" className="planner-detail-action" onClick={() => change('meet_requested', true)}>Додати відеоконференцію Google Meet</button> : <div className="planner-meet"><div>{form.meet_url ? <a href={form.meet_url} target="_blank" rel="noreferrer">Приєднатися в Google Meet ↗</a> : <span>Google Meet</span>}<small>{form.meet_status === 'failure' ? 'Google не створив зустріч. Збережіть подію, щоб повторити.' : form.meet_url || 'Посилання з’явиться після збереження й синхронізації'}</small></div><button type="button" aria-label="Прибрати Google Meet" onClick={() => change('meet_requested', false)}>×</button></div>}
                    </div></div>
                    <div className="planner-quick-detail-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M19 10c0 5-7 11-7 11S5 15 5 10a7 7 0 1 1 14 0Z" /><circle cx="12" cy="10" r="2" /></svg><input className="planner-location" aria-label="Місцезнаходження" placeholder="Додайте місцезнаходження" maxLength={1000} value={form.location || ''} onChange={event => change('location', event.target.value)} /></div>
                </>}
                <div className="planner-quick-detail-row"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 6h16M4 11h16M4 16h11" /></svg><PlannerDescriptionEditor value={form.description} onChange={value => change('description', value)} disabled={!!readOnly || busy} /></div>
            </fieldset>
            <div className="planner-attachments">
                {!!(attachments.length || pendingFiles.length) && <small className="planner-local-files-note">Файли зберігаються на цьому комп’ютері</small>}
                <input ref={fileInput} type="file" multiple hidden onChange={addFiles} />
                {!readOnly && <button type="button" className="planner-attachments__add" disabled={busy} onClick={() => fileInput.current?.click()}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M20 11.5 12 19.5a5 5 0 0 1-7-7l9-9a3.5 3.5 0 0 1 5 5l-9 9a2 2 0 0 1-3-3l8-8" /></svg> Вкласти файл</button>}
                {!!(attachments.length || pendingFiles.length) && <div className="planner-attachments__list">
                    {attachments.map(file => <div className="planner-attachment" key={file.id}><a href={buildApiUrl(`/tasks/${current.id}/attachments/${file.id}`)}>{file.name}</a><small>{(file.size / 1024).toFixed(0)} КБ</small>{!readOnly && <button type="button" aria-label={`Прибрати ${file.name}`} disabled={busy} onClick={() => removeAttachment(file)}>×</button>}</div>)}
                    {pendingFiles.map((file, index) => <div className="planner-attachment" key={`${file.name}-${index}`}><span>{file.name}</span><small>Після збереження</small><button type="button" aria-label={`Прибрати ${file.name}`} disabled={busy} onClick={() => setPendingFiles(previous => previous.filter((_, position) => position !== index))}>×</button></div>)}
                </div>}
            </div>
            <div className="planner-editor-calendar"><label className="planner-check"><input type="checkbox" disabled={!form.date || !!readOnly || busy || current.source === 'google' || !!form.attendees?.length || !!guestInput.trim() || form.meet_requested} checked={!!form.google_enabled || !!guestInput.trim()} onChange={event => change('google_enabled', event.target.checked)} />{form.google_enabled || guestInput.trim() ? 'Google Календар' : 'На цьому комп’ютері'}</label><small>{form.google_enabled || guestInput.trim() ? google?.connection ? google.connection.email : 'Підключіть Google у задачнику' : 'Увімкніть, щоб синхронізувати з Google'}</small>{form.google_enabled && <div className="planner-select-field"><span>Календар</span><AppSelect {...selectProps} disabled={!!readOnly || busy || current.source === 'google' || current.sync_state === 'synced'} ariaLabel="Календар Google" value={form.google_calendar_id || google?.calendars?.find(calendar => calendar.managed)?.id || ''} onChange={value => change('google_calendar_id', value ? Number(value) : null)} options={(google?.calendars || []).filter(calendar => calendar.visible && calendar.writable).map(calendar => ({ value: calendar.id, label: calendar.name }))} /></div>}{(form.attendees?.length > 0 || guestInput.trim()) && <small>Після синхронізації Google надішле гостям запрошення та зміни події.</small>}{current.id && form.recurrence?.length > 0 && <small>Редагування та видалення застосовуються до всієї серії.</small>}</div>
            {expanded && <fieldset className="planner-extra-fields" disabled={!!readOnly || busy}>
                <div className="planner-fields"><div className="planner-select-field"><span>Категорія</span><AppSelect {...selectProps} ariaLabel="Категорія" value={form.category} onChange={value => change('category', value)} options={Object.entries(taskCategories).map(([value, label]) => ({ value, label }))} /></div><div className="planner-select-field"><span>Група</span><AppSelect {...selectProps} ariaLabel="Група" value={form.group_id || ''} onChange={value => change('group_id', value ? Number(value) : null)} options={[{ value: '', label: 'Без групи' }, ...groups.map(group => ({ value: group.id, label: group.name }))]} /></div></div>
                <div className="planner-select-field"><span>Стан</span><AppSelect {...selectProps} ariaLabel="Стан" value={form.status} onChange={value => change('status', value)} options={[{ value: 'open', label: form.kind === 'event' ? 'Заплановано' : 'До виконання' }, ...(form.kind === 'task' ? [{ value: 'done', label: 'Виконано' }] : []), { value: 'cancelled', label: 'Скасовано' }]} /></div>
                <details><summary>Додатково</summary><div className="planner-fields"><label>Часовий пояс<input required value={form.timezone} onChange={e => change('timezone', e.target.value)} /></label><div className="planner-select-field"><span>При переведенні годинника</span><AppSelect {...selectProps} ariaLabel="При переведенні годинника" value={form.fold ?? ''} onChange={value => change('fold', value === '' ? null : Number(value))} options={[{ value: '', label: 'Уточнити, якщо час повторюється' }, { value: 0, label: 'Перше входження' }, { value: 1, label: 'Друге входження' }]} /></div></div></details>
            </fieldset>}
            {expanded && current.id && <section className="planner-reminders"><h3>Нагадування</h3><p>Системні сповіщення працюють, поки застосунок запущений.</p>
                {(current.reminders || []).filter(r => r.state !== 'cancelled').map(r => <div className="planner-reminder" key={r.id}><span>{r.channel === 'system' ? 'На комп’ютері' : 'Telegram · Збережене'} · {DateTime.fromISO(r.remind_at).setZone(form.timezone).toFormat('dd.LL HH:mm')}<small>{reminderLabels[r.state] || r.state}{r.error ? ` · ${r.error}` : ''}</small></span>{!['sent', 'missed'].includes(r.state) && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => run(() => api.delete(`/tasks/${current.id}/reminders/${r.id}`))}>Скасувати</button>}</div>)}
                {!current.deleted_at && current.status === 'open' && <><div className="planner-fields"><div className="planner-select-field"><span>Куди</span><AppSelect disabled={busy} portalContainerRef={dialog} menuClassName="planner-editor-select-menu" ariaLabel="Куди надіслати нагадування" value={reminder.channel} onChange={value => setReminder(previous => ({ ...previous, channel: value }))} options={[{ value: 'system', label: 'На комп’ютері' }, { value: 'telegram', label: 'Telegram · Збережене' }]} /></div><label>Дата<input type="date" value={reminder.date} onChange={e => setReminder({ ...reminder, date: e.target.value })} /></label><label>Час<input type="time" value={reminder.time} onChange={e => setReminder({ ...reminder, time: e.target.value })} /></label></div><button className="btn btn-secondary" type="button" disabled={busy || !reminder.date || !reminder.time} onClick={() => run(() => api.post(`/tasks/${current.id}/reminders`, { ...reminder, fold: form.fold, revision: current.revision }))}>Додати нагадування</button></>}
            </section>}
            </div>
            <footer>
                <button className="planner-dialog__more" type="button" aria-expanded={expanded} disabled={busy} onClick={() => setExpanded(value => !value)}>{expanded ? 'Менше параметрів' : 'Інші параметри'}</button>
                {expanded && current.id && !readOnly && <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => run(() => api.delete(`/tasks/${current.id}?revision=${current.revision}`), true)}>До кошика</button>}
                {expanded && current.deleted_at && !current.read_only && <button className="btn btn-primary" type="button" disabled={busy} onClick={() => run(() => api.post(`/tasks/${current.id}/restore`, { revision: current.revision }), true)}>Відновити</button>}
                {!readOnly && <button className="btn btn-primary" disabled={busy} type="submit">{busy ? 'Збереження…' : 'Зберегти'}</button>}
            </footer>
        </form>
    </dialog>
}

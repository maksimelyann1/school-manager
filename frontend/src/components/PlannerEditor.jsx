import { useEffect, useRef, useState } from 'react'
import { DateTime } from 'luxon'
import { api } from '../api/client'

export const taskCategories = { lesson: 'Урок', substitution: 'Заміна', preparation: 'Підготовка', event: 'Захід', other: 'Інше' }
export const syncLabels = { local: 'На цьому комп’ютері', synced: 'Синхронізовано', pending: 'Очікує синхронізації', conflict: 'Є конфлікт змін', error: 'Помилка синхронізації' }
export const reminderLabels = { pending: 'Очікує', scheduled: 'Заплановано', sent: 'Відправлено', cancelled: 'Скасовано', cancel_pending: 'Скасування', error: 'Помилка', uncertain: 'Потрібна перевірка', missed: 'Пропущено', elapsed: 'Час нагадування минув' }

export default function PlannerEditor({ item, onClose, onChanged }) {
    const dialog = useRef(null)
    const [current, setCurrent] = useState(item)
    const [form, setForm] = useState({ title: '', description: '', kind: 'task', category: 'preparation', status: 'open', date: '', time: '', end_date: '', end_time: '', timezone: 'Europe/Kyiv', google_enabled: false, ...item })
    const [requestId] = useState(() => crypto.randomUUID())
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const [groups, setGroups] = useState([])
    const [relations, setRelations] = useState(null)
    const [reminder, setReminder] = useState({ channel: 'system', date: item.date || DateTime.now().setZone('Europe/Kyiv').toISODate(), time: '09:00' })
    const readOnly = current.read_only || current.deleted_at
    useEffect(() => {
        const el = dialog.current
        el.showModal()
        el.querySelector('input:not([disabled])')?.focus()
        return () => el.close()
    }, [])
    useEffect(() => {
        if (!current.id) return
        const controller = new AbortController()
        api.get(`/tasks/${current.id}`, { signal: controller.signal }).then(setRelations).catch(() => {})
        return () => controller.abort()
    }, [current.id, current.revision])
    useEffect(() => {
        const controller = new AbortController()
        api.get('/groups', { signal: controller.signal }).then(data => setGroups(Array.isArray(data) ? data : data.groups || [])).catch(() => {})
        return () => controller.abort()
    }, [])
    const change = (name, value) => setForm(previous => {
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
        return next
    })
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
    const save = (event) => {
        event.preventDefault()
        const keys = ['title', 'description', 'kind', 'category', 'status', 'date', 'time', 'end_date', 'end_time', 'timezone', 'fold', 'parent_id', 'group_id', 'google_enabled']
        const values = Object.fromEntries(keys.filter(key => form[key] !== undefined).map(key => [key, form[key] === '' && !['title', 'description'].includes(key) ? null : form[key]]))
        if (!values.date) Object.assign(values, { time: null, end_date: null, end_time: null })
        if (!values.time) values.end_time = null
        if (values.kind === 'event' && values.status === 'done') values.status = 'open'
        run(() => current.id ? api.patch(`/tasks/${current.id}`, { ...values, revision: current.revision }) : api.post('/tasks', { ...values, request_id: requestId }), true)
    }
    return <dialog ref={dialog} className="planner-dialog" onCancel={event => { if (busy) event.preventDefault(); else onClose() }} aria-labelledby="planner-editor-title">
        <form onSubmit={save}>
            <header><h2 id="planner-editor-title">{current.deleted_at ? 'У кошику' : current.read_only ? 'Подія Google' : current.id ? 'Редагування' : 'Нова задача або подія'}</h2><button type="button" className="btn btn-secondary" aria-label="Закрити" disabled={busy} onClick={onClose}>×</button></header>
            {error && <p className="planner-error" role="alert">{error} {error.includes('вже змінилася') && <button type="button" onClick={() => run(async () => { const fresh = await api.get(`/tasks/${current.id}`); setForm({ ...form, ...fresh }); return fresh })}>Завантажити актуальну</button>}</p>}
            {relations?.parent && <p className="planner-relation">Підготовка до: <strong>{relations.parent.title}</strong>{relations.parent.deleted_at || relations.parent.status === 'cancelled' ? ' · подію видалено або скасовано' : ''}</p>}
            {!!relations?.preparations?.length && <div className="planner-relation">Пов’язана підготовка:{relations.preparations.map(value => <p key={value.id}>{value.status === 'done' ? '✓ ' : '□ '}{value.title} · {value.date || 'Без дати'}</p>)}</div>}
            <fieldset disabled={!!readOnly || busy}>
                <label>Назва<input autoFocus required maxLength={240} value={form.title} onChange={e => change('title', e.target.value)} placeholder="Підготувати матеріал до уроку" /></label>
                <div className="planner-fields"><label>Тип<select value={form.kind} onChange={e => change('kind', e.target.value)}><option value="task">Задача</option><option value="event">Подія</option></select></label><label>Категорія<select value={form.category} onChange={e => change('category', e.target.value)}>{Object.entries(taskCategories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
                <div className="planner-fields"><label>Дата<input type="date" required={form.kind === 'event'} value={form.date || ''} onChange={e => change('date', e.target.value)} /></label><label><span>Час <small>(необов’язково)</small></span><input type="time" disabled={!form.date || !!readOnly || busy} value={form.time || ''} onChange={e => change('time', e.target.value)} /></label></div>
                {form.date && <div className="planner-fields"><label>Дата завершення<input type="date" min={form.date} value={form.end_date || ''} onChange={e => change('end_date', e.target.value)} /></label>{form.time && <label>Час завершення<input type="time" value={form.end_time || ''} onChange={e => change('end_time', e.target.value)} /></label>}</div>}
                <label>Нотатки<textarea rows={3} maxLength={20000} value={form.description} onChange={e => change('description', e.target.value)} /></label>
                <div className="planner-fields"><label>Група<select value={form.group_id || ''} onChange={e => change('group_id', e.target.value ? Number(e.target.value) : null)}><option value="">Без групи</option>{groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label><label>Стан<select value={form.status} onChange={e => change('status', e.target.value)}><option value="open">{form.kind === 'event' ? 'Заплановано' : 'До виконання'}</option>{form.kind === 'task' && <option value="done">Виконано</option>}<option value="cancelled">Скасовано</option></select></label></div>
                <details><summary>Додатково</summary><div className="planner-fields"><label>Часовий пояс<input required value={form.timezone} onChange={e => change('timezone', e.target.value)} /></label><label>При переведенні годинника<select value={form.fold ?? ''} onChange={e => change('fold', e.target.value === '' ? null : Number(e.target.value))}><option value="">Уточнити, якщо час повторюється</option><option value="0">Перше входження</option><option value="1">Друге входження</option></select></label></div></details>
                <label className="planner-check"><input type="checkbox" disabled={!form.date || !!readOnly || busy} checked={!!form.google_enabled} onChange={e => change('google_enabled', e.target.checked)} />Синхронізувати в календар «School Manager»</label>
            </fieldset>
            {current.id && <section className="planner-reminders"><h3>Нагадування</h3><p>Системні сповіщення працюють, поки застосунок запущений.</p>
                {(current.reminders || []).filter(r => r.state !== 'cancelled').map(r => <div className="planner-reminder" key={r.id}><span>{r.channel === 'system' ? 'На комп’ютері' : 'Telegram · Збережене'} · {DateTime.fromISO(r.remind_at).setZone(form.timezone).toFormat('dd.LL HH:mm')}<small>{reminderLabels[r.state] || r.state}{r.error ? ` · ${r.error}` : ''}</small></span>{!['sent', 'missed'].includes(r.state) && <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => run(() => api.delete(`/tasks/${current.id}/reminders/${r.id}`))}>Скасувати</button>}</div>)}
                {!current.deleted_at && current.status === 'open' && <><div className="planner-fields"><label>Куди<select value={reminder.channel} onChange={e => setReminder({ ...reminder, channel: e.target.value })}><option value="system">На комп’ютері</option><option value="telegram">Telegram · Збережене</option></select></label><label>Дата<input type="date" value={reminder.date} onChange={e => setReminder({ ...reminder, date: e.target.value })} /></label><label>Час<input type="time" value={reminder.time} onChange={e => setReminder({ ...reminder, time: e.target.value })} /></label></div><button className="btn btn-secondary" type="button" disabled={busy || !reminder.date || !reminder.time} onClick={() => run(() => api.post(`/tasks/${current.id}/reminders`, { ...reminder, fold: form.fold, revision: current.revision }))}>Додати нагадування</button></>}
            </section>}
            <footer>
                {!readOnly && <button className="btn btn-primary" disabled={busy} type="submit">{busy ? 'Збереження…' : 'Зберегти'}</button>}
                {current.id && !readOnly && <button className="btn btn-secondary" type="button" disabled={busy} onClick={() => run(() => api.delete(`/tasks/${current.id}?revision=${current.revision}`), true)}>До кошика</button>}
                {current.deleted_at && !current.read_only && <button className="btn btn-primary" type="button" disabled={busy} onClick={() => run(() => api.post(`/tasks/${current.id}/restore`, { revision: current.revision }), true)}>Відновити</button>}
                <button className="btn btn-secondary" disabled={busy} type="button" onClick={onClose}>Закрити</button>
            </footer>
        </form>
    </dialog>
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

export default function PlannerGoogle({ onChanged }) {
    const [status, setStatus] = useState(null)
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const [conflicts, setConflicts] = useState([])
    const mounted = useRef(false)
    const request = useRef(null)
    const load = useCallback(async () => {
        request.current?.abort()
        const controller = new AbortController()
        request.current = controller
        const next = await api.get('/planner/google/status', { signal: controller.signal })
        if (!mounted.current || controller.signal.aborted) return
        setStatus(next)
        if (next.connection) {
            const values = await api.get('/planner/google/conflicts', { signal: controller.signal })
            if (mounted.current && !controller.signal.aborted) setConflicts(values)
        } else setConflicts([])
    }, [])
    useEffect(() => {
        mounted.current = true
        const refresh = () => { if (!document.hidden) load().catch(err => { if (err.name !== 'AbortError' && mounted.current) setError('Не вдалося перевірити Google') }) }
        refresh()
        window.addEventListener('focus', refresh)
        return () => { mounted.current = false; request.current?.abort(); window.removeEventListener('focus', refresh) }
    }, [load])
    useEffect(() => {
        const waiting = status?.oauth_state === 'waiting'
        const timer = setInterval(() => { if (waiting || !document.hidden) load().catch(() => {}) }, waiting ? 2000 : 60000)
        return () => clearInterval(timer)
    }, [status?.oauth_state, load])
    const action = async (path, body = {}, method = 'post') => {
        setBusy(true); setError('')
        try { const result = await api[method](`/planner/google/${path}`, body); if (result.error) setError(result.error); await load(); onChanged() }
        catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося виконати дію Google. Спробуйте ще раз.') }
        finally { setBusy(false) }
    }
    return <details className="planner-google"><summary>Google Календар · {status?.connection?.email || (status?.configured ? 'Не підключено' : 'Потрібне налаштування')}</summary>
        {!status?.configured && <><p>Для першого підключення потрібен OAuth-клієнт типу Desktop у Google Cloud. Інструкція: docs/google-calendar-setup.md.</p><p>Файл конфігурації: <code>{status?.config_path}</code></p><button className="btn btn-secondary" onClick={() => load().catch(() => setError('Не вдалося перевірити конфігурацію'))}>Перевірити налаштування</button></>}
        {(error || status?.oauth_error || status?.connection?.error) && <p className="planner-error" role="alert">{error || status.oauth_error || status.connection.error}</p>}
        <div className="planner-actions">
            {status?.configured && (!status.connection || status.connection.state === 'reauth') && <button disabled={busy || status.oauth_state === 'waiting'} className="btn btn-primary" onClick={() => action('connect')}>{status.oauth_state === 'waiting' ? 'Очікуємо вхід у браузері…' : 'Підключити Google'}</button>}
            {status?.oauth_state === 'waiting' && <button disabled={busy} className="btn btn-secondary" onClick={() => action('cancel')}>Скасувати вхід</button>}
            {status?.connection && <>{status.connection.state !== 'reauth' && <button disabled={busy || status.oauth_state === 'waiting'} className="btn btn-secondary" onClick={() => action('connect')}>Оновити дозволи Google</button>}<button disabled={busy} className="btn btn-secondary" onClick={() => action('calendars')}>Завантажити календарі</button><button disabled={busy} className="btn btn-primary" onClick={() => action('sync')}>{busy ? 'Зачекайте…' : 'Синхронізувати'}</button><button disabled={busy} className="btn btn-secondary" onClick={() => action('disconnect')}>Від’єднати</button></>}
            {status?.connection && !status.calendars.some(c => c.managed) && <button disabled={busy} className="btn btn-primary" onClick={() => action('calendar')}>Створити календар School Manager</button>}
        </div>
        {status?.connection && <p>Синхронізація: кожні 5 хвилин у відкритому задачнику, 15 хвилин у фоні; після ваших змін — на найближчій перевірці. При помилках інтервал збільшується. Редагування доступне у календарях, де ви власник або редактор.</p>}
        {status?.connection && !status.connection.events_write && <p className="planner-error">Щоб редагувати інші календарі, натисніть «Оновити дозволи Google» й підтвердьте доступ у браузері. Потім завантажте календарі.</p>}
        {status?.connection?.last_sync_at && <p>Остання синхронізація: {new Date(status.connection.last_sync_at).toLocaleString('uk-UA')}</p>}
        {status?.calendars.map(calendar => <label className="planner-check" key={calendar.id}><input type="checkbox" checked={calendar.visible} disabled={calendar.managed || busy} onChange={event => action(`calendars/${calendar.id}`, { visible: event.target.checked }, 'patch')} />{calendar.name} · {calendar.writable ? 'створення й редагування' : 'лише перегляд'}</label>)}
        {conflicts.map(conflict => <div className="planner-error" key={conflict.id}><p>Тут: {conflict.local_title} · {conflict.local_start}</p><p>Google: {conflict.google_title} · {conflict.google_start.dateTime || conflict.google_start.date}</p><div className="planner-actions"><button className="btn btn-secondary" disabled={busy} onClick={() => action(`conflicts/${conflict.id}`, { revision: conflict.revision, use_google: false })}>Залишити мою версію</button><button className="btn btn-secondary" disabled={busy} onClick={() => action(`conflicts/${conflict.id}`, { revision: conflict.revision, use_google: true })}>Прийняти Google</button></div></div>)}
    </details>
}

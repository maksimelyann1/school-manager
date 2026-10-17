import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

export default function PlannerGoogle({ onChanged }) {
    const [status, setStatus] = useState(null)
    const [busy, setBusy] = useState('')
    const actionInFlight = useRef(false)
    const [error, setError] = useState('')
    const mounted = useRef(false)
    const request = useRef(null)
    const lastSync = useRef(null)
    const calendars = Array.isArray(status?.calendars) ? status.calendars : []
    const load = useCallback(async (notifyChanges = true) => {
        request.current?.abort()
        const controller = new AbortController()
        request.current = controller
        const next = await api.get('/planner/google/status', { signal: controller.signal })
        if (!mounted.current || controller.signal.aborted) return
        setStatus(next)
        setError('')
        const stamp = next.connection?.last_sync_at || null
        if (notifyChanges && stamp && lastSync.current && lastSync.current !== stamp) onChanged()
        lastSync.current = stamp

    }, [onChanged])
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
        if (actionInFlight.current) return
        actionInFlight.current = true
        setBusy(path); setError('')
        try { const result = await api[method](`/planner/google/${path}`, body); await load(false); if (result.error) setError(result.error); onChanged() }
        catch (err) { setError(typeof err.data?.detail === 'string' ? err.data.detail : 'Не вдалося виконати дію Google. Спробуйте ще раз.') }
        finally { actionInFlight.current = false; setBusy('') }
    }
    return <details className="planner-google"><summary>Google Календар · {status?.connection?.email || (status?.configured ? 'Не підключено' : 'Потрібне налаштування')}</summary>
        {!status?.configured && <><p>Для першого підключення потрібен OAuth-клієнт типу Desktop у Google Cloud. Інструкція: docs/google-calendar-setup.md.</p><p>Файл конфігурації: <code>{status?.config_path}</code></p><button className="btn btn-secondary" onClick={() => load().catch(() => setError('Не вдалося перевірити конфігурацію'))}>Перевірити налаштування</button></>}
        {(error || status?.oauth_error || status?.connection?.error) && <p className="planner-error" role="alert">{error || status.oauth_error || status.connection.error}</p>}
        {status?.oauth_notice && <p role="status">{status.oauth_notice}.{status.connection ? ' Поточне підключення Google збережено.' : ''}</p>}
        {status?.oauth_state === 'waiting' && <p role="status">Завершіть вхід у браузері або натисніть «Скасувати вхід».{status.connection ? ' Поточне підключення Google продовжує працювати.' : ''}</p>}
        <div className="planner-actions">
            {status?.configured && (!status.connection || status.connection.state === 'reauth') && <button disabled={!!busy || status.oauth_state === 'waiting'} className="btn btn-primary" onClick={() => action('connect')}>{status.oauth_state === 'waiting' ? 'Очікуємо вхід у браузері…' : 'Підключити Google'}</button>}
            {status?.oauth_state === 'waiting' && <button disabled={!!busy} className="btn btn-secondary" onClick={() => action('cancel')}>Скасувати вхід</button>}
            {status?.connection && <>{status.connection.state !== 'reauth' && <button disabled={!!busy || status.oauth_state === 'waiting'} className="btn btn-secondary" onClick={() => action('connect')}>Оновити дозволи Google</button>}<button disabled={!!busy} aria-busy={busy === 'sync'} title="Оновити список календарів і синхронізувати події" className="btn btn-primary" onClick={() => action('sync')}>Синхронізувати</button><button disabled={!!busy} className="btn btn-secondary" onClick={() => action('disconnect')}>Від’єднати</button></>}
            {status?.connection && !calendars.some(c => c.managed) && <button disabled={!!busy} className="btn btn-primary" onClick={() => action('calendar')}>Створити календар School Manager</button>}
        </div>
        {status?.connection && <p>Синхронізація: кожні 5 хвилин у відкритому задачнику, 15 хвилин у фоні; після ваших змін — на найближчій перевірці. Новіша версія події автоматично застосовується в обох календарях. При помилках інтервал збільшується. Редагування доступне у календарях, де ви власник або редактор.</p>}
        {status?.connection && !status.connection.events_write && <p className="planner-error">Щоб редагувати інші календарі, натисніть «Оновити дозволи Google» й підтвердьте доступ у браузері. Потім натисніть «Синхронізувати».</p>}
        {status?.connection?.last_sync_at && <p>Остання синхронізація: {new Date(status.connection.last_sync_at).toLocaleString('uk-UA')}</p>}
        {status?.connection?.error && status.connection.state !== 'reauth' && status.connection.next_sync_at && <p role="status">Наступна спроба: {new Date(status.connection.next_sync_at).toLocaleString('uk-UA')}. Можна повторити зараз кнопкою «Синхронізувати».</p>}
        {calendars.map(calendar => <label className="planner-check" key={calendar.id}><input type="checkbox" checked={calendar.visible} disabled={calendar.managed || !!busy} onChange={event => action(`calendars/${calendar.id}`, { visible: event.target.checked }, 'patch')} />{calendar.name} · {calendar.writable ? 'створення й редагування' : 'лише перегляд'}</label>)}
    </details>
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { IconCalendarMonth, IconChecklist, IconSchool, IconLock, IconLockOpen, IconDeviceDesktop, IconEye, IconEyeOff, IconTrash, IconPlus } from '@tabler/icons-react'
import { desktopCall, widgetChannel, widgetKinds } from '../widgets/bridge'
import '../widgets/Widgets.css'

const icons = { calendar: IconCalendarMonth, agenda: IconChecklist, lessons: IconSchool }
const descriptions = { calendar: 'Місяць, події на день і швидке створення.', agenda: 'Найближчі справи та відмітка виконання.', lessons: 'Час уроків з урахуванням перенесень і пауз.' }

export default function Widgets() {
    const [state, setState] = useState({ widgets: [], displays: [] })
    const [available, setAvailable] = useState(!!window.pywebview?.api?.get_widgets)
    const [error, setError] = useState('')
    const [busy, setBusy] = useState(false)
    const saving = useRef(false)
    const mounted = useRef(true)
    const load = useCallback(async () => {
        if (!window.pywebview?.api?.get_widgets) return
        const data = await desktopCall('get_widgets')
        if (mounted.current) { setState(data); setAvailable(true) }
    }, [])
    useEffect(() => {
        mounted.current = true
        const refresh = () => load().catch(() => { if (mounted.current) setError('Не вдалося прочитати віджети. Спробуйте ще раз.') })
        refresh()
        window.addEventListener('pywebviewready', refresh)
        window.addEventListener('focus', refresh)
        const channel = window.BroadcastChannel ? new BroadcastChannel(widgetChannel) : null
        if (channel) channel.onmessage = refresh
        return () => { mounted.current = false; window.removeEventListener('pywebviewready', refresh); window.removeEventListener('focus', refresh); channel?.close() }
    }, [load])
    const run = async (method, ...args) => {
        if (saving.current) return
        saving.current = true; setBusy(true); setError('')
        try { const data = await desktopCall(method, ...args); if (mounted.current) setState(data) }
        catch (err) { if (mounted.current) setError(err.message || 'Не вдалося змінити віджет.') }
        finally { saving.current = false; if (mounted.current) setBusy(false) }
    }
    const update = (id, values) => run('update_widget', id, values)
    return <div className="widgets-page">
        <header className="page-header"><div><h2>Віджети</h2><p>Календар і справи під рукою на робочому столі</p></div></header>
        {(error || state.error) && <p className="widgets-error" role="alert">{error || state.error}</p>}
        {!available && <p className="widgets-note">Відкрийте цю вкладку у настільній програмі, щоб додати віджети на робочий стіл.</p>}
        <section className="widgets-library" aria-label="Додати віджет">
            {Object.entries(widgetKinds).map(([kind, name]) => { const Icon = icons[kind]; return <article className="widget-choice" key={kind}>
                <Icon size={27} stroke={1.7} /><h3>{name}</h3><p>{descriptions[kind]}</p>
                <button className="btn btn-secondary" disabled={!available || busy || state.widgets.length >= 8} onClick={() => run('create_widget', kind)}><IconPlus size={16} />Додати</button>
            </article> })}
        </section>
        <div className="widgets-section-heading"><h3>На робочому столі <span>{state.widgets.length}</span></h3><small>Налаштування та позиції зберігаються автоматично</small></div>
        <section className="widgets-configurations" aria-label="Мої віджети">
            {state.widgets.map(widget => { const Icon = icons[widget.kind]; const screen = state.displays.find(d => d.id === widget.position?.display_id); return <article className="widget-configuration" key={widget.id}>
                <header><div><Icon size={21} stroke={1.7} /><strong>{widgetKinds[widget.kind]}</strong><span className={widget.visible ? 'widget-status-active' : ''}>{widget.visible ? 'Показано' : 'Приховано'}</span></div><div className="widget-config-actions">
                    <button aria-label={widget.visible ? 'Приховати віджет' : 'Показати віджет'} title={widget.visible ? 'Приховати' : 'Показати'} disabled={busy} onClick={() => update(widget.id, { visible: !widget.visible })}>{widget.visible ? <IconEye size={18} /> : <IconEyeOff size={18} />}</button>
                    <button aria-label="Видалити віджет" title="Видалити віджет" disabled={busy} onClick={() => run('remove_widget', widget.id)}><IconTrash size={18} /></button>
                </div></header>
                <div className="widget-config-fields">
                    <label>Розмір<select disabled={busy} value={widget.size} onChange={e => update(widget.id, { size: e.target.value })}><option value="compact">Компактний</option><option value="regular">Звичайний</option><option value="large">Великий</option></select></label>
                    <label><span><IconDeviceDesktop size={15} />Екран</span><select disabled={busy} value={widget.position?.display_id || state.displays[0]?.id || ''} onChange={e => update(widget.id, { display_id: e.target.value })}>
                        {widget.display_missing && <option value={widget.position.display_id}>Від’єднаний екран</option>}
                        {state.displays.map((d, i) => <option key={d.id} value={d.id}>{i + 1} · {d.name}{d.primary ? ' · головний' : ''}</option>)}
                    </select></label>
                    <label className="widget-opacity">Прозорість <output>{100 - widget.opacity}%</output><input type="range" min="0" max="65" step="5" defaultValue={100 - widget.opacity} key={widget.opacity} disabled={busy} aria-label="Прозорість віджета" onPointerUp={e => update(widget.id, { opacity: 100 - Number(e.currentTarget.value) })} onKeyUp={e => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) update(widget.id, { opacity: 100 - Number(e.currentTarget.value) }) }} /></label>
                </div>
                <footer><button className={`widget-lock-toggle ${widget.locked ? 'is-on' : ''}`} aria-pressed={widget.locked} disabled={busy} onClick={() => update(widget.id, { locked: !widget.locked })}>{widget.locked ? <IconLock size={16} /> : <IconLockOpen size={16} />}{widget.locked ? 'Позицію закріплено' : 'Можна переміщувати'}</button>
                    <label className="widget-check"><input type="checkbox" checked={widget.on_top} disabled={busy} onChange={e => update(widget.id, { on_top: e.target.checked })} />Поверх інших вікон</label></footer>
                {widget.display_missing && <p className="widgets-note">Екран тимчасово від’єднаний. Віджет показано на головному; після підключення він повернеться.</p>}
                {widget.locked && screen && <small className="widget-lock-hint">Закріплено на екрані «{screen.name}». Вміст залишається інтерактивним.</small>}
            </article> })}
            {!state.widgets.length && <p className="widgets-empty">Додайте віджет вище, перемістіть його на потрібний екран і натисніть замочок.</p>}
        </section>
        <p className="widgets-note">Віджети працюють, поки програма запущена, зокрема у треї. Приховані віджети звільняють пам’ять. Збережені віджети відкриються при наступному запуску.</p>
    </div>
}

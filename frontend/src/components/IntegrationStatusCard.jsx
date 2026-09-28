import { useStartupStatus } from './StartupStatusContext'
import './IntegrationStatusCard.css'

export default function IntegrationStatusCard({ service, connected, name, onClick }) {
    const { progress, unavailable } = useStartupStatus()
    const step = progress?.steps?.[service]
    const label = service === 'telegram' ? 'Telegram' : 'Logika'
    const busy = !unavailable && (!step || ['pending', 'running'].includes(step.state))
    const failed = unavailable || step?.state === 'error'
    const state = busy ? 'loading' : failed || !connected ? 'error' : 'success'
    const title = unavailable ? 'Стан недоступний'
        : busy ? !step || step.state === 'pending' ? 'Перевірка…'
            : step.message.startsWith('Підключаємо') ? 'Підключення…' : 'Синхронізація…'
        : failed ? 'Не вдалося оновити'
        : connected ? 'Підключено' : 'Відключено'
    const detail = unavailable ? 'Не вдалося перевірити стан. Повторюємо…'
        : busy ? step?.message || 'Перевіряємо стан запуску…'
        : failed ? 'Збережені дані доступні. Деталі в журналі.'
        : step?.state === 'skipped' ? step.message
        : name || (connected ? '' : 'Перевірте підключення в налаштуваннях')

    return (
        <button type="button" className={`card dashboard-action-card integration-status-card integration-status-${state}`}
            data-service={service} data-state={state} onClick={onClick}
            title={[`Статус ${label}: ${title}`, detail, 'Відкрити налаштування'].filter(Boolean).join('\n')}>
            <span className="integration-status-icon" aria-hidden="true">
                {busy ? <span className="integration-status-spinner" /> : (
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        {state === 'error' ? <>
                            <circle cx="12" cy="12" r="10" />
                            <path d="M12 7v6m0 3v1" />
                        </> : service === 'telegram' ? <>
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                            <polyline points="22 4 12 14.01 9 11.01" />
                        </> : <>
                            <path d="M22 10v6M2 10l10-5 10 5-10 5z" />
                            <path d="M6 12v5c3 3 9 3 12 0v-5" />
                        </>}
                    </svg>
                )}
            </span>
            <span className="integration-status-content" role="status" aria-live="polite" aria-atomic="true">
                <span className="integration-status-label">Статус {label}</span>
                <strong className="integration-status-title">{title}</strong>
                {detail && <span className="integration-status-detail">{detail}</span>}
            </span>
        </button>
    )
}

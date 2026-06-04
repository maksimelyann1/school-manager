import { useEffect, useMemo, useState } from 'react'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

const START_STEPS = [
    'Авторизуйтесь через Telegram акаунт, де є робочі групи.',
    'У налаштуваннях синхронізуйте групи Telegram і створіть категорії для швидкого пошуку.',
    'Створіть Google AI API key в AI Studio, вставте його в блоці Google AI, виберіть модель Gemini та натисніть зберегти.',
    'Для вкладки Звіт батькам оновіть базу звітів, заповніть або імпортуйте локальний розклад і привʼяжіть потрібні Telegram-групи.',
    'Створюйте шаблони з текстом і файлами, щоб швидко додавати готові повідомлення.',
    'Надсилайте повідомлення, наліпки, файли або налаштовуйте автоповідомлення й автозвіти.',
    'Користуйтеся Magic для покращення тексту, правою кнопкою миші, Ctrl+V і перетягуванням файлів у редактори.'
]

function versionTuple(version) {
    return String(version || '')
        .split('.')
        .map(part => Number.parseInt(part, 10) || 0)
}

function compareVersions(left, right) {
    const a = versionTuple(left)
    const b = versionTuple(right)
    const length = Math.max(a.length, b.length)
    for (let index = 0; index < length; index += 1) {
        const diff = (a[index] || 0) - (b[index] || 0)
        if (diff !== 0) return diff
    }
    return 0
}

function splitChangelog(text) {
    return String(text || '')
        .split(/\r?\n+/)
        .map(line => line.trim())
        .filter(Boolean)
}

function Info() {
    const [versionInfo, setVersionInfo] = useState(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')

    useEffect(() => {
        const controller = new AbortController()

        const loadVersion = async () => {
            setLoading(true)
            setError('')
            try {
                const response = await fetch(`${API_URL}/system/version`, { signal: controller.signal })
                const data = await response.json()
                if (!response.ok) throw new Error(data.detail || data.error || 'Не вдалося завантажити список змін')
                setVersionInfo(data)
                if (data.check_error) {
                    setError('Не вдалося завантажити список змін')
                }
            } catch (loadError) {
                if (loadError.name === 'AbortError') return
                setError(loadError.message || 'Не вдалося завантажити список змін')
            } finally {
                if (!controller.signal.aborted) setLoading(false)
            }
        }

        loadVersion()
        return () => controller.abort()
    }, [])

    const changelogLines = useMemo(() => splitChangelog(versionInfo?.changelog), [versionInfo])
    const latestVersion = versionInfo?.latest_version || versionInfo?.current_version
    const isNewerOnline = compareVersions(latestVersion, versionInfo?.current_version) > 0
    const changelogTitle = isNewerOnline
        ? `У новій версії v${latestVersion}`
        : `У цій версії v${latestVersion || '...'}`

    return (
        <div className="info-page">
            <div className="page-header">
                <h2>Інфо</h2>
            </div>

            <div className="info-layout">
                <div className="info-left-column">
                    <section className="card info-card">
                        <div className="info-card-header">
                            <span className="info-card-icon">i</span>
                            <div>
                                <h3 className="card-title">Як почати користуватися</h3>
                                <p>Перші кроки після встановлення програми.</p>
                            </div>
                        </div>

                        <ol className="info-steps">
                            {START_STEPS.map((step, index) => (
                                <li key={step}>
                                    <span>{index + 1}</span>
                                    <p>{step}</p>
                                </li>
                            ))}
                        </ol>

                        <div className="info-beta-note">
                            Це Beta-версія, можливі баги.
                        </div>
                    </section>

                    <section className="card info-card info-video-card">
                        <span className="info-support-icon">▶</span>
                        <div>
                            <h3 className="card-title">Відеоінструкція</h3>
                            <p>Скоро тут буде короткий відеогайд.</p>
                        </div>
                    </section>
                </div>

                <div className="info-right-column">
                    <section className="card info-card">
                        <div className="info-card-header">
                            <span className="info-card-icon info-card-icon-version">v</span>
                            <div>
                                <h3 className="card-title">Версія програми</h3>
                            </div>
                        </div>

                        <div className="info-version-grid">
                            <div>
                                <span>Встановлена</span>
                                <strong>v{versionInfo?.current_version || '...'}</strong>
                            </div>
                            <div>
                                <span>Онлайн</span>
                                <strong>v{latestVersion || '...'}</strong>
                            </div>
                        </div>

                        <div className={`info-version-status ${versionInfo?.update_available ? 'update' : 'ok'}`}>
                            {loading
                                ? 'Перевіряємо версію...'
                                : versionInfo?.update_available
                                    ? `Доступна нова версія v${versionInfo.latest_version}`
                                    : 'Встановлена версія актуальна'}
                        </div>

                        <div className="info-changelog">
                            <h4>{changelogTitle}</h4>
                            {error && changelogLines.length === 0 ? (
                                <p className="info-muted">{error}</p>
                            ) : changelogLines.length > 0 ? (
                                <ul>
                                    {changelogLines.map((line, index) => (
                                        <li key={`${line}-${index}`}>{line}</li>
                                    ))}
                                </ul>
                            ) : (
                                <p className="info-muted">Список змін поки порожній.</p>
                            )}
                            {error && changelogLines.length > 0 && (
                                <p className="info-muted">{error}</p>
                            )}
                        </div>
                    </section>

                    <section className="card info-card info-feedback-card">
                        <div>
                            <h3 className="card-title">Знайшов помилку?</h3>
                            <p>Збережи log-файл у налаштуваннях і напиши мені.</p>
                        </div>
                        <a
                            className="info-feedback-button"
                            href="https://t.me/Maksimelyann"
                            target="_blank"
                            rel="noreferrer"
                            aria-label="Звʼязатися в Telegram"
                            title="Звʼязатися в Telegram"
                        >
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                                <path d="M21.7 3.35 2.9 10.6c-1.28.5-1.27 1.2-.23 1.52l4.82 1.5 1.85 5.67c.24.67.12.94.82.94.54 0 .78-.25 1.08-.54l2.6-2.53 5.4 3.99c.99.55 1.7.27 1.95-.92l3.53-16.62c.36-1.44-.55-2.1-1.52-1.69ZM8.24 13.27l10.56-6.66c.53-.32 1.02-.15.62.2l-9.04 8.17-.35 3.76-1.79-5.47Z" />
                            </svg>
                        </a>
                    </section>
                </div>
            </div>
        </div>
    )
}

export default Info

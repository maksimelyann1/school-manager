import { useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

function TelegramAuthPanel({
    mode = 'settings',
    showLogoutActions = true,
    onAuthorized,
    onDisconnected,
    onStatusChange,
    onRefreshRequested,
    onAlert
}) {
    const callbacksRef = useRef({ onAuthorized, onDisconnected, onStatusChange, onRefreshRequested, onAlert })
    const [apiId, setApiId] = useState('')
    const [apiHash, setApiHash] = useState('')
    const [phone, setPhone] = useState('')
    const [smsCode, setSmsCode] = useState('')
    const [twoFaPassword, setTwoFaPassword] = useState('')
    const [authStep, setAuthStep] = useState('credentials')
    const [isConnected, setIsConnected] = useState(false)
    const [hasSavedSession, setHasSavedSession] = useState(false)
    const [manuallyDisconnected, setManuallyDisconnected] = useState(false)
    const [userInfo, setUserInfo] = useState(null)
    const [authLoading, setAuthLoading] = useState(false)
    const [showAdvancedAuth, setShowAdvancedAuth] = useState(false)
    const [hasBuiltinCredentials, setHasBuiltinCredentials] = useState(true)
    const [hasCustomApiHash, setHasCustomApiHash] = useState(false)
    const [qrImage, setQrImage] = useState('')
    const [qrExpires, setQrExpires] = useState(null)
    const [panelAlert, setPanelAlert] = useState(null)

    useEffect(() => {
        callbacksRef.current = { onAuthorized, onDisconnected, onStatusChange, onRefreshRequested, onAlert }
    }, [onAuthorized, onDisconnected, onStatusChange, onRefreshRequested, onAlert])

    const pushAlert = (nextAlert) => {
        setPanelAlert(nextAlert)
        callbacksRef.current.onAlert?.(nextAlert)
    }

    const requestError = (data, fallback) => {
        const detail = data?.detail
        const message = typeof detail === 'object' && detail
            ? detail.message
            : detail || data?.error || fallback
        const code = (typeof detail === 'object' && detail?.code) || data?.code || null
        const error = new Error(message || fallback)
        error.code = code
        return error
    }

    const handleAuthError = (error, fallback) => {
        if (error?.code === 'API_ID_INVALID') {
            setApiId('')
            setApiHash('')
            setHasCustomApiHash(false)
        }
        pushAlert({ type: 'error', text: error.message || fallback })
    }

    const notifyStatus = (nextIsConnected, nextUserInfo, raw = null) => {
        callbacksRef.current.onStatusChange?.({
            isConnected: nextIsConnected,
            userInfo: nextUserInfo,
            raw
        })
        window.dispatchEvent(new CustomEvent('telegram-auth-status', {
            detail: {
                isConnected: nextIsConnected,
                userInfo: nextUserInfo,
                raw
            }
        }))
    }

    const loadSettings = async () => {
        try {
            const res = await fetch(`${API_URL}/settings/bot`)
            if (!res.ok) return
            const data = await res.json()
            const connected = !!data.is_connected
            const hasSession = !!data.has_session
            const manual = !!data.manually_disconnected
            const info = data.user_info || null

            setApiId(data.api_id || '')
            setApiHash('')
            setPhone(data.phone || '')
            setIsConnected(connected)
            setHasSavedSession(hasSession)
            setManuallyDisconnected(manual)
            setUserInfo(info)
            setAuthStep(connected ? 'done' : manual && hasSession ? 'manual-disconnected' : hasSession ? 'restoring' : 'credentials')
            setHasBuiltinCredentials(data.has_builtin_credentials !== false)
            setHasCustomApiHash(!!data.api_hash_set)
            setShowAdvancedAuth(data.has_builtin_credentials === false)
            notifyStatus(connected, info, data)
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Не вдалося перевірити Telegram авторизацію' })
        }
    }

    useEffect(() => {
        loadSettings()
    }, [])

    useEffect(() => {
        if (authStep !== 'restoring') return undefined
        const timer = setInterval(loadSettings, 4000)
        return () => clearInterval(timer)
    }, [authStep])

    useEffect(() => {
        if (!panelAlert) return undefined
        const timer = setTimeout(() => setPanelAlert(null), 5000)
        return () => clearTimeout(timer)
    }, [panelAlert])

    const refreshAfterAutoGroupSync = () => {
        const refresh = callbacksRef.current.onRefreshRequested || callbacksRef.current.onAuthorized
        setTimeout(() => refresh?.(), 2000)
        setTimeout(() => refresh?.(), 6000)
        setTimeout(() => refresh?.(), 12000)
    }

    const markAuthorized = (nextUserInfo) => {
        setIsConnected(true)
        setHasSavedSession(true)
        setManuallyDisconnected(false)
        setUserInfo(nextUserInfo || null)
        setAuthStep('done')
        setQrImage('')
        notifyStatus(true, nextUserInfo || null)
        callbacksRef.current.onAuthorized?.(nextUserInfo || null)
        refreshAfterAutoGroupSync()
    }

    const resetTelegramAuthUi = (raw = null) => {
        setIsConnected(false)
        const hasSession = !!raw?.has_session
        const manual = !!raw?.manually_disconnected
        setHasSavedSession(hasSession)
        setManuallyDisconnected(manual)
        setUserInfo(null)
        setAuthStep(manual && hasSession ? 'manual-disconnected' : hasSession ? 'restoring' : 'credentials')
        setSmsCode('')
        setTwoFaPassword('')
        setQrImage('')
        setQrExpires(null)
        notifyStatus(false, null, raw)
    }

    const buildCredentialPayload = () => {
        const payload = {}
        if (!showAdvancedAuth) return payload

        const customApiId = apiId.trim()
        const customApiHash = apiHash.trim()

        if (hasCustomApiHash && customApiId && !customApiHash) {
            return payload
        }

        if (customApiId || customApiHash) {
            if (!customApiId || !customApiHash) {
                throw new Error('API ID та API Hash потрібно вводити разом')
            }
            payload.api_id = customApiId
            payload.api_hash = customApiHash
        }

        return payload
    }

    const resetApiCredentials = async () => {
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/credentials/reset`, { method: 'POST' })
            const data = await res.json()
            if (!res.ok) throw requestError(data, 'Не вдалося скинути API-дані')
            setApiId('')
            setApiHash('')
            setHasCustomApiHash(false)
            setHasBuiltinCredentials(data.has_builtin_credentials !== false)
            setShowAdvancedAuth(false)
            pushAlert({ type: 'success', text: data.message || 'Власні API-дані скинуто. Використовується вбудований ключ додатку.' })
            loadSettings()
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Не вдалося скинути API-дані' })
        } finally {
            setAuthLoading(false)
        }
    }

    const sendCode = async () => {
        if (!phone.trim()) {
            pushAlert({ type: 'error', text: 'Введіть номер телефону!' })
            return
        }
        setAuthLoading(true)
        try {
            const payload = { phone: phone.trim(), ...buildCredentialPayload() }
            const res = await fetch(`${API_URL}/settings/auth/send-code`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            const data = await res.json()
            if (!res.ok) throw requestError(data, 'Помилка відправки коду')
            setAuthStep('code')
            if (payload.api_hash) setHasCustomApiHash(true)
            pushAlert({ type: 'success', text: 'Код відправлено в Telegram!' })
        } catch (error) {
            handleAuthError(error, 'Помилка відправки коду')
        } finally {
            setAuthLoading(false)
        }
    }

    const startQrLogin = async () => {
        setAuthLoading(true)
        try {
            const payload = buildCredentialPayload()
            if (phone.trim()) payload.phone = phone.trim()
            const res = await fetch(`${API_URL}/settings/auth/qr`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            const data = await res.json()
            if (res.ok && data.authorized) {
                markAuthorized(data.user)
                pushAlert({ type: 'success', text: 'Авторизація успішна! Групи синхронізуються автоматично.' })
            } else if (res.ok && data.qr_image) {
                setQrImage(data.qr_image)
                setQrExpires(data.expires || null)
                setAuthStep('qr')
                if (payload.api_hash) setHasCustomApiHash(true)
                pushAlert({ type: 'info', text: 'Відскануйте QR-код через розділ Telegram "Пристрої".' })
            } else {
                throw requestError(data, 'Не вдалося створити QR-код')
            }
        } catch (error) {
            handleAuthError(error, 'Помилка QR-авторизації')
        } finally {
            setAuthLoading(false)
        }
    }

    const checkQrLogin = async () => {
        try {
            const res = await fetch(`${API_URL}/settings/auth/qr/check`, { method: 'POST' })
            const data = await res.json()
            if (res.ok && data.authorized) {
                markAuthorized(data.user)
                pushAlert({ type: 'success', text: 'Авторизація через QR успішна! Групи синхронізуються автоматично.' })
            } else if (res.ok && data.needs_2fa) {
                setAuthStep('2fa')
                pushAlert({ type: 'info', text: 'Потрібен пароль двофакторної автентифікації' })
            } else if (res.ok && data.qr_image) {
                setQrImage(data.qr_image)
                setQrExpires(data.expires || null)
            } else if (!res.ok) {
                throw requestError(data, 'Помилка перевірки QR-коду')
            }
        } catch (error) {
            console.error('QR check error:', error)
        }
    }

    useEffect(() => {
        if (authStep !== 'qr') return undefined
        const timer = setInterval(checkQrLogin, 3000)
        return () => clearInterval(timer)
    }, [authStep])

    const verifyCode = async () => {
        if (!smsCode.trim()) {
            pushAlert({ type: 'error', text: 'Введіть код!' })
            return
        }
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/verify-code`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, code: smsCode })
            })
            const data = await res.json()
            if (res.ok && data.ok) {
                markAuthorized(data.user)
                pushAlert({ type: 'success', text: 'Авторизація успішна! Групи синхронізуються автоматично.' })
            } else if (data.needs_2fa) {
                setAuthStep('2fa')
                pushAlert({ type: 'info', text: 'Потрібен пароль двофакторної автентифікації' })
            } else {
                throw requestError(data, 'Невірний код')
            }
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Помилка верифікації' })
        } finally {
            setAuthLoading(false)
        }
    }

    const verify2FA = async () => {
        if (!twoFaPassword.trim()) {
            pushAlert({ type: 'error', text: 'Введіть пароль!' })
            return
        }
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/verify-2fa`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: twoFaPassword })
            })
            const data = await res.json()
            if (!res.ok || !data.ok) throw requestError(data, 'Невірний пароль')
            markAuthorized(data.user)
            pushAlert({ type: 'success', text: 'Авторизація успішна! Групи синхронізуються автоматично.' })
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Помилка 2FA' })
        } finally {
            setAuthLoading(false)
        }
    }

    const logout = async () => {
        if (!confirm('Від’єднати Telegram до перезапуску програми? Після нового запуску акаунт підключиться автоматично.')) return
        try {
            const res = await fetch(`${API_URL}/settings/auth/logout`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) throw new Error(data.detail || data.error || 'Не вдалося від’єднати Telegram')
            resetTelegramAuthUi({ has_session: true, manually_disconnected: true })
            callbacksRef.current.onDisconnected?.()
            pushAlert({ type: 'success', text: data.message || 'Telegram від’єднано до перезапуску програми' })
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Помилка виходу' })
        }
    }

    const logoutFull = async () => {
        if (!confirm('Вийти повністю з Telegram у цій програмі? Буде видалено лише дані авторизації Telegram. Бази, групи, шаблони й файли залишаться.')) return
        try {
            const res = await fetch(`${API_URL}/settings/auth/logout-full`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) throw new Error(data.detail || data.error || 'Не вдалося повністю вийти з Telegram')
            resetTelegramAuthUi({ has_session: false })
            callbacksRef.current.onDisconnected?.()
            pushAlert({ type: 'success', text: data.message || 'Telegram акаунт повністю від’єднано. Для входу потрібно авторизуватися заново.' })
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Помилка повного виходу' })
        }
    }

    const reconnect = async () => {
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/reconnect`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok || !data.ok) {
                const detail = typeof data.detail === 'object' ? data.detail.message : data.detail
                throw new Error(detail || data.message || data.error || 'Не вдалося підключити Telegram')
            }
            setManuallyDisconnected(false)
            markAuthorized(data.user_info || data.user || null)
            pushAlert({ type: 'success', text: data.message || 'Telegram підключено' })
        } catch (error) {
            pushAlert({ type: 'error', text: error.message || 'Не вдалося підключити Telegram' })
            loadSettings()
        } finally {
            setAuthLoading(false)
        }
    }

    return (
        <div className={`telegram-auth-panel telegram-auth-panel-${mode}`}>
            {panelAlert && !callbacksRef.current.onAlert && (
                <div className={`alert alert-${panelAlert.type} telegram-auth-alert`}>
                    {panelAlert.text}
                </div>
            )}

            {authStep === 'done' && isConnected ? (
                <div>
                    <div className="telegram-auth-status">
                        <span className="telegram-auth-status-icon">✓</span>
                        <div>
                            <div className="telegram-auth-status-name">{userInfo?.name || 'Підключено'}</div>
                            <div className="telegram-auth-status-meta">
                                {userInfo?.username ? `@${userInfo.username}` : ''} {userInfo?.phone ? `• +${userInfo.phone}` : ''}
                            </div>
                        </div>
                    </div>
                    {showLogoutActions && (
                        <>
                            <div className="telegram-auth-actions">
                                <button className="btn btn-secondary btn-sm" onClick={logout}>Від’єднатися</button>
                                <button className="btn btn-danger btn-sm" onClick={logoutFull}>Вийти повністю</button>
                            </div>
                            <p className="telegram-auth-note">
                                “Від’єднатися” залишає збережену сесію і після перезапуску програма підключиться знову. “Вийти повністю” видаляє тільки Telegram-авторизацію, без видалення бази, груп, шаблонів і файлів.
                            </p>
                        </>
                    )}
                </div>
            ) : (
                <div>
                    {authStep === 'restoring' && hasSavedSession && (
                        <div>
                            <div className="telegram-auth-status telegram-auth-status-restoring">
                                <span className="telegram-auth-status-icon">↻</span>
                                <div>
                                    <div className="telegram-auth-status-name">Відновлюємо підключення Telegram</div>
                                    <div className="telegram-auth-status-meta">
                                        Збережена сесія є. Програма перепідключається у фоні, повторний вхід не потрібен.
                                    </div>
                                </div>
                            </div>
                            <div className="telegram-auth-actions">
                                <button className="btn btn-secondary btn-sm" onClick={loadSettings} disabled={authLoading}>
                                    Перевірити ще раз
                                </button>
                                {showLogoutActions && (
                                    <button className="btn btn-danger btn-sm" onClick={logoutFull}>
                                        Вийти повністю
                                    </button>
                                )}
                            </div>
                        </div>
                    )}

                    {authStep === 'manual-disconnected' && hasSavedSession && (
                        <div>
                            <div className="telegram-auth-status telegram-auth-status-paused">
                                <span className="telegram-auth-status-icon">⏸</span>
                                <div>
                                    <div className="telegram-auth-status-name">Telegram від’єднано до перезапуску</div>
                                    <div className="telegram-auth-status-meta">
                                        Сесія збережена. Натисніть “Підключитися”, щоб повернути акаунт без нового входу.
                                    </div>
                                </div>
                            </div>
                            <div className="telegram-auth-actions">
                                <button className="btn btn-primary btn-sm" onClick={reconnect} disabled={authLoading}>
                                    {authLoading ? 'Підключення...' : 'Підключитися'}
                                </button>
                                {showLogoutActions && (
                                    <button className="btn btn-danger btn-sm" onClick={logoutFull}>
                                        Вийти повністю
                                    </button>
                                )}
                            </div>
                        </div>
                    )}

                    {authStep === 'credentials' && (
                        <div>
                            <div className="form-group">
                                <label className="form-label">Номер телефону</label>
                                <input
                                    type="text"
                                    className="form-input"
                                    placeholder="+380991234567"
                                    value={phone}
                                    onChange={e => setPhone(e.target.value)}
                                    onKeyDown={e => e.key === 'Enter' && sendCode()}
                                />
                            </div>

                            <div className="telegram-auth-actions">
                                <button className="btn btn-primary" onClick={sendCode} disabled={authLoading}>
                                    {authLoading ? 'Відправка...' : 'Увійти по номеру'}
                                </button>
                                <button className="btn btn-secondary" onClick={startQrLogin} disabled={authLoading}>
                                    {authLoading ? 'Створення QR...' : 'Увійти через QR'}
                                </button>
                            </div>

                            <div style={{ marginTop: '18px' }}>
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    onClick={() => setShowAdvancedAuth(prev => !prev)}
                                >
                                    {showAdvancedAuth ? 'Сховати розширені налаштування' : 'Розширені налаштування'}
                                </button>
                            </div>

                            {showAdvancedAuth && (
                                <div className="telegram-auth-advanced">
                                    <p>
                                        За замовчуванням використовується вбудований ключ додатку. Тут можна ввести власний API ID та API Hash.
                                        {hasCustomApiHash ? ' Власний API Hash уже збережений; щоб змінити його, введіть новий.' : ''}
                                    </p>
                                    <div className="telegram-auth-advanced-grid">
                                        <div className="form-group">
                                            <label className="form-label">API ID</label>
                                            <input type="text" className="form-input" placeholder="12345678" value={apiId} onChange={e => setApiId(e.target.value)} />
                                        </div>
                                        <div className="form-group">
                                            <label className="form-label">API Hash</label>
                                            <input type="password" className="form-input" placeholder={hasCustomApiHash ? 'Збережено. Введіть новий для заміни' : 'abcdef1234567890...'} value={apiHash} onChange={e => setApiHash(e.target.value)} />
                                        </div>
                                    </div>
                                    {hasCustomApiHash && (
                                        <button
                                            type="button"
                                            className="btn btn-secondary btn-sm"
                                            onClick={resetApiCredentials}
                                            disabled={authLoading}
                                        >
                                            Скинути API до вбудованого
                                        </button>
                                    )}
                                    {!hasBuiltinCredentials && (
                                        <p className="telegram-auth-warning">
                                            Вбудований ключ недоступний, тому власні API ID та API Hash обов’язкові.
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {authStep === 'qr' && (
                        <div className="telegram-auth-qr">
                            <p>
                                Відкрийте Telegram на телефоні: Налаштування → Пристрої → Підключити пристрій.
                            </p>
                            <p className="telegram-auth-warning">
                                Важливо: використовуйте саме розділ "Пристрої". Сканер QR-кодів у профілі Telegram призначений для профільних QR-кодів і може показувати помилку.
                            </p>
                            {qrImage ? (
                                <img src={qrImage} alt="QR-код для входу в Telegram" className="telegram-auth-qr-image" />
                            ) : (
                                <div className="loader"><div className="spinner"></div></div>
                            )}
                            {qrExpires && (
                                <p className="telegram-auth-note">QR-код оновлюється автоматично.</p>
                            )}
                            <div className="telegram-auth-actions telegram-auth-actions-centered">
                                <button className="btn btn-secondary" onClick={() => { setAuthStep('credentials'); setQrImage('') }}>
                                    Назад
                                </button>
                                <button className="btn btn-primary" onClick={checkQrLogin}>
                                    Перевірити
                                </button>
                            </div>
                        </div>
                    )}

                    {authStep === 'code' && (
                        <div>
                            <p className="telegram-auth-note">Введіть код з Telegram (перевірте повідомлення від Telegram):</p>
                            <div className="telegram-auth-inline">
                                <div className="form-group telegram-auth-code-input">
                                    <input type="text" className="form-input" placeholder="12345" value={smsCode} onChange={e => setSmsCode(e.target.value)} onKeyDown={e => e.key === 'Enter' && verifyCode()} autoFocus />
                                </div>
                                <button className="btn btn-primary" onClick={verifyCode} disabled={authLoading}>
                                    {authLoading ? 'Перевірка...' : 'Підтвердити'}
                                </button>
                                <button className="btn btn-secondary" onClick={() => setAuthStep('credentials')}>Назад</button>
                            </div>
                        </div>
                    )}

                    {authStep === '2fa' && (
                        <div>
                            <p className="telegram-auth-note">Введіть пароль двофакторної автентифікації:</p>
                            <div className="telegram-auth-inline">
                                <div className="form-group telegram-auth-password-input">
                                    <input type="password" className="form-input" placeholder="Пароль 2FA" value={twoFaPassword} onChange={e => setTwoFaPassword(e.target.value)} onKeyDown={e => e.key === 'Enter' && verify2FA()} autoFocus />
                                </div>
                                <button className="btn btn-primary" onClick={verify2FA} disabled={authLoading}>
                                    {authLoading ? 'Перевірка...' : 'Підтвердити'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default TelegramAuthPanel

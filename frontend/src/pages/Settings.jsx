import { useState, useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { AppSelect, TimePicker } from '../components/FormControls'
import TelegramAuthPanel from '../components/TelegramAuthPanel'
import { useToast } from '../components/ToastProvider'
import { getSearchVariations } from '../utils/search'
import { API_URL, reportClientError } from '../api/client'

// URL бекенду

// Дні тижня
const DAYS = ['понеділок', 'вівторок', 'середа', 'четвер', "п'ятниця", 'субота', 'неділя']
const DAY_OPTIONS = DAYS.map(day => ({ value: day, label: day }))
const GEMINI_MODEL_OPTIONS = [
    { label: 'Gemini 3.5 Flash', value: 'gemini-3.5-flash' },
    { label: 'Gemini 3 Flash', value: 'gemini-3-flash-preview' },
    { label: 'Gemini 3.1 Flash Lite', value: 'gemini-3.1-flash-lite' },
    { label: 'Gemini 2.5 Flash', value: 'gemini-2.5-flash' },
    { label: 'Gemini 2.5 Flash Lite', value: 'gemini-2.5-flash-lite' }
]
const AI_STUDIO_API_KEY_URL = 'https://aistudio.google.com/apikey'
const AI_STUDIO_RATE_LIMIT_URL = 'https://aistudio.google.com/rate-limit?timeRange=last-28-days'

function EyeIcon({ crossed = false }) {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" />
            <circle cx="12" cy="12" r="3" />
            {crossed && <path d="M4 20L20 4" />}
        </svg>
    )
}

function ExternalLinkIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 3h6v6" />
            <path d="M10 14L21 3" />
            <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5" />
        </svg>
    )
}

function Settings() {
    const location = useLocation()
    const [groups, setGroups] = useState([])
    const [categories, setCategories] = useState([])
    const [loading, setLoading] = useState(false)
    const [isSyncing, setIsSyncing] = useState(false)
    const [isCleaningCache, setIsCleaningCache] = useState(false)
    const [isCleaningStickers, setIsCleaningStickers] = useState(false)
    const [isOpeningCacheFolder, setIsOpeningCacheFolder] = useState(false)
    const [cacheStatus, setCacheStatus] = useState(null)
    const [isAutostartSaving, setIsAutostartSaving] = useState(false)
    const [isNotificationsSaving, setIsNotificationsSaving] = useState(false)
    const [autostart, setAutostart] = useState({
        supported: true,
        enabled: false,
        starts_in_tray: false,
        is_current: false
    })
    const [windowsNotifications, setWindowsNotifications] = useState({
        supported: true,
        enabled: true
    })
    const { showToast } = useToast()
    const setAlert = showToast
    const [showGroupForm, setShowGroupForm] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')
    const [isGroupsExpanded, setIsGroupsExpanded] = useState(false)
    const [focusHighlight, setFocusHighlight] = useState(null)
    const telegramCardRef = useRef(null)
    const groupsCardRef = useRef(null)
    const logikaCardRef = useRef(null)
    
    // Резервне копіювання
    const [isRestoring, setIsRestoring] = useState(false)
    const [isSavingDiagnosticLog, setIsSavingDiagnosticLog] = useState(false)

    // Pyrogram авторизація
    const [apiId, setApiId] = useState('')
    const [apiHash, setApiHash] = useState('')
    const [phone, setPhone] = useState('')
    const [smsCode, setSmsCode] = useState('')
    const [twoFaPassword, setTwoFaPassword] = useState('')
    const [authStep, setAuthStep] = useState('credentials') // credentials | qr | code | 2fa | done
    const [isConnected, setIsConnected] = useState(false)
    const [userInfo, setUserInfo] = useState(null)
    const [authLoading, setAuthLoading] = useState(false)
    const [showAdvancedAuth, setShowAdvancedAuth] = useState(false)
    const [hasBuiltinCredentials, setHasBuiltinCredentials] = useState(true)
    const [hasCustomApiHash, setHasCustomApiHash] = useState(false)
    const [qrImage, setQrImage] = useState('')
    const [qrExpires, setQrExpires] = useState(null)
    const [editingGroupId, setEditingGroupId] = useState(null)
    const [reportSettings, setReportSettings] = useState(null)
    const [googleApiKeyDraft, setGoogleApiKeyDraft] = useState('')
    const [googleApiKeyTouched, setGoogleApiKeyTouched] = useState(false)
    const [googleApiKeyVisible, setGoogleApiKeyVisible] = useState(false)
    const [googleApiKeyRevealLoading, setGoogleApiKeyRevealLoading] = useState(false)
    const [isGoogleAiSaving, setIsGoogleAiSaving] = useState(false)

    // Logika Backoffice
    const [logikaSettings, setLogikaSettings] = useState(null)
    const [logikaLoginDraft, setLogikaLoginDraft] = useState('')
    const [logikaPasswordDraft, setLogikaPasswordDraft] = useState('')
    const [logikaPasswordVisible, setLogikaPasswordVisible] = useState(false)
    const [isLogikaLoggingIn, setIsLogikaLoggingIn] = useState(false)
    const [isLogikaSyncing, setIsLogikaSyncing] = useState(false)
    const [isLogikaDisconnecting, setIsLogikaDisconnecting] = useState(false)

    // Стан для створення категорії
    const [newCategoryName, setNewCategoryName] = useState('')
    const [categoryContextMenu, setCategoryContextMenu] = useState(null)
    const [renamingCategory, setRenamingCategory] = useState(null)
    const [renameCategoryName, setRenameCategoryName] = useState('')

    // Сортування таблиці груп
    const [sortBy, setSortBy] = useState(null) // 'name' | 'category' | 'day' | 'time'
    const [sortDir, setSortDir] = useState('asc') // 'asc' | 'desc'

    // Клік по заголовку — перемикає поле/напрямок
    const handleSort = (field) => {
        if (sortBy === field) {
            setSortDir(d => d === 'asc' ? 'desc' : 'asc')
        } else {
            setSortBy(field)
            setSortDir('asc')
        }
    }

    // Фільтрований список груп
    const filteredGroups = groups.filter(g => {
        if (!searchQuery) return true;
        const searchVars = getSearchVariations(searchQuery);
        const groupName = g.name.toLowerCase();
        return searchVars.some(term => groupName.includes(term));
    });

    // Відсортований список груп
    const sortedGroups = [...filteredGroups].sort((a, b) => {
        let valA, valB
        if (sortBy === 'name') {
            valA = (a.name || '').toLowerCase()
            valB = (b.name || '').toLowerCase()
        } else if (sortBy === 'category') {
            valA = (a.category_name || 'я').toLowerCase() // 'я' щоб "без категорії" йшло в кінець
            valB = (b.category_name || 'я').toLowerCase()
        } else if (sortBy === 'day') {
            valA = DAYS.indexOf(a.lesson_day) === -1 ? 99 : DAYS.indexOf(a.lesson_day)
            valB = DAYS.indexOf(b.lesson_day) === -1 ? 99 : DAYS.indexOf(b.lesson_day)
        } else if (sortBy === 'time') {
            valA = a.lesson_time || '99:99'
            valB = b.lesson_time || '99:99'
        } else {
            return 0 // без сортування — оригінальний порядок
        }
        if (valA < valB) return sortDir === 'asc' ? -1 : 1
        if (valA > valB) return sortDir === 'asc' ? 1 : -1
        return 0
    })
    const reportModelOptions = reportSettings?.google_ai_model_options?.length
        ? reportSettings.google_ai_model_options
        : GEMINI_MODEL_OPTIONS

    const logError = (text, details = '') => {
        console.error(text, details)
        reportClientError('Settings', `${text}: ${details}`)
        setAlert({ type: 'error', text })
    }

    const refreshAfterAutoGroupSync = () => {
        setTimeout(fetchData, 2000)
        setTimeout(fetchData, 6000)
        setTimeout(fetchData, 12000)
    }

    // Дані форми групи
    const [newGroup, setNewGroup] = useState({
        name: '',
        telegram_id: '',
        lesson_time: '19:00',
        lesson_day: 'понеділок',
        category_id: null
    })

    useEffect(() => {
        fetchData()
        loadLogikaSettings()
    }, [])

    const loadLogikaSettings = async () => {
        try {
            const res = await fetch(`${API_URL}/logika/settings`)
            if (res.ok) {
                const data = await res.json()
                setLogikaSettings(data)
                if (data.login) {
                    setLogikaLoginDraft(data.login)
                }
            }
        } catch (err) {
            console.error('Помилка завантаження Logika:', err)
        }
    }

    const handleLogikaLogin = async (e) => {
        if (e) e.preventDefault()
        if (!logikaLoginDraft.trim() || !logikaPasswordDraft.trim()) {
            setAlert({ type: 'warning', text: 'Введіть логін та пароль Logika' })
            return
        }
        setIsLogikaLoggingIn(true)
        try {
            const res = await fetch(`${API_URL}/logika/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    login: logikaLoginDraft.trim(),
                    password: logikaPasswordDraft.trim(),
                }),
            })
            let data = {}
            try {
                data = await res.json()
            } catch (_) {
                const text = await res.text().catch(() => '')
                data = { detail: text || 'Некоректна відповідь сервера' }
            }
            if (!res.ok) {
                throw new Error(data.detail || 'Не вдалося увійти в Logika')
            }
            setAlert({ type: 'success', text: data.message || 'Успішно підключено до Logika' })
            setLogikaPasswordDraft('')
            await loadLogikaSettings()
        } catch (err) {
            setAlert({ type: 'error', text: err.message || 'Помилка авторизації Logika' })
        } finally {
            setIsLogikaLoggingIn(false)
        }
    }

    const handleLogikaSync = async () => {
        setIsLogikaSyncing(true)
        try {
            const res = await fetch(`${API_URL}/logika/sync-schedule`, {
                method: 'POST',
            })
            let data = {}
            try {
                data = await res.json()
            } catch (_) {
                const text = await res.text().catch(() => '')
                data = { detail: text || 'Некоректна відповідь сервера' }
            }
            if (!res.ok) {
                throw new Error(data.detail || 'Помилка синхронізації')
            }
            setAlert({ type: 'success', text: data.message || 'Розклад Logika успішно оновлено' })
            await loadLogikaSettings()
        } catch (err) {
            setAlert({ type: 'error', text: err.message || 'Помилка синхронізації' })
        } finally {
            setIsLogikaSyncing(false)
        }
    }

    const handleLogikaDisconnect = async () => {
        if (!window.confirm('Ви впевнені, що хочете вийти з акаунта Logika?')) return
        setIsLogikaDisconnecting(true)
        try {
            const res = await fetch(`${API_URL}/logika/disconnect`, { method: 'POST' })
            if (res.ok) {
                setAlert({ type: 'info', text: 'Акаунт Logika відключено' })
                setLogikaPasswordDraft('')
                await loadLogikaSettings()
            }
        } catch (err) {
            setAlert({ type: 'error', text: 'Помилка відключення' })
        } finally {
            setIsLogikaDisconnecting(false)
        }
    }

    const handleLogikaToggle = async (field, value) => {
        try {
            const res = await fetch(`${API_URL}/logika/update-settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [field]: value }),
            })
            if (res.ok) {
                setLogikaSettings((prev) => ({ ...prev, [field]: value }))
                setAlert({ type: 'success', text: 'Налаштування збережено' })
            }
        } catch (err) {
            setAlert({ type: 'error', text: 'Не вдалося оновити налаштування' })
        }
    }

    const fetchData = async () => {
        setLoading(true)
        try {
            // Завантажуємо налаштування та статус Pyrogram
            const settingsRes = await fetch(`${API_URL}/settings/bot`)
            if (settingsRes.ok) {
                const s = await settingsRes.json()
                if (s) {
                    setApiId(s.api_id || '')
                    setApiHash('')
                    setPhone(s.phone || '')
                    setIsConnected(s.is_connected || false)
                    setUserInfo(s.user_info || null)
                    setAuthStep(s.is_connected ? 'done' : 'credentials')
                    setHasBuiltinCredentials(s.has_builtin_credentials !== false)
                    setHasCustomApiHash(!!s.api_hash_set)
                    setShowAdvancedAuth(!s.has_builtin_credentials)
                }
            }
            // Завантажуємо групи
            const groupsRes = await fetch(`${API_URL}/groups/`)
            if (groupsRes.ok) setGroups(await groupsRes.json())
            // Завантажуємо категорії
            try {
                const catRes = await fetch(`${API_URL}/categories/`)
                if (catRes.ok) setCategories(await catRes.json())
            } catch (e) { console.error('Категорії недоступні:', e) }
            try {
                const autostartRes = await fetch(`${API_URL}/system/autostart`)
                if (autostartRes.ok) setAutostart(await autostartRes.json())
            } catch (e) { console.error('Автозапуск недоступний:', e) }
            try {
                const notificationsRes = await fetch(`${API_URL}/system/notifications`)
                if (notificationsRes.ok) setWindowsNotifications(await notificationsRes.json())
            } catch (e) { console.error('Системні сповіщення недоступні:', e) }
            try {
                const reportSettingsRes = await fetch(`${API_URL}/parents-report/settings`)
                if (reportSettingsRes.ok) {
                    const data = await reportSettingsRes.json()
                    setReportSettings(data)
                    setGoogleApiKeyDraft(data.google_ai_api_key_masked || '')
                    setGoogleApiKeyTouched(false)
                    setGoogleApiKeyVisible(false)
                }
            } catch (e) { console.error('Google AI налаштування недоступні:', e) }
            fetchCacheStatus()
        } catch (error) {
            logError('Помилка завантаження даних', error)
        }
        setLoading(false)
    }

    const fetchCacheStatus = async () => {
        try {
            const res = await fetch(`${API_URL}/system/cache/status`)
            if (res.ok) {
                setCacheStatus(await res.json())
            }
        } catch (error) {
            console.error('Статус кешу недоступний:', error)
        }
    }

    const buildCredentialPayload = () => {
        const payload = {}
        const customApiId = apiId.trim()
        const customApiHash = apiHash.trim()

        if (customApiId || customApiHash) {
            if (!customApiId || !customApiHash) {
                throw new Error('API ID та API Hash потрібно вводити разом')
            }
            payload.api_id = customApiId
            payload.api_hash = customApiHash
        }

        return payload
    }

    const updateReportSetting = (key, value) => {
        setReportSettings(prev => ({ ...(prev || {}), [key]: value }))
    }

    const toggleGoogleApiKeyVisible = async () => {
        if (googleApiKeyVisible) {
            setGoogleApiKeyVisible(false)
            if (!googleApiKeyTouched && reportSettings?.google_ai_api_key_set) {
                setGoogleApiKeyDraft(reportSettings.google_ai_api_key_masked || '')
            }
            return
        }

        if (reportSettings?.google_ai_api_key_set && !googleApiKeyTouched) {
            setGoogleApiKeyRevealLoading(true)
            try {
                const res = await fetch(`${API_URL}/parents-report/settings/api-key`)
                const data = await res.json().catch(() => ({}))
                if (!res.ok) {
                    throw new Error(data.detail || data.error || 'Не вдалося показати API key')
                }
                setGoogleApiKeyDraft(data.google_ai_api_key || '')
                setGoogleApiKeyVisible(true)
            } catch (error) {
                setAlert({ type: 'error', text: error.message || 'Не вдалося показати API key' })
            } finally {
                setGoogleApiKeyRevealLoading(false)
            }
            return
        }

        setGoogleApiKeyVisible(true)
    }

    const openExternalUrl = async (url) => {
        try {
            const desktopApi = window.pywebview?.api
            if (desktopApi?.open_external_url) {
                const result = await desktopApi.open_external_url(url)
                if (result?.opened) return
                if (result?.error) throw new Error(result.error)
            }
            window.open(url, '_blank', 'noopener,noreferrer')
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Не вдалося відкрити посилання' })
        }
    }

    const saveGoogleAiSettings = async () => {
        setIsGoogleAiSaving(true)
        try {
            const payload = {
                google_ai_model: reportSettings?.google_ai_model || 'gemini-2.5-flash'
            }
            if (googleApiKeyTouched) {
                payload.google_ai_api_key = googleApiKeyDraft
            }

            const res = await fetch(`${API_URL}/parents-report/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) {
                throw new Error(data.detail || data.error || 'Не вдалося зберегти Google AI')
            }

            setReportSettings(data)
            setGoogleApiKeyDraft(data.google_ai_api_key_masked || '')
            setGoogleApiKeyTouched(false)
            setGoogleApiKeyVisible(false)
            setAlert({ type: 'success', text: 'Google AI налаштування збережено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Не вдалося зберегти Google AI' })
        } finally {
            setIsGoogleAiSaving(false)
        }
    }

    // Pyrogram: Крок 1 — відправити код на номер телефону
    const sendCode = async () => {
        if (!phone.trim()) {
            setAlert({ type: 'error', text: 'Введіть номер телефону!' })
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
            if (res.ok) {
                setAuthStep('code')
                setAlert({ type: 'success', text: '📲 Код відправлено в Telegram!' })
                if (payload.api_hash) setHasCustomApiHash(true)
            } else {
                setAlert({ type: 'error', text: data.detail || 'Помилка відправки коду' })
            }
        } catch (e) {
            setAlert({ type: 'error', text: e.message || 'Помилка відправки коду' })
        }
        setAuthLoading(false)
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
                setIsConnected(true)
                setUserInfo(data.user)
                setAuthStep('done')
                setQrImage('')
                setAlert({ type: 'success', text: '✅ Авторизація успішна! Групи синхронізуються автоматично.' })
                refreshAfterAutoGroupSync()
            } else if (res.ok && data.qr_image) {
                setQrImage(data.qr_image)
                setQrExpires(data.expires || null)
                setAuthStep('qr')
                setAlert({ type: 'info', text: 'Відскануйте QR-код у Telegram на телефоні' })
                if (payload.api_hash) setHasCustomApiHash(true)
            } else {
                setAlert({ type: 'error', text: data.detail || data.error || 'Не вдалося створити QR-код' })
            }
        } catch (e) {
            setAlert({ type: 'error', text: e.message || 'Помилка QR-авторизації' })
        } finally {
            setAuthLoading(false)
        }
    }

    const checkQrLogin = async () => {
        try {
            const res = await fetch(`${API_URL}/settings/auth/qr/check`, { method: 'POST' })
            const data = await res.json()
            if (res.ok && data.authorized) {
                setIsConnected(true)
                setUserInfo(data.user)
                setAuthStep('done')
                setQrImage('')
                setAlert({ type: 'success', text: '✅ Авторизація через QR успішна! Групи синхронізуються автоматично.' })
                refreshAfterAutoGroupSync()
            } else if (res.ok && data.needs_2fa) {
                setAuthStep('2fa')
                setAlert({ type: 'info', text: '🔐 Потрібен пароль двофакторної аутентифікації' })
            } else if (res.ok && data.qr_image) {
                setQrImage(data.qr_image)
                setQrExpires(data.expires || null)
            } else if (!res.ok) {
                setAlert({ type: 'error', text: data.detail || data.error || 'Помилка перевірки QR-коду' })
            }
        } catch (e) {
            console.error('QR check error:', e)
        }
    }

    // Pyrogram: Крок 2 — підтвердити код
    const verifyCode = async () => {
        if (!smsCode.trim()) { setAlert({ type: 'error', text: 'Введіть код!' }); return }
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/verify-code`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, code: smsCode })
            })
            const data = await res.json()
            if (res.ok && data.ok) {
                setIsConnected(true)
                setUserInfo(data.user)
                setAuthStep('done')
                setAlert({ type: 'success', text: '✅ Авторизація успішна! Групи синхронізуються автоматично.' })
                refreshAfterAutoGroupSync()
            } else if (data.needs_2fa) {
                setAuthStep('2fa')
                setAlert({ type: 'info', text: '🔐 Потрібен пароль двофакторної аутентифікації' })
            } else {
                setAlert({ type: 'error', text: data.detail || 'Невірний код' })
            }
        } catch (e) { logError('Помилка верифікації', e) }
        setAuthLoading(false)
    }

    // Pyrogram: Крок 3 — 2FA пароль
    const verify2FA = async () => {
        if (!twoFaPassword.trim()) { setAlert({ type: 'error', text: 'Введіть пароль!' }); return }
        setAuthLoading(true)
        try {
            const res = await fetch(`${API_URL}/settings/auth/verify-2fa`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: twoFaPassword })
            })
            const data = await res.json()
            if (res.ok && data.ok) {
                setIsConnected(true)
                setUserInfo(data.user)
                setAuthStep('done')
                setAlert({ type: 'success', text: '✅ Авторизація успішна! Групи синхронізуються автоматично.' })
                refreshAfterAutoGroupSync()
            } else {
                setAlert({ type: 'error', text: data.detail || 'Невірний пароль' })
            }
        } catch (e) { logError('Помилка 2FA', e) }
        setAuthLoading(false)
    }

    const resetTelegramAuthUi = () => {
        setIsConnected(false)
        setUserInfo(null)
        setAuthStep('credentials')
        setSmsCode('')
        setTwoFaPassword('')
        setQrImage('')
    }

    // Тимчасове від'єднання без видалення сесії
    const logout = async () => {
        if (!confirm('Від’єднати Telegram до перезапуску програми? Після нового запуску акаунт підключиться автоматично.')) return
        try {
            const res = await fetch(`${API_URL}/settings/auth/logout`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) {
                throw new Error(data.detail || data.error || 'Не вдалося від’єднати Telegram')
            }
            resetTelegramAuthUi()
            setAlert({ type: 'success', text: data.message || 'Telegram від’єднано до перезапуску програми' })
        } catch (e) { logError('Помилка виходу', e) }
    }

    // Повний вихід з видаленням тільки Telegram-сесії
    const logoutFull = async () => {
        if (!confirm('Вийти повністю з Telegram у цій програмі? Буде видалено лише дані авторизації Telegram. Бази, групи, шаблони й файли залишаться.')) return
        try {
            const res = await fetch(`${API_URL}/settings/auth/logout-full`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok) {
                throw new Error(data.detail || data.error || 'Не вдалося повністю вийти з Telegram')
            }
            resetTelegramAuthUi()
            setAlert({ type: 'success', text: data.message || 'Telegram акаунт повністю від’єднано. Для входу потрібно авторизуватися заново.' })
        } catch (e) { logError('Помилка повного виходу', e) }
    }

    // === Категорії ===
    const createCategory = async () => {
        if (!newCategoryName.trim()) {
            setAlert({ type: 'error', text: 'Введіть назву категорії!' })
            return
        }
        try {
            const response = await fetch(`${API_URL}/categories/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newCategoryName.trim() })
            })
            if (response.ok) {
                setAlert({ type: 'success', text: 'Категорію створено!' })
                setNewCategoryName('')
                fetchData()
            }
        } catch (error) {
            logError('Помилка створення категорії', error)
        }
    }

    const deleteCategory = async (id, name) => {
        if (!confirm(`Видалити категорію "${name}"? Групи залишаться без категорії.`)) return
        try {
            await fetch(`${API_URL}/categories/${id}`, { method: 'DELETE' })
            setAlert({ type: 'success', text: 'Категорію видалено' })
            fetchData()
        } catch (error) {
            logError('Помилка видалення категорії', error)
        }
    }

    const openCategoryContextMenu = (e, category) => {
        e.preventDefault()
        e.stopPropagation()
        setCategoryContextMenu({
            x: Math.max(8, Math.min(e.clientX, window.innerWidth - 230)),
            y: Math.max(8, Math.min(e.clientY, window.innerHeight - 80)),
            category
        })
    }

    const startRenameCategory = (category) => {
        setCategoryContextMenu(null)
        setRenamingCategory(category)
        setRenameCategoryName(category.name)
    }

    const cancelRenameCategory = () => {
        setRenamingCategory(null)
        setRenameCategoryName('')
    }

    const saveRenamedCategory = async () => {
        const name = renameCategoryName.trim()
        if (!renamingCategory) return
        if (!name) {
            setAlert({ type: 'error', text: 'Введіть назву категорії' })
            return
        }

        try {
            const response = await fetch(`${API_URL}/categories/${renamingCategory.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || 'Не вдалося перейменувати категорію')
            }

            const updatedCategory = data.id ? data : { ...renamingCategory, name }
            setCategories(prev => prev.map(cat => cat.id === renamingCategory.id ? updatedCategory : cat))
            setGroups(prev => prev.map(group => (
                group.category_id === renamingCategory.id
                    ? { ...group, category_name: updatedCategory.name }
                    : group
            )))
            setAlert({ type: 'success', text: 'Категорію перейменовано' })
            cancelRenameCategory()
        } catch (error) {
            logError('Помилка перейменування категорії', error)
        }
    }

    // === Групи ===
    const saveGroup = async () => {
        if (!newGroup.name || !newGroup.telegram_id) {
            setAlert({ type: 'error', text: 'Заповніть назву та ID групи!' })
            return
        }

        try {
            const url = editingGroupId
                ? `${API_URL}/groups/${editingGroupId}`
                : `${API_URL}/groups/`
            const method = editingGroupId ? 'PUT' : 'POST'

            // Підготовка даних — category_id = null якщо пусто
            const payload = {
                ...newGroup,
                category_id: newGroup.category_id ? parseInt(newGroup.category_id) : null
            }

            const response = await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })

            if (response.ok) {
                setAlert({ type: 'success', text: editingGroupId ? 'Групу оновлено!' : 'Групу додано!' })
                cancelEditGroup()
                fetchData()
            }
        } catch (error) {
            logError(editingGroupId ? 'Помилка оновлення групи' : 'Помилка додавання групи', error)
        }
    }

    // Синхронізувати групи з Telegram
    const syncGroups = async () => {
        if (!isConnected) {
            setAlert({ type: 'error', text: 'Спочатку авторизуйтесь в Telegram!' })
            return
        }

        setIsSyncing(true)
        try {
            const response = await fetch(`${API_URL}/groups/sync`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })

            const data = await response.json()

            if (response.ok) {
                const added = data.added_count || 0
                const updated = data.updated_count || 0
                if (added > 0 || updated > 0) {
                    const parts = []
                    if (added > 0) parts.push(`нових: ${added}`)
                    if (updated > 0) parts.push(`оновлено назв: ${updated}`)
                    setAlert({ type: 'success', text: `Синхронізація успішна! (${parts.join(', ')})` })
                    fetchData()
                } else {
                    setAlert({ type: 'info', text: 'Усі групи та назви актуальні. Змін не виявлено.' })
                    fetchData()
                }
            } else {
                setAlert({ type: 'error', text: data.detail || 'Помилка синхронізації' })
            }
        } catch (error) {
            logError('Помилка під час синхронізації з Telegram', error)
        } finally {
            setIsSyncing(false)
        }
    }

    const startEditGroup = (group) => {
        setNewGroup({
            name: group.name,
            telegram_id: group.telegram_id,
            lesson_time: group.lesson_time || '19:00',
            lesson_day: group.lesson_day || 'понеділок',
            category_id: group.category_id || ''
        })
        setEditingGroupId(group.id)
        setIsGroupsExpanded(true)
        setShowGroupForm(true)
    }

    const cancelEditGroup = () => {
        setNewGroup({ name: '', telegram_id: '', lesson_time: '19:00', lesson_day: 'понеділок', category_id: '' })
        setEditingGroupId(null)
        setShowGroupForm(false)
    }

    // Видалити групу
    const deleteGroup = async (id) => {
        if (!confirm('Видалити цю групу?')) return

        try {
            await fetch(`${API_URL}/groups/${id}`, { method: 'DELETE' })
            fetchData()
        } catch (error) {
            logError('Помилка видалення групи', error)
        }
    }

    // === Резервне копіювання ===
    const downloadBackup = () => {
        // Відкриваємо ендпоінт у новій вкладці — браузер автоматично завантажить файл
        window.open(`${API_URL}/system/backup`, '_blank')
        setAlert({ type: 'success', text: '✅ Резервну копію завантажується...' })
    }

    const filenameFromDisposition = (header, fallback) => {
        const value = header || ''
        const utfMatch = value.match(/filename\*=UTF-8''([^;]+)/i)
        if (utfMatch?.[1]) return decodeURIComponent(utfMatch[1].replace(/"/g, ''))
        const plainMatch = value.match(/filename="?([^";]+)"?/i)
        return plainMatch?.[1] || fallback
    }

    const blobToBase64 = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '')
        reader.onerror = reject
        reader.readAsDataURL(blob)
    })

    const saveDiagnosticLog = async () => {
        setIsSavingDiagnosticLog(true)
        try {
            const response = await fetch(`${API_URL}/system/diagnostics/log-file`)
            if (!response.ok) {
                const data = await response.json().catch(() => ({}))
                throw new Error(data.detail || data.error || 'Не вдалося сформувати log файл')
            }

            const blob = await response.blob()
            const filename = filenameFromDisposition(
                response.headers.get('content-disposition'),
                `school_manager_log_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.txt`
            )

            const desktopApi = window.pywebview?.api
            if (desktopApi?.save_log_file_dialog) {
                const base64Payload = await blobToBase64(blob)
                const saveResult = await desktopApi.save_log_file_dialog(filename, base64Payload)
                if (saveResult?.cancelled) return
                if (!saveResult?.saved) {
                    throw new Error(saveResult?.error || 'Не вдалося зберегти log файл')
                }
                setAlert({ type: 'success', text: 'Log файл збережено' })
                return
            }

            const url = URL.createObjectURL(blob)
            const link = document.createElement('a')
            link.href = url
            link.download = filename
            document.body.appendChild(link)
            link.click()
            link.remove()
            URL.revokeObjectURL(url)
            setAlert({ type: 'success', text: 'Log файл завантажено' })
        } catch (error) {
            logError('Помилка збереження log файлу', error)
        } finally {
            setIsSavingDiagnosticLog(false)
        }
    }

    const handleRestoreFile = async (e) => {
        const file = e.target.files[0]
        if (!file) return
        if (!file.name.endsWith('.db')) {
            setAlert({ type: 'error', text: 'Оберіть файл з розширенням .db' })
            return
        }
        if (!confirm(`Відновити базу з файлу "${file.name}"? Поточні дані будуть замінені. Автоматичний бекап створиться. Продовжити?`)) {
            e.target.value = ''
            return
        }
        setIsRestoring(true)
        try {
            const formData = new FormData()
            formData.append('file', file)
            const res = await fetch(`${API_URL}/system/restore`, {
                method: 'POST',
                body: formData
            })
            const data = await res.json()
            if (data.ok) {
                setAlert({ type: 'success', text: '✅ ' + data.message })
                // Перезавантажуємо дані після відновлення
                fetchData()
            } else {
                setAlert({ type: 'error', text: data.error || 'Помилка відновлення' })
            }
        } catch (err) {
            logError('Помилка відновлення', err)
        } finally {
            setIsRestoring(false)
            e.target.value = ''
        }
    }

    const cleanupCache = async () => {
        if (!confirm('Очистити зайві файли кешу шаблонів та старі тимчасові імпорти? Наліпки залишаться на компʼютері.')) return
        setIsCleaningCache(true)
        try {
            const res = await fetch(`${API_URL}/system/cache/cleanup`, { method: 'POST' })
            const data = await res.json()
            if (res.ok && data.ok) {
                setAlert({ type: 'success', text: `Кеш очищено: видалено ${data.deleted_count} файлів, звільнено ${data.freed_mb} MB` })
            } else {
                setAlert({ type: 'error', text: data.error || data.detail || 'Не вдалося очистити кеш' })
            }
        } catch (error) {
            logError('Помилка очищення кешу', error)
        } finally {
            setIsCleaningCache(false)
            fetchCacheStatus()
        }
    }

    const cleanupStickers = async () => {
        if (!confirm('Очистити наліпки з програми і компʼютера? Після цього їх доведеться завантажувати з Telegram заново.')) return
        setIsCleaningStickers(true)
        try {
            const res = await fetch(`${API_URL}/system/cache/stickers/cleanup`, { method: 'POST' })
            const data = await res.json()
            if (res.ok && data.ok) {
                setAlert({ type: 'success', text: `Наліпки очищено: видалено ${data.deleted_count} файлів, звільнено ${data.freed_mb} MB` })
            } else {
                setAlert({ type: 'error', text: data.error || data.detail || 'Не вдалося очистити наліпки' })
            }
        } catch (error) {
            logError('Помилка очищення наліпок', error)
        } finally {
            setIsCleaningStickers(false)
            fetchCacheStatus()
        }
    }

    const formatBytes = (bytes = 0) => {
        if (!bytes) return '0 MB'
        const units = ['B', 'KB', 'MB', 'GB']
        let value = bytes
        let unitIndex = 0
        while (value >= 1024 && unitIndex < units.length - 1) {
            value /= 1024
            unitIndex += 1
        }
        const digits = value >= 10 || unitIndex < 2 ? 1 : 2
        return `${value.toFixed(digits)} ${units[unitIndex]}`
    }

    const openCacheFolder = async () => {
        setIsOpeningCacheFolder(true)
        try {
            const res = await fetch(`${API_URL}/system/cache/open-folder`, { method: 'POST' })
            const data = await res.json().catch(() => ({}))
            if (!res.ok || data.ok === false) {
                throw new Error(data.detail || data.error || 'Не вдалося відкрити папку')
            }
        } catch (error) {
            logError('Помилка відкриття папки кешу', error)
        } finally {
            setIsOpeningCacheFolder(false)
        }
    }

    const stickerCacheBytes = cacheStatus?.sticker_cache_bytes ?? 0
    const stickerCacheCount = cacheStatus?.sticker_cache_count ?? 0
    const runtimeBytes = cacheStatus?.runtime_total_bytes
    const runtimeCount = cacheStatus?.runtime_file_count
    const programFilesBytes = runtimeBytes !== undefined
        ? Math.max(0, runtimeBytes - stickerCacheBytes)
        : (cacheStatus?.total_bytes ?? 0)
    const programFilesCount = runtimeCount !== undefined
        ? Math.max(0, runtimeCount - stickerCacheCount)
        : (cacheStatus?.file_count ?? 0)

    const saveAutostart = async (enabled) => {
        setIsAutostartSaving(true)
        try {
            const res = await fetch(`${API_URL}/system/autostart`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            })
            const data = await res.json()
            if (res.ok && data.ok) {
                setAutostart(data)
                setAlert({
                    type: 'success',
                    text: enabled
                        ? 'Автозапуск увімкнено. Після старту системи програма відкриється у треї.'
                        : 'Автозапуск вимкнено.'
                })
            } else {
                setAlert({ type: 'error', text: data.detail || data.error || 'Не вдалося змінити автозапуск' })
            }
        } catch (error) {
            logError('Помилка налаштування автозапуску', error)
        } finally {
            setIsAutostartSaving(false)
        }
    }

    const saveWindowsNotifications = async (enabled) => {
        setIsNotificationsSaving(true)
        try {
            const res = await fetch(`${API_URL}/system/notifications`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled })
            })
            const data = await res.json()
            if (res.ok && data.ok) {
                setWindowsNotifications(data)
                setAlert({
                    type: 'success',
                    text: enabled
                        ? 'Системні сповіщення увімкнено.'
                        : 'Системні сповіщення вимкнено.'
                })
            } else {
                setAlert({ type: 'error', text: data.detail || data.error || 'Не вдалося змінити системні сповіщення' })
            }
        } catch (error) {
            logError('Помилка налаштування системних сповіщень', error)
        } finally {
            setIsNotificationsSaving(false)
        }
    }

    useEffect(() => {
        const closeCategoryMenu = () => setCategoryContextMenu(null)
        window.addEventListener('click', closeCategoryMenu)
        window.addEventListener('scroll', closeCategoryMenu, true)
        return () => {
            window.removeEventListener('click', closeCategoryMenu)
            window.removeEventListener('scroll', closeCategoryMenu, true)
        }
    }, [])

    useEffect(() => {
        if (authStep !== 'qr') return undefined
        const timer = setInterval(checkQrLogin, 3000)
        return () => clearInterval(timer)
    }, [authStep])

    useEffect(() => {
        const params = new URLSearchParams(location.search)
        const focus = params.get('focus')
        if (focus !== 'telegram' && focus !== 'groups' && focus !== 'logika') return undefined

        if (focus === 'groups') {
            setIsGroupsExpanded(true)
        }

        const targetRef = focus === 'telegram' ? telegramCardRef : focus === 'logika' ? logikaCardRef : groupsCardRef
        const scrollTimer = setTimeout(() => {
            targetRef.current?.scrollIntoView({
                behavior: 'smooth',
                block: focus === 'groups' ? 'start' : 'center'
            })
        }, focus === 'groups' ? 140 : 80)

        setFocusHighlight(focus)
        const highlightTimer = setTimeout(() => setFocusHighlight(null), 3000)

        return () => {
            clearTimeout(scrollTimer)
            clearTimeout(highlightTimer)
        }
    }, [location.search])

    return (
        <div>
            <div className="page-header">
                <h2>⚙️ Налаштування</h2>
                <p>Підключіть Telegram акаунт, групи та категорії</p>
            </div>

            {categoryContextMenu && (
                <div
                    className="context-menu category-context-menu"
                    style={{ left: categoryContextMenu.x, top: categoryContextMenu.y }}
                    onClick={(e) => e.stopPropagation()}
                    onContextMenu={(e) => e.preventDefault()}
                >
                    <button type="button" onClick={() => startRenameCategory(categoryContextMenu.category)}>
                        Перейменувати
                    </button>
                </div>
            )}

            {renamingCategory && (
                <div className="modal-overlay" onClick={cancelRenameCategory}>
                    <div className="modal category-rename-modal" onClick={(e) => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 className="modal-title">Перейменувати категорію</h3>
                            <button className="modal-close" type="button" onClick={cancelRenameCategory}>×</button>
                        </div>
                        <div className="form-group">
                            <label className="form-label">Назва категорії</label>
                            <input
                                autoFocus
                                type="text"
                                className="form-input"
                                value={renameCategoryName}
                                onChange={(e) => setRenameCategoryName(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') saveRenamedCategory()
                                    if (e.key === 'Escape') cancelRenameCategory()
                                }}
                            />
                        </div>
                        <div className="modal-actions">
                            <button type="button" className="btn btn-secondary" onClick={cancelRenameCategory}>
                                Скасувати
                            </button>
                            <button type="button" className="btn btn-primary" onClick={saveRenamedCategory}>
                                Зберегти
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <div className="settings-top-grid">
                {/* Авторизація Telegram */}
                <div
                    ref={telegramCardRef}
                    className={`card focus-scroll-target ${focusHighlight === 'telegram' ? 'focus-highlight' : ''}`}
                >
                    <h3 className="card-title" style={{ marginBottom: '20px' }}>📱 Telegram акаунт</h3>

                    <TelegramAuthPanel
                        mode="settings"
                        showLogoutActions
                        onAlert={setAlert}
                        onAuthorized={() => {
                            setIsConnected(true)
                        }}
                        onRefreshRequested={fetchData}
                        onDisconnected={() => setIsConnected(false)}
                        onStatusChange={({ isConnected: nextIsConnected, userInfo: nextUserInfo }) => {
                            setIsConnected(nextIsConnected)
                            setUserInfo(nextUserInfo)
                        }}
                    />

                    {false && (
                        <>
                {authStep === 'done' && isConnected ? (
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '16px', background: 'rgba(16, 185, 129, 0.1)', borderRadius: 'var(--radius-sm)', marginBottom: '16px' }}>
                            <span style={{ fontSize: '2rem' }}>✅</span>
                            <div>
                                <div style={{ fontWeight: 600, fontSize: '1.1rem' }}>{userInfo?.name || 'Підключено'}</div>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                    {userInfo?.username ? `@${userInfo.username}` : ''} {userInfo?.phone ? `• +${userInfo.phone}` : ''}
                                </div>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
                            <button className="btn btn-secondary btn-sm" onClick={logout}>Від’єднатися</button>
                            <button className="btn btn-danger btn-sm" onClick={logoutFull}>Вийти повністю</button>
                        </div>
                        <p style={{ marginTop: '10px', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                            “Від’єднатися” залишає збережену сесію і після перезапуску програма підключиться знову. “Вийти повністю” видаляє тільки Telegram-авторизацію, без видалення бази, груп, шаблонів і файлів.
                        </p>
                    </div>
                ) : (
                    <div>
                        {/* Крок 1: простий вхід */}
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

                                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <button className="btn btn-primary" onClick={sendCode} disabled={authLoading}>
                                        {authLoading ? 'Відправка...' : '📲 Увійти по номеру'}
                                    </button>
                                    <button className="btn btn-secondary" onClick={startQrLogin} disabled={authLoading}>
                                        {authLoading ? 'Створення QR...' : '▦ Увійти через QR'}
                                    </button>
                                </div>

                                <div style={{ marginTop: '18px' }}>
                                    <button
                                        type="button"
                                        className="btn btn-secondary btn-sm"
                                        onClick={() => setShowAdvancedAuth(prev => !prev)}
                                    >
                                        {showAdvancedAuth ? '▲ Сховати розширені налаштування' : '▶ Розширені налаштування'}
                                    </button>
                                </div>

                                {showAdvancedAuth && (
                                    <div style={{
                                        marginTop: '14px',
                                        padding: '16px',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius-sm)',
                                        background: 'var(--bg-input)'
                                    }}>
                                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: 0 }}>
                                            За замовчуванням використовується вбудований ключ додатку. Тут можна ввести власний API ID та API Hash.
                                            {hasCustomApiHash ? ' Власний API Hash уже збережений; щоб змінити його, введіть новий.' : ''}
                                        </p>
                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
                                            <div className="form-group">
                                                <label className="form-label">API ID</label>
                                                <input type="text" className="form-input" placeholder="12345678" value={apiId} onChange={e => setApiId(e.target.value)} />
                                            </div>
                                            <div className="form-group">
                                                <label className="form-label">API Hash</label>
                                                <input type="password" className="form-input" placeholder={hasCustomApiHash ? 'Збережено. Введіть новий для заміни' : 'abcdef1234567890...'} value={apiHash} onChange={e => setApiHash(e.target.value)} />
                                            </div>
                                        </div>
                                        {!hasBuiltinCredentials && (
                                            <p style={{ color: 'var(--warning)', fontSize: '0.9rem', marginBottom: 0 }}>
                                                Вбудований ключ недоступний, тому власні API ID та API Hash обов'язкові.
                                            </p>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* QR авторизація */}
                        {authStep === 'qr' && (
                            <div style={{ textAlign: 'center' }}>
                                <p style={{ color: 'var(--text-secondary)', marginBottom: '16px' }}>
                                    Відкрийте Telegram на телефоні: Налаштування → Пристрої → Підключити пристрій.
                                </p>
                                <p style={{ color: 'var(--warning)', fontSize: '0.88rem', margin: '-6px auto 16px', maxWidth: '520px' }}>
                                    Важливо: використовуйте саме розділ "Пристрої". Сканер QR-кодів у профілі Telegram призначений для профільних QR-кодів і може показувати помилку.
                                </p>
                                {qrImage ? (
                                    <img
                                        src={qrImage}
                                        alt="QR-код для входу в Telegram"
                                        style={{ width: '240px', maxWidth: '100%', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}
                                    />
                                ) : (
                                    <div className="loader"><div className="spinner"></div></div>
                                )}
                                {qrExpires && (
                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '12px' }}>
                                        QR-код оновлюється автоматично.
                                    </p>
                                )}
                                <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', flexWrap: 'wrap', marginTop: '16px' }}>
                                    <button className="btn btn-secondary" onClick={() => { setAuthStep('credentials'); setQrImage('') }}>
                                        Назад
                                    </button>
                                    <button className="btn btn-primary" onClick={checkQrLogin}>
                                        Перевірити
                                    </button>
                                </div>
                            </div>
                        )}

                        {/* Крок 2: SMS код */}
                        {authStep === 'code' && (
                            <div>
                                <p style={{ color: 'var(--text-secondary)', marginBottom: '12px' }}>Введіть код з Telegram (перевірте повідомлення від Telegram):</p>
                                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                                    <div className="form-group" style={{ flex: 1, maxWidth: '200px' }}>
                                        <input type="text" className="form-input" placeholder="12345" value={smsCode} onChange={e => setSmsCode(e.target.value)} onKeyDown={e => e.key === 'Enter' && verifyCode()} autoFocus />
                                    </div>
                                    <button className="btn btn-primary" onClick={verifyCode} disabled={authLoading}>
                                        {authLoading ? 'Перевірка...' : '✓ Підтвердити'}
                                    </button>
                                    <button className="btn btn-secondary" onClick={() => setAuthStep('credentials')}>Назад</button>
                                </div>
                            </div>
                        )}

                        {/* Крок 3: 2FA */}
                        {authStep === '2fa' && (
                            <div>
                                <p style={{ color: 'var(--text-secondary)', marginBottom: '12px' }}>Введіть пароль двофакторної аутентифікації:</p>
                                <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
                                    <div className="form-group" style={{ flex: 1, maxWidth: '300px' }}>
                                        <input type="password" className="form-input" placeholder="Пароль 2FA" value={twoFaPassword} onChange={e => setTwoFaPassword(e.target.value)} onKeyDown={e => e.key === 'Enter' && verify2FA()} autoFocus />
                                    </div>
                                    <button className="btn btn-primary" onClick={verify2FA} disabled={authLoading}>
                                        {authLoading ? 'Перевірка...' : '🔐 Підтвердити'}
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                )}
                    </>
                )}
                </div>

                <div className="card settings-google-ai-card">
                    <div className="card-header" style={{ marginBottom: '16px' }}>
                        <div>
                            <h3 className="card-title" style={{ marginBottom: '8px' }}>✨ Google AI</h3>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                                Ключ використовується для генерації звітів батькам і зберігається локально на цьому комп'ютері.
                            </p>
                        </div>
                    </div>

                    <div className="settings-google-ai-grid">
                        <label className="form-group">
                            <span className="form-label">Google AI API key</span>
                            <div className="parents-secret-input">
                                <input
                                    className="form-input"
                                    type={googleApiKeyVisible ? 'text' : 'password'}
                                    value={googleApiKeyDraft}
                                    onFocus={() => {
                                        if (!googleApiKeyTouched && !googleApiKeyVisible && reportSettings?.google_ai_api_key_set) {
                                            setGoogleApiKeyDraft('')
                                        }
                                    }}
                                    onChange={(event) => {
                                        setGoogleApiKeyDraft(event.target.value)
                                        setGoogleApiKeyTouched(true)
                                    }}
                                    placeholder={reportSettings?.google_ai_api_key_set ? 'Ключ збережено' : 'Вставте API key'}
                                />
                                <button
                                    type="button"
                                    className="parents-secret-toggle"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={toggleGoogleApiKeyVisible}
                                    disabled={googleApiKeyRevealLoading}
                                    aria-label={googleApiKeyVisible ? 'Приховати API key' : 'Показати API key'}
                                    title={googleApiKeyVisible ? 'Приховати API key' : 'Показати API key'}
                                >
                                    <EyeIcon crossed={googleApiKeyVisible} />
                                </button>
                            </div>
                        </label>

                        <label className="form-group">
                            <span className="form-label">Модель Gemini</span>
                            <AppSelect
                                value={reportSettings?.google_ai_model || 'gemini-2.5-flash'}
                                options={reportModelOptions}
                                onChange={(value) => updateReportSetting('google_ai_model', value)}
                                ariaLabel="Модель Gemini"
                            />
                        </label>
                    </div>

                    <div className="settings-google-ai-actions">
                        <button className="btn btn-primary settings-google-ai-save" onClick={saveGoogleAiSettings} disabled={isGoogleAiSaving}>
                            {isGoogleAiSaving ? 'Зберігаю...' : 'Зберегти Google AI'}
                        </button>
                        <div className="parents-ai-link-row">
                            <button
                                type="button"
                                className="btn btn-secondary parents-external-link"
                                onClick={() => openExternalUrl(AI_STUDIO_API_KEY_URL)}
                                title="Відкрити сторінку Google AI Studio, де можна створити або скопіювати API key"
                            >
                                <ExternalLinkIcon />
                                API key
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary parents-external-link"
                                onClick={() => openExternalUrl(AI_STUDIO_RATE_LIMIT_URL)}
                                title="Відкрити реальні ліміти та використання в Google AI Studio"
                            >
                                <ExternalLinkIcon />
                                Ліміти AI Studio
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <div ref={logikaCardRef} className={`card ${focusHighlight === 'logika' ? 'highlight-focus' : ''}`} style={{ marginBottom: '24px' }}>
                <div className="card-header" style={{ marginBottom: '16px' }}>
                    <div>
                        <h3 className="card-title" style={{ marginBottom: '8px' }}>🎓 Logika Backoffice</h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Вхід під акаунтом викладача для автоматичного отримання розкладу уроків, тем та списку присутніх/відсутніх учнів після уроку.
                        </p>
                    </div>
                </div>

                {logikaSettings?.is_configured ? (
                    <div>
                        <div style={{
                            background: 'rgba(34, 197, 94, 0.08)',
                            border: '1px solid rgba(34, 197, 94, 0.25)',
                            borderRadius: '8px',
                            padding: '14px 16px',
                            marginBottom: '16px',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            flexWrap: 'wrap',
                            gap: '12px'
                        }}>
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                    <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: 'var(--success, #22c55e)' }} />
                                    <strong style={{ fontSize: '1rem' }}>
                                        {logikaSettings.teacher_name ? `Викладач: ${logikaSettings.teacher_name}` : 'Підключено'}
                                    </strong>
                                </div>
                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    Логін: <strong>{logikaSettings.login}</strong>
                                    {logikaSettings.last_sync_at ? (
                                        <span> • Останнє оновлення: {new Date(logikaSettings.last_sync_at).toLocaleString('uk-UA')} ({logikaSettings.last_sync_count} уроків)</span>
                                    ) : null}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <button
                                    type="button"
                                    className="btn btn-primary btn-sm"
                                    onClick={handleLogikaSync}
                                    disabled={isLogikaSyncing}
                                >
                                    {isLogikaSyncing ? 'Синхронізація...' : '🔄 Синхронізувати розклад'}
                                </button>
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm"
                                    onClick={handleLogikaDisconnect}
                                    disabled={isLogikaDisconnecting}
                                >
                                    {isLogikaDisconnecting ? 'Вихід...' : 'Вийти'}
                                </button>
                            </div>
                        </div>

                        <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap', paddingBottom: '14px', borderBottom: '1px solid var(--border)' }}>
                                <div style={{ flex: '1 1 280px' }}>
                                    <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.95rem', marginBottom: '4px' }}>
                                        Автоматично підтягувати відсутніх учнів
                                    </div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                        Після закінчення уроку зчитує відмітки з журналу Logika та вставляє імена відсутніх у звіт
                                    </div>
                                </div>
                                <label
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '10px',
                                        cursor: 'pointer',
                                        userSelect: 'none',
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={!!logikaSettings.auto_fetch_absents}
                                        onChange={(e) => handleLogikaToggle('auto_fetch_absents', e.target.checked)}
                                        style={{ display: 'none' }}
                                    />
                                    <span style={{
                                        position: 'relative',
                                        width: '48px',
                                        height: '26px',
                                        borderRadius: '999px',
                                        background: logikaSettings.auto_fetch_absents ? 'var(--success, #22c55e)' : 'var(--border)',
                                        transition: 'background 0.2s ease',
                                        flex: '0 0 auto'
                                    }}>
                                        <span style={{
                                            position: 'absolute',
                                            top: '3px',
                                            left: logikaSettings.auto_fetch_absents ? '25px' : '3px',
                                            width: '20px',
                                            height: '20px',
                                            borderRadius: '50%',
                                            background: '#fff',
                                            boxShadow: 'var(--shadow-sm)',
                                            transition: 'left 0.2s ease'
                                        }} />
                                    </span>
                                    <span style={{ fontWeight: 600, minWidth: '70px' }}>
                                        {logikaSettings.auto_fetch_absents ? 'Увімкнено' : 'Вимкнено'}
                                    </span>
                                </label>
                            </div>

                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap', paddingTop: '14px' }}>
                                <div style={{ flex: '1 1 280px' }}>
                                    <div style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.95rem', marginBottom: '4px' }}>
                                        Автоматично синхронізувати розклад при старті програми
                                    </div>
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                        При кожному запуску School Manager актуалізує список груп, тем і розклад з Logika
                                    </div>
                                </div>
                                <label
                                    style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '10px',
                                        cursor: 'pointer',
                                        userSelect: 'none',
                                    }}
                                >
                                    <input
                                        type="checkbox"
                                        checked={!!logikaSettings.auto_sync_enabled}
                                        onChange={(e) => handleLogikaToggle('auto_sync_enabled', e.target.checked)}
                                        style={{ display: 'none' }}
                                    />
                                    <span style={{
                                        position: 'relative',
                                        width: '48px',
                                        height: '26px',
                                        borderRadius: '999px',
                                        background: logikaSettings.auto_sync_enabled ? 'var(--success, #22c55e)' : 'var(--border)',
                                        transition: 'background 0.2s ease',
                                        flex: '0 0 auto'
                                    }}>
                                        <span style={{
                                            position: 'absolute',
                                            top: '3px',
                                            left: logikaSettings.auto_sync_enabled ? '25px' : '3px',
                                            width: '20px',
                                            height: '20px',
                                            borderRadius: '50%',
                                            background: '#fff',
                                            boxShadow: 'var(--shadow-sm)',
                                            transition: 'left 0.2s ease'
                                        }} />
                                    </span>
                                    <span style={{ fontWeight: 600, minWidth: '70px' }}>
                                        {logikaSettings.auto_sync_enabled ? 'Увімкнено' : 'Вимкнено'}
                                    </span>
                                </label>
                            </div>
                        </div>
                    </div>
                ) : (
                    <form onSubmit={handleLogikaLogin} style={{ maxWidth: '500px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '16px' }}>
                            <label className="form-group" style={{ margin: 0 }}>
                                <span className="form-label">Логін Logika</span>
                                <input
                                    className="form-input"
                                    type="text"
                                    value={logikaLoginDraft}
                                    onChange={(e) => setLogikaLoginDraft(e.target.value)}
                                    placeholder="Введіть ваш логін (напр. miablonskyi)"
                                    disabled={isLogikaLoggingIn}
                                    required
                                />
                            </label>

                            <label className="form-group" style={{ margin: 0 }}>
                                <span className="form-label">Пароль Logika</span>
                                <div className="parents-secret-input">
                                    <input
                                        className="form-input"
                                        type={logikaPasswordVisible ? 'text' : 'password'}
                                        value={logikaPasswordDraft}
                                        onChange={(e) => setLogikaPasswordDraft(e.target.value)}
                                        placeholder="Введіть ваш пароль"
                                        disabled={isLogikaLoggingIn}
                                        required
                                    />
                                    <button
                                        type="button"
                                        className="parents-secret-toggle"
                                        onClick={() => setLogikaPasswordVisible(!logikaPasswordVisible)}
                                        aria-label="Перемкнути видимість пароля"
                                    >
                                        <EyeIcon crossed={logikaPasswordVisible} />
                                    </button>
                                </div>
                            </label>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                disabled={isLogikaLoggingIn}
                            >
                                {isLogikaLoggingIn ? 'Вхід у Logika...' : 'Увійти в Logika'}
                            </button>
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Авторизація працює локально на вашому комп'ютері
                            </span>
                        </div>
                    </form>
                )}
            </div>

            <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 280px' }}>
                        <h3 className="card-title" style={{ marginBottom: '8px' }}>🚀 Автозапуск програми</h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Програма запускається при старті системи.
                        </p>
                    </div>
                    <label
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '10px',
                            cursor: autostart.supported && !isAutostartSaving ? 'pointer' : 'not-allowed',
                            userSelect: 'none',
                            opacity: autostart.supported ? 1 : 0.6
                        }}
                    >
                        <input
                            type="checkbox"
                            checked={!!autostart.enabled}
                            onChange={(e) => saveAutostart(e.target.checked)}
                            disabled={!autostart.supported || isAutostartSaving}
                            style={{ display: 'none' }}
                        />
                        <span style={{
                            position: 'relative',
                            width: '48px',
                            height: '26px',
                            borderRadius: '999px',
                            background: autostart.enabled ? 'var(--success)' : 'var(--border)',
                            transition: 'background 0.2s ease',
                            flex: '0 0 auto'
                        }}>
                            <span style={{
                                position: 'absolute',
                                top: '3px',
                                left: autostart.enabled ? '25px' : '3px',
                                width: '20px',
                                height: '20px',
                                borderRadius: '50%',
                                background: '#fff',
                                boxShadow: 'var(--shadow-sm)',
                                transition: 'left 0.2s ease'
                            }} />
                        </span>
                        <span style={{ fontWeight: 600 }}>
                            {isAutostartSaving ? 'Збереження...' : autostart.enabled ? 'Увімкнено' : 'Вимкнено'}
                        </span>
                    </label>

                </div>
                <div style={{ marginTop: '18px', paddingTop: '16px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 280px' }}>
                        <h4 style={{ margin: '0 0 6px', color: 'var(--text-primary)', fontSize: '1rem' }}>Системні сповіщення</h4>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Показувати повідомлення біля трея, коли програма запланувала автоповідомлення в Telegram.
                        </p>
                    </div>
                    <label
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '10px',
                            cursor: windowsNotifications.supported && !isNotificationsSaving ? 'pointer' : 'not-allowed',
                            userSelect: 'none',
                            opacity: windowsNotifications.supported ? 1 : 0.6
                        }}
                    >
                        <input
                            type="checkbox"
                            checked={!!windowsNotifications.enabled}
                            onChange={(e) => saveWindowsNotifications(e.target.checked)}
                            disabled={!windowsNotifications.supported || isNotificationsSaving}
                            style={{ display: 'none' }}
                        />
                        <span style={{
                            position: 'relative',
                            width: '48px',
                            height: '26px',
                            borderRadius: '999px',
                            background: windowsNotifications.enabled ? 'var(--success)' : 'var(--border)',
                            transition: 'background 0.2s ease',
                            flex: '0 0 auto'
                        }}>
                            <span style={{
                                position: 'absolute',
                                top: '3px',
                                left: windowsNotifications.enabled ? '25px' : '3px',
                                width: '20px',
                                height: '20px',
                                borderRadius: '50%',
                                background: '#fff',
                                boxShadow: 'var(--shadow-sm)',
                                transition: 'left 0.2s ease'
                            }} />
                        </span>
                        <span style={{ fontWeight: 600 }}>
                            {isNotificationsSaving ? 'Збереження...' : windowsNotifications.enabled ? 'Увімкнено' : 'Вимкнено'}
                        </span>
                    </label>
                </div>
                {!autostart.supported && (
                    <p style={{ color: 'var(--warning)', fontSize: '0.9rem', marginTop: '12px', marginBottom: 0 }}>
                        Автозапуск доступний у Windows та macOS-версіях програми.
                    </p>
                )}
                {!windowsNotifications.supported && (
                    <p style={{ color: 'var(--warning)', fontSize: '0.9rem', marginTop: '12px', marginBottom: 0 }}>
                        Системні сповіщення доступні у Windows та macOS-версіях програми.
                    </p>
                )}
                {autostart.enabled && !autostart.starts_in_tray && (
                    <p style={{ color: 'var(--warning)', fontSize: '0.9rem', marginTop: '12px', marginBottom: 0 }}>
                        Запис автозапуску знайдено, але він не містить режим запуску у треї. Вимкніть і увімкніть перемикач ще раз.
                    </p>
                )}
            </div>

            {/* === Категорії === */}
            <div className="card">
                <h3 className="card-title" style={{ marginBottom: '20px' }}>📁 Категорії груп</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '16px' }}>
                    Створіть категорії для зручного групування (напр. за містом, типом уроку тощо)
                </p>

                {/* Форма створення категорії */}
                <div style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
                    <input
                        type="text"
                        className="form-input"
                        placeholder="Назва категорії (напр. Миронівка)"
                        value={newCategoryName}
                        onChange={(e) => setNewCategoryName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && createCategory()}
                        style={{ flex: '1', minWidth: '180px' }}
                    />
                    <button className="btn btn-success btn-sm" onClick={createCategory}>
                        + Додати
                    </button>
                </div>

                {/* Список категорій */}
                {categories.length === 0 ? (
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                        Категорій ще немає. Створіть першу!
                    </div>
                ) : (
                    <div className="category-manage-list">
                        {categories.map(cat => {
                            const count = groups.filter(g => g.category_id === cat.id).length
                            return (
                                <div
                                    key={cat.id}
                                    className="category-manage-item"
                                    onContextMenu={(e) => openCategoryContextMenu(e, cat)}
                                >
                                    <span>📁 {cat.name}</span>
                                    <span className="category-badge">{count} груп</span>
                                    <button
                                        className="cat-delete-btn"
                                        onClick={() => deleteCategory(cat.id, cat.name)}
                                        title="Видалити категорію"
                                    >
                                        ✕
                                    </button>
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>

            {/* Групи */}
            <div
                ref={groupsCardRef}
                className={`card focus-scroll-target ${focusHighlight === 'groups' ? 'focus-highlight' : ''}`}
            >
                <div className="card-header" style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: '15px',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: isGroupsExpanded ? '20px' : 0,
                    paddingBottom: isGroupsExpanded ? '16px' : 0,
                    borderBottom: isGroupsExpanded ? '1px solid var(--border)' : 'none'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flexWrap: 'wrap' }}>
                        <h3 className="card-title" style={{ margin: 0 }}>👥 Групи Telegram</h3>
                        <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => setIsGroupsExpanded(prev => !prev)}
                            aria-expanded={isGroupsExpanded}
                            style={{ whiteSpace: 'nowrap' }}
                        >
                            {isGroupsExpanded ? '▲ Згорнути' : '▶ Розгорнути'}
                        </button>
                        <input
                            type="text"
                            placeholder="Пошук групи..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            style={{
                                padding: '6px 12px',
                                borderRadius: 'var(--radius-sm)',
                                border: '1px solid var(--border)',
                                background: 'var(--bg-input)',
                                color: 'var(--text)',
                                outline: 'none',
                                minWidth: '220px',
                                fontSize: '0.9rem'
                            }}
                        />
                    </div>
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={syncGroups}
                            disabled={isSyncing}
                        >
                            {isSyncing ? '🔄 Синхронізація...' : '🔄 Синхронізувати'}
                        </button>
                        <button className="btn btn-primary btn-sm" onClick={() => {
                            if (showGroupForm) cancelEditGroup()
                            else {
                                setIsGroupsExpanded(true)
                                setShowGroupForm(true)
                            }
                        }}>
                            {showGroupForm ? '✕ Закрити' : '+ Додати групу'}
                        </button>
                    </div>
                </div>

                {isGroupsExpanded && (
                    <>
                        {/* Форма додавання групи */}
                        {showGroupForm && (
                            <div style={{
                                background: 'var(--bg-input)',
                                padding: '20px',
                                borderRadius: 'var(--radius-md)',
                                marginBottom: '20px'
                            }}>
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px' }}>
                                    <div className="form-group">
                                        <label className="form-label">Назва групи</label>
                                        <input
                                            type="text"
                                            className="form-input"
                                            placeholder="Наприклад: Фронтенд"
                                            value={newGroup.name}
                                            onChange={(e) => setNewGroup({ ...newGroup, name: e.target.value })}
                                        />
                                    </div>

                                    <div className="form-group">
                                        <label className="form-label">ID групи в Telegram</label>
                                        <input
                                            type="text"
                                            className="form-input"
                                            placeholder="-100123456789"
                                            value={newGroup.telegram_id}
                                            onChange={(e) => setNewGroup({ ...newGroup, telegram_id: e.target.value })}
                                        />
                                    </div>

                                    <div className="form-group">
                                        <label className="form-label">Категорія</label>
                                        <AppSelect
                                            value={newGroup.category_id || ''}
                                            options={[
                                                { value: '', label: 'Без категорії' },
                                                ...categories.map(cat => ({ value: cat.id, label: cat.name }))
                                            ]}
                                            onChange={(value) => setNewGroup({ ...newGroup, category_id: value || null })}
                                            ariaLabel="Категорія групи"
                                        />
                                    </div>

                                    <div className="form-group">
                                        <label className="form-label">День уроку</label>
                                        <AppSelect
                                            value={newGroup.lesson_day}
                                            options={DAY_OPTIONS}
                                            onChange={(value) => setNewGroup({ ...newGroup, lesson_day: value })}
                                            ariaLabel="День уроку"
                                        />
                                    </div>

                                    <div className="form-group">
                                        <label className="form-label">Час уроку</label>
                                        <TimePicker
                                            value={newGroup.lesson_time}
                                            onChange={(value) => setNewGroup({ ...newGroup, lesson_time: value })}
                                            ariaLabel="Час уроку"
                                        />
                                    </div>
                                </div>

                                <div style={{ display: 'flex', gap: '12px' }}>
                                    <button className="btn btn-success" onClick={saveGroup}>
                                        {editingGroupId ? '✓ Зберегти зміни' : '✓ Додати групу'}
                                    </button>
                                    {editingGroupId && (
                                        <button className="btn btn-secondary" onClick={cancelEditGroup}>
                                            Скасувати
                                        </button>
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Таблиця груп */}
                        {loading ? (
                            <div className="loader"><div className="spinner"></div></div>
                        ) : groups.length === 0 ? (
                            <div className="empty-state">
                                <p>Групи не додано. Додайте першу групу!</p>
                            </div>
                        ) : (
                            <div className="table-container">
                                <table className="table">
                                    <thead>
                                        <tr>
                                            <th
                                                onClick={() => handleSort('name')}
                                                style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                                            >
                                                Назва {sortBy === 'name' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                                            </th>
                                            <th
                                                onClick={() => handleSort('category')}
                                                style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                                            >
                                                Категорія {sortBy === 'category' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                                            </th>
                                            <th>ID групи</th>
                                            <th
                                                onClick={() => handleSort('day')}
                                                style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                                            >
                                                День уроку {sortBy === 'day' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                                            </th>
                                            <th
                                                onClick={() => handleSort('time')}
                                                style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                                            >
                                                Час уроку {sortBy === 'time' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                                            </th>
                                            <th>Дії</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {sortedGroups.map(group => (
                                            <tr key={group.id}>
                                                <td><strong>{group.name}</strong></td>
                                                <td>
                                                    {group.category_name
                                                        ? <span className="category-badge">📁 {group.category_name}</span>
                                                        : <span style={{ color: 'var(--text-secondary)' }}>—</span>
                                                    }
                                                </td>
                                                <td style={{ fontFamily: 'monospace' }}>{group.telegram_id}</td>
                                                <td>{group.lesson_day || '-'}</td>
                                                <td>{group.lesson_time || '-'}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                                        <button
                                                            className="btn btn-secondary btn-sm"
                                                            onClick={() => startEditGroup(group)}
                                                        >
                                                            ✏️ Редагувати
                                                        </button>
                                                        <button
                                                            className="btn btn-danger btn-sm"
                                                            onClick={() => deleteGroup(group.id)}
                                                        >
                                                            🗑 Видалити
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* === Резервне копіювання === */}
            <div className="card">
                <h3 className="card-title" style={{ marginBottom: '12px' }}>💾 Резервне копіювання</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '20px' }}>
                    Збережіть або відновіть всі ваші дані (групи, автоповідомлення, шаблони, налаштування Telegram).
                    Перед відновленням автоматично створюється бекап поточної БД.
                </p>
                <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
                    {/* Кнопка ЕКСПОРТУ */}
                    <button className="btn btn-success" onClick={downloadBackup}>
                        ⬇️ Завантажити резервну копію
                    </button>

                    {/* Кнопка ІМПОРТУ (прихований input[file]) */}
                    <label className="btn btn-secondary" style={{ cursor: 'pointer' }}>
                        {isRestoring ? 'Відновлення...' : '⬆️ Відновити з резервної копії'}
                        <input
                            type="file"
                            accept=".db"
                            style={{ display: 'none' }}
                            onChange={handleRestoreFile}
                            disabled={isRestoring}
                        />
                    </label>
                    <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={saveDiagnosticLog}
                        disabled={isSavingDiagnosticLog}
                        title="Зберегти діагностичний log файл для перевірки помилок"
                    >
                        {isSavingDiagnosticLog ? 'Збереження log...' : 'Зберегти log файл'}
                    </button>
                </div>
            </div>

            <div className="card">
                <h3 className="card-title" style={{ marginBottom: '12px' }}>Кеш програми</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '20px' }}>
                    Кеш програми очищає тільки зайві файли шаблонів і старі тимчасові імпорти. Наліпки винесені окремо, щоб випадково не завантажувати їх знову.
                </p>
                <div className="cache-actions-row">
                    <button className="btn btn-danger" onClick={cleanupCache} disabled={isCleaningCache}>
                        {isCleaningCache ? 'Очищення...' : 'Очистити кеш програми'}
                    </button>
                    <button className="btn btn-secondary" onClick={cleanupStickers} disabled={isCleaningStickers}>
                        {isCleaningStickers ? 'Очищення...' : 'Очистити наліпки'}
                    </button>
                    <button
                        type="button"
                        className="cache-size-pill"
                        onClick={openCacheFolder}
                        disabled={isOpeningCacheFolder}
                        title="Відкрити папку з файлами програми"
                    >
                        <span>Файли програми</span>
                        <strong>{formatBytes(programFilesBytes)}</strong>
                        <small>
                            {isOpeningCacheFolder
                                ? 'Відкриття...'
                                : `${programFilesCount} файлів · відкрити папку`}
                        </small>
                    </button>
                    <button
                        type="button"
                        className="cache-size-pill cache-size-pill-danger"
                        onClick={openCacheFolder}
                        disabled={isOpeningCacheFolder}
                        title="Відкрити папку, де зберігаються наліпки"
                    >
                        <span>Наліпки</span>
                        <strong>{formatBytes(stickerCacheBytes)}</strong>
                        <small>
                            {isOpeningCacheFolder
                                ? 'Відкриття...'
                                : `${stickerCacheCount} файлів · окрема очистка`}
                        </small>
                    </button>
                </div>
            </div>
        </div>
    )
}

export default Settings

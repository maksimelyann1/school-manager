import { useEffect, useMemo, useRef, useState } from 'react'
import FloatingPanel from '../components/FloatingPanel'
import { NumberStepper } from '../components/FormControls'
import TelegramSendIcon from '../components/TelegramSendIcon'
import { getSearchVariations } from '../utils/search'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

const TABS = [
    { id: 'pending', label: 'Потребують звіт' },
    { id: 'schedule', label: 'Розклад' },
    { id: 'database', label: 'База даних' },
    { id: 'settings', label: 'Налаштування' },
    { id: 'runs', label: 'Журнал' }
]

const DAYS = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'НД']
const DAY_SORT_ORDER = Object.fromEntries(DAYS.map((day, index) => [day, index]))

const SCHEDULE_COLUMNS = [
    { id: 'group', label: 'Група', width: 320, minWidth: 190, sortKey: 'group_name' },
    { id: 'day', label: 'День', width: 74, minWidth: 62, sortKey: 'day' },
    { id: 'time', label: 'Час', width: 86, minWidth: 72 },
    { id: 'course', label: 'Курс', width: 220, minWidth: 150 },
    { id: 'lesson_code', label: 'Урок', width: 92, minWidth: 70 },
    { id: 'lesson_count', label: 'Кількість проведених уроків', width: 190, minWidth: 132 },
    { id: 'report_date', label: 'Дата звіту', width: 128, minWidth: 112 },
    { id: 'absents', label: 'Відсутні', width: 150, minWidth: 110 },
    { id: 'lesson_title', label: 'Тема уроку', width: 280, minWidth: 170 },
    { id: 'duration', label: 'Тривалість', width: 96, minWidth: 82 },
    { id: 'actions', label: '', width: 64, minWidth: 56 }
]

const READONLY_SCHEDULE_COLUMNS = SCHEDULE_COLUMNS.filter(column => column.id !== 'actions')
const COLUMN_WIDTHS_STORAGE_KEY = 'school_manager.parents_report.column_widths.v1'
const DEFAULT_COLUMN_WIDTHS = Object.fromEntries(SCHEDULE_COLUMNS.map(column => [column.id, column.width]))

function loadColumnWidths() {
    if (typeof window === 'undefined') return DEFAULT_COLUMN_WIDTHS
    try {
        const saved = JSON.parse(window.localStorage.getItem(COLUMN_WIDTHS_STORAGE_KEY) || '{}')
        return Object.fromEntries(SCHEDULE_COLUMNS.map(column => {
            const width = Number(saved[column.id])
            return [
                column.id,
                Number.isFinite(width) ? Math.max(column.minWidth || 0, width) : column.width
            ]
        }))
    } catch {
        return DEFAULT_COLUMN_WIDTHS
    }
}

function TrashIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M3 6h18" />
            <path d="M8 6V4h8v2" />
            <path d="M19 6l-1 14H6L5 6" />
            <path d="M10 11v5" />
            <path d="M14 11v5" />
        </svg>
    )
}

function PostponeIcon() {
    return (
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
            <rect x="4.25" y="5.25" width="15.5" height="14" rx="2.4" />
            <path d="M8 3.5v3.2M16 3.5v3.2M4.25 9.25h15.5" />
            <path d="M8.5 14h6.8" />
            <path d="m12.9 11.6 2.4 2.4-2.4 2.4" />
        </svg>
    )
}

function EditableText({ value, onSave, multiline = false, type = 'text', className = '', placeholder = '' }) {
    const [draft, setDraft] = useState(value ?? '')

    useEffect(() => {
        setDraft(value ?? '')
    }, [value])

    const commit = () => {
        const next = String(draft ?? '')
        if (next !== String(value ?? '')) {
            onSave(next)
        }
    }

    const handleKeyDown = (event) => {
        if (!multiline && event.key === 'Enter') {
            event.preventDefault()
            event.currentTarget.blur()
        }
        if (event.key === 'Escape') {
            setDraft(value ?? '')
            event.currentTarget.blur()
        }
    }

    if (multiline) {
        return (
            <textarea
                className={`parents-cell-input parents-cell-textarea ${className}`}
                value={draft}
                placeholder={placeholder}
                onChange={(event) => setDraft(event.target.value)}
                onBlur={commit}
                onKeyDown={handleKeyDown}
                rows={3}
            />
        )
    }

    return (
        <input
            className={`parents-cell-input ${className}`}
            type={type}
            value={draft}
            placeholder={placeholder}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commit}
            onKeyDown={handleKeyDown}
        />
    )
}

function GroupMappingCell({ lesson, groups, onSelect }) {
    const [open, setOpen] = useState(false)
    const [query, setQuery] = useState('')
    const rootRef = useRef(null)
    const controlRef = useRef(null)
    const dropdownRef = useRef(null)

    const selectedGroup = groups.find(group => String(group.id) === String(lesson.telegram_group_id))
    const terms = getSearchVariations(query)
    const filteredGroups = groups.filter(group => {
        const raw = query.trim()
        if (!raw) return true
        const searchable = [
            group.name,
            group.category_name,
            group.telegram_id,
            group.lesson_day,
            group.lesson_time
        ].filter(Boolean).join(' ').toLowerCase()
        return terms.some(term => searchable.includes(term))
    })

    const categories = [...new Set(filteredGroups.map(group => group.category_name).filter(Boolean))]
    const sections = [
        ...categories.map(categoryName => ({
            label: categoryName,
            groups: filteredGroups.filter(group => group.category_name === categoryName)
        })),
        ...(filteredGroups.some(group => !group.category_name)
            ? [{ label: 'Без категорії', groups: filteredGroups.filter(group => !group.category_name) }]
            : [])
    ]

    useEffect(() => {
        if (!open) return undefined
        const handleClick = (event) => {
            if (
                rootRef.current?.contains(event.target) ||
                dropdownRef.current?.contains(event.target)
            ) {
                return
            }
            setOpen(false)
        }
        document.addEventListener('mousedown', handleClick)
        return () => document.removeEventListener('mousedown', handleClick)
    }, [open])

    const chooseGroup = (group) => {
        onSelect(group)
        setQuery('')
        setOpen(false)
    }

    return (
        <div className="parents-group-cell" ref={rootRef}>
            <button
                type="button"
                className={`parents-group-cell-button ${selectedGroup ? 'mapped' : ''}`}
                onClick={() => setOpen(prev => !prev)}
                ref={controlRef}
            >
                <span>{lesson.group_name || 'Вибрати групу'}</span>
                <small>{selectedGroup ? selectedGroup.name : 'TG не вибрано'}</small>
            </button>
            <FloatingPanel
                open={open}
                anchorRef={controlRef}
                panelRef={dropdownRef}
                className="group-picker-dropdown parents-group-dropdown"
                matchWidth={false}
                width={520}
                maxHeight={360}
                zIndex={12000}
            >
                <div className="parents-group-search">
                    <input
                        className="group-picker-input"
                        value={query}
                        placeholder="Пошук Telegram-групи..."
                        onChange={(event) => setQuery(event.target.value)}
                        autoFocus
                    />
                </div>
                {filteredGroups.length === 0 ? (
                    <div className="group-picker-empty">Групи не знайдено</div>
                ) : sections.map(section => (
                    <div className="group-picker-section" key={section.label}>
                        <div className="group-picker-section-title">{section.label}</div>
                        {section.groups.map(group => (
                            <button
                                type="button"
                                key={group.id}
                                className={`group-picker-option ${String(group.id) === String(lesson.telegram_group_id) ? 'selected' : ''}`}
                                onClick={() => chooseGroup(group)}
                            >
                                <span>{group.name}</span>
                                <small>
                                    {[group.lesson_day, group.lesson_time].filter(Boolean).join(' · ') || group.telegram_id}
                                </small>
                            </button>
                        ))}
                    </div>
                ))}
            </FloatingPanel>
        </div>
    )
}

function ParentsReport() {
    const [activeTab, setActiveTab] = useState('pending')
    const [activeSheet, setActiveSheet] = useState('schedule')
    const [settings, setSettings] = useState(null)
    const [pending, setPending] = useState([])
    const [workbook, setWorkbook] = useState({ schedule: [], courses: [], sheet_names: [] })
    const [groups, setGroups] = useState([])
    const [runs, setRuns] = useState([])
    const [alert, setAlert] = useState(null)
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState('')
    const [absentsByLesson, setAbsentsByLesson] = useState({})
    const [postponeModal, setPostponeModal] = useState(null)
    const [newCourseName, setNewCourseName] = useState('')
    const [scheduleSort, setScheduleSort] = useState({ key: '', direction: 'asc' })
    const [columnWidths, setColumnWidths] = useState(loadColumnWidths)
    const fileInputRef = useRef(null)
    const postponeAnchorRef = useRef(null)
    const postponePanelRef = useRef(null)
    const postponeDateInputRef = useRef(null)
    const postponeTimeInputRef = useRef(null)
    const sourceSyncAttemptedRef = useRef(false)
    const reportSendLockRef = useRef(new Set())

    const lessons = workbook.schedule || []
    const courses = workbook.courses || []
    const readyPendingCount = pending.filter(item => item.mapping_ready).length
    const mappedCount = lessons.filter(item => item.telegram_group_id).length
    const sortedLessons = useMemo(() => {
        if (!scheduleSort.key) return lessons
        const direction = scheduleSort.direction === 'desc' ? -1 : 1
        return [...lessons].sort((left, right) => {
            if (scheduleSort.key === 'day') {
                const leftDay = DAY_SORT_ORDER[left.day] ?? 99
                const rightDay = DAY_SORT_ORDER[right.day] ?? 99
                if (leftDay !== rightDay) return (leftDay - rightDay) * direction
                return String(left.start_time || '').localeCompare(String(right.start_time || ''), 'uk') * direction
            }
            const leftValue = String(left[scheduleSort.key] || '').toLocaleLowerCase('uk')
            const rightValue = String(right[scheduleSort.key] || '').toLocaleLowerCase('uk')
            return leftValue.localeCompare(rightValue, 'uk', { numeric: true, sensitivity: 'base' }) * direction
        })
    }, [lessons, scheduleSort])

    useEffect(() => {
        loadAll()
    }, [])

    useEffect(() => {
        try {
            window.localStorage.setItem(COLUMN_WIDTHS_STORAGE_KEY, JSON.stringify(columnWidths))
        } catch {
            // localStorage can be unavailable in private or restricted webview contexts.
        }
    }, [columnWidths])

    useEffect(() => {
        if (!alert) return undefined
        const timer = window.setTimeout(() => setAlert(null), 4500)
        return () => window.clearTimeout(timer)
    }, [alert])

    useEffect(() => {
        if (!postponeModal) return undefined
        const handlePointerDown = (event) => {
            if (
                postponePanelRef.current?.contains(event.target) ||
                postponeAnchorRef.current?.contains(event.target)
            ) {
                return
            }
            setPostponeModal(null)
        }
        document.addEventListener('mousedown', handlePointerDown)
        return () => document.removeEventListener('mousedown', handlePointerDown)
    }, [postponeModal])

    useEffect(() => {
        if (activeSheet !== 'schedule') {
            setActiveSheet('schedule')
        }
    }, [activeSheet, courses])

    const showError = (message) => {
        setAlert({ type: 'error', text: message })
    }

    const showSuccess = (message) => {
        setAlert({ type: 'success', text: message })
    }

    const requestJson = async (url, options = {}) => {
        const isFormData = options.body instanceof FormData
        const response = await fetch(url, {
            ...options,
            headers: isFormData
                ? (options.headers || {})
                : {
                    'Content-Type': 'application/json',
                    ...(options.headers || {})
                }
        })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
            const detail = data.detail
            throw new Error(typeof detail === 'string' ? detail : detail?.message || data.error || 'Помилка запиту')
        }
        return data
    }

    const loadAll = async () => {
        setLoading(true)
        try {
            const [settingsData, pendingData, workbookData, groupsData, runsData] = await Promise.all([
                requestJson(`${API_URL}/parents-report/settings`),
                requestJson(`${API_URL}/parents-report/pending`),
                requestJson(`${API_URL}/parents-report/workbook`),
                requestJson(`${API_URL}/groups/`),
                requestJson(`${API_URL}/parents-report/runs`)
            ])
            let nextPendingData = pendingData
            let nextWorkbookData = workbookData
            let nextRunsData = runsData
            if (!sourceSyncAttemptedRef.current && !(workbookData?.courses || []).length) {
                sourceSyncAttemptedRef.current = true
                try {
                    await requestJson(`${API_URL}/parents-report/sync-source`, {
                        method: 'POST',
                        body: JSON.stringify({})
                    })
                    const [syncedPending, syncedWorkbook, syncedRuns] = await Promise.all([
                        requestJson(`${API_URL}/parents-report/pending`),
                        requestJson(`${API_URL}/parents-report/workbook`),
                        requestJson(`${API_URL}/parents-report/runs`)
                    ])
                    nextPendingData = syncedPending
                    nextWorkbookData = syncedWorkbook
                    nextRunsData = syncedRuns
                } catch (syncError) {
                    showError(syncError.message || 'Не вдалося оновити базу звітів')
                }
            }
            setSettings(settingsData)
            setPending(nextPendingData.pending_lessons || [])
            setWorkbook(nextWorkbookData || { schedule: [], courses: [], sheet_names: [] })
            setGroups(groupsData || [])
            setRuns(nextRunsData || [])
            setAbsentsByLesson(Object.fromEntries((nextPendingData.pending_lessons || []).map(item => [item.id, ''])))
        } catch (error) {
            showError(error.message || 'Не вдалося завантажити звіти')
        } finally {
            setLoading(false)
        }
    }

    const refreshReports = async () => {
        const [pendingData, workbookData, runsData] = await Promise.all([
            requestJson(`${API_URL}/parents-report/pending`),
            requestJson(`${API_URL}/parents-report/workbook`),
            requestJson(`${API_URL}/parents-report/runs`)
        ])
        setPending(pendingData.pending_lessons || [])
        setWorkbook(workbookData || { schedule: [], courses: [], sheet_names: [] })
        setRuns(runsData || [])
    }

    const updateSetting = (key, value) => {
        setSettings(prev => ({ ...(prev || {}), [key]: value }))
    }

    const saveSettings = async () => {
        if (!settings) return
        setBusy('settings')
        try {
            const payload = {
                prompt_template: settings.prompt_template || '',
                auto_reports_enabled: !!settings.auto_reports_enabled,
                report_delay_minutes: Number(settings.report_delay_minutes ?? 0),
                report_notifications_enabled: !!settings.report_notifications_enabled,
                report_notification_delay_minutes: Number(settings.report_notification_delay_minutes ?? 0),
                default_duration_minutes: Number(settings.default_duration_minutes || 90),
                test_mode: !!settings.test_mode
            }
            const data = await requestJson(`${API_URL}/parents-report/settings`, {
                method: 'PUT',
                body: JSON.stringify(payload)
            })
            setSettings(data)
            showSuccess('Налаштування звітів збережено')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const resetPromptToDefault = async () => {
        if (!settings) return
        setBusy('reset-prompt')
        try {
            const data = await requestJson(`${API_URL}/parents-report/settings/reset-prompt`, {
                method: 'POST',
                body: JSON.stringify({})
            })
            setSettings(data)
            showSuccess('Інструкції промта повернуто до стандартних')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const syncReportSource = async () => {
        setBusy('sync-source')
        try {
            const result = await requestJson(`${API_URL}/parents-report/sync-source`, {
                method: 'POST',
                body: JSON.stringify({})
            })
            await refreshReports()
            setActiveTab('database')
            showSuccess(result.message || 'Базу звітів оновлено')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const importFromFile = async (file) => {
        if (!file) return
        setBusy('import-file')
        try {
            const formData = new FormData()
            formData.append('file', file)
            const result = await requestJson(`${API_URL}/parents-report/import-file`, {
                method: 'POST',
                body: formData
            })
            await loadAll()
            setActiveTab('database')
            showSuccess(`Імпортовано локальний розклад: ${result.imported_lessons} уроків`)
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
            if (fileInputRef.current) fileInputRef.current.value = ''
        }
    }

    const blobToBase64 = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => {
            const result = String(reader.result || '')
            resolve(result.includes(',') ? result.split(',')[1] : result)
        }
        reader.onerror = () => reject(reader.error || new Error('Не вдалося підготувати файл для збереження'))
        reader.readAsDataURL(blob)
    })

    const exportWorkbook = async () => {
        setBusy('export')
        try {
            const response = await fetch(`${API_URL}/parents-report/export`)
            if (!response.ok) {
                let message = `Помилка ${response.status}`
                try {
                    const data = await response.json()
                    message = data.detail || data.message || message
                } catch {
                    message = await response.text() || message
                }
                throw new Error(message)
            }

            const blob = await response.blob()
            const disposition = response.headers.get('content-disposition') || ''
            const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
            const plainMatch = disposition.match(/filename="?([^";]+)"?/i)
            const filename = encodedMatch
                ? decodeURIComponent(encodedMatch[1])
                : (plainMatch?.[1] || 'school_manager_schedule.xlsx')

            const desktopApi = window.pywebview?.api
            if (desktopApi?.save_file_dialog) {
                const base64Payload = await blobToBase64(blob)
                const saveResult = await desktopApi.save_file_dialog(filename, base64Payload)
                if (saveResult?.saved) {
                    showSuccess('Розклад збережено')
                } else if (!saveResult?.cancelled) {
                    throw new Error(saveResult?.error || 'Не вдалося зберегти розклад')
                }
                return
            }

            const url = URL.createObjectURL(blob)
            const link = document.createElement('a')
            link.href = url
            link.download = filename
            document.body.appendChild(link)
            link.click()
            link.remove()
            window.setTimeout(() => URL.revokeObjectURL(url), 1000)
            showSuccess('Розклад збережено')
        } catch (error) {
            showError(error.message || 'Не вдалося експортувати розклад')
        } finally {
            setBusy('')
        }
    }

    const patchLesson = async (lessonId, payload) => {
        setBusy(`lesson-${lessonId}`)
        try {
            const updated = await requestJson(`${API_URL}/parents-report/schedule/${lessonId}`, {
                method: 'PATCH',
                body: JSON.stringify(payload)
            })
            setWorkbook(prev => ({
                ...prev,
                schedule: (prev.schedule || []).map(item => item.id === lessonId ? updated : item)
            }))
            const pendingData = await requestJson(`${API_URL}/parents-report/pending`)
            setPending(pendingData.pending_lessons || [])
        } catch (error) {
            showError(error.message)
            await refreshReports()
        } finally {
            setBusy('')
        }
    }

    const addScheduleRow = async () => {
        setBusy('add-schedule')
        try {
            const row = await requestJson(`${API_URL}/parents-report/schedule`, { method: 'POST', body: JSON.stringify({}) })
            setWorkbook(prev => ({ ...prev, schedule: [...(prev.schedule || []), row] }))
            showSuccess('Рядок розкладу додано')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const deleteScheduleRow = async (lessonId) => {
        setBusy(`delete-schedule-${lessonId}`)
        try {
            await requestJson(`${API_URL}/parents-report/schedule/${lessonId}`, { method: 'DELETE' })
            setWorkbook(prev => ({
                ...prev,
                schedule: (prev.schedule || []).filter(item => item.id !== lessonId)
            }))
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const postponeLesson = async () => {
        if (!postponeModal?.lesson) return
        const lessonId = postponeModal.lesson.id
        setBusy(`postpone-${lessonId}`)
        try {
            await requestJson(`${API_URL}/parents-report/schedule/${lessonId}/postpone`, {
                method: 'POST',
                body: JSON.stringify({
                    date: postponeModal.date,
                    time: postponeModal.time
                })
            })
            setPostponeModal(null)
            await refreshReports()
            showSuccess('Урок перенесено')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const clearLessonPostpone = async (lessonId) => {
        setBusy(`clear-postpone-${lessonId}`)
        try {
            await requestJson(`${API_URL}/parents-report/schedule/${lessonId}/postpone`, { method: 'DELETE' })
            await refreshReports()
            showSuccess('Перенесення скасовано')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const addCourse = async () => {
        const name = newCourseName.trim()
        if (!name) return
        setBusy('add-course')
        try {
            const course = await requestJson(`${API_URL}/parents-report/courses`, {
                method: 'POST',
                body: JSON.stringify({ name })
            })
            setWorkbook(prev => ({ ...prev, courses: [...(prev.courses || []), course] }))
            setNewCourseName('')
            setActiveSheet(course.name)
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const patchCourse = async (courseId, payload) => {
        setBusy(`course-${courseId}`)
        try {
            const updated = await requestJson(`${API_URL}/parents-report/courses/${courseId}`, {
                method: 'PATCH',
                body: JSON.stringify(payload)
            })
            setWorkbook(prev => ({
                ...prev,
                courses: (prev.courses || []).map(item => item.id === courseId ? updated : item)
            }))
            setActiveSheet(updated.name)
            await refreshReports()
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const deleteCourse = async (courseId) => {
        setBusy(`delete-course-${courseId}`)
        try {
            await requestJson(`${API_URL}/parents-report/courses/${courseId}`, { method: 'DELETE' })
            await refreshReports()
            setActiveSheet('courses')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const addCourseLesson = async (course) => {
        setBusy(`add-course-lesson-${course.id}`)
        try {
            const lesson = await requestJson(`${API_URL}/parents-report/courses/${course.id}/lessons`, {
                method: 'POST',
                body: JSON.stringify({})
            })
            setWorkbook(prev => ({
                ...prev,
                courses: (prev.courses || []).map(item => item.id === course.id
                    ? { ...item, lessons: [...(item.lessons || []), lesson] }
                    : item)
            }))
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const patchCourseLesson = async (lessonId, payload) => {
        setBusy(`course-lesson-${lessonId}`)
        try {
            const updated = await requestJson(`${API_URL}/parents-report/course-lessons/${lessonId}`, {
                method: 'PATCH',
                body: JSON.stringify(payload)
            })
            setWorkbook(prev => ({
                ...prev,
                courses: (prev.courses || []).map(course => ({
                    ...course,
                    lessons: (course.lessons || []).map(item => item.id === lessonId ? updated : item)
                }))
            }))
            await refreshReports()
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const deleteCourseLesson = async (lessonId) => {
        setBusy(`delete-course-lesson-${lessonId}`)
        try {
            await requestJson(`${API_URL}/parents-report/course-lessons/${lessonId}`, { method: 'DELETE' })
            setWorkbook(prev => ({
                ...prev,
                courses: (prev.courses || []).map(course => ({
                    ...course,
                    lessons: (course.lessons || []).filter(item => item.id !== lessonId)
                }))
            }))
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const sendReport = async (lessonId) => {
        if (reportSendLockRef.current.size > 0) return
        reportSendLockRef.current.add(lessonId)
        setBusy(`send-${lessonId}`)
        try {
            const currentAbsents = absentsByLesson[lessonId] ?? ''
            await requestJson(`${API_URL}/parents-report/send`, {
                method: 'POST',
                body: JSON.stringify({
                    lesson_id: lessonId,
                    absents: currentAbsents,
                    test: settings?.test_mode
                })
            })
            await refreshReports()
            setAbsentsByLesson(prev => {
                const next = { ...prev }
                delete next[lessonId]
                return next
            })
            showSuccess('Звіт відправлено')
        } catch (error) {
            showError(error.message)
        } finally {
            reportSendLockRef.current.delete(lessonId)
            setBusy('')
        }
    }

    const runAutoNow = async () => {
        setBusy('run-auto')
        try {
            await requestJson(`${API_URL}/parents-report/auto/run-now`, { method: 'POST', body: JSON.stringify({}) })
            await refreshReports()
            showSuccess('Перевірку автозвітів виконано')
        } catch (error) {
            showError(error.message)
        } finally {
            setBusy('')
        }
    }

    const formatDateTime = (value) => {
        if (!value) return ''
        const date = new Date(value)
        if (Number.isNaN(date.getTime())) return value
        return date.toLocaleString('uk-UA', {
            day: '2-digit',
            month: '2-digit',
            hour: '2-digit',
            minute: '2-digit'
        })
    }

    const formatFullDateTime = (value) => {
        if (!value) return ''
        const date = new Date(value)
        if (Number.isNaN(date.getTime())) return value
        return date.toLocaleString('uk-UA', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        })
    }

    const formatDateOnly = (value) => {
        if (!value) return ''
        const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/)
        const date = match
            ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
            : new Date(value)
        if (Number.isNaN(date.getTime())) return value
        return date.toLocaleDateString('uk-UA', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric'
        })
    }

    const toInputDate = (date) => {
        const year = date.getFullYear()
        const month = String(date.getMonth() + 1).padStart(2, '0')
        const day = String(date.getDate()).padStart(2, '0')
        return `${year}-${month}-${day}`
    }

    const addDaysToDateString = (value, days) => {
        const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/)
        const date = match
            ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
            : new Date()
        date.setDate(date.getDate() + days)
        return toInputDate(date)
    }

    const normalizeInputTime = (value) => {
        const match = String(value || '').match(/^(\d{1,2}):(\d{2})/)
        if (!match) return '18:00'
        const hour = String(Math.max(0, Math.min(23, Number(match[1])))).padStart(2, '0')
        return `${hour}:${match[2]}`
    }

    const openPostponeModal = (lesson, anchorElement) => {
        postponeAnchorRef.current = anchorElement || null
        setPostponeModal({
            lesson,
            date: addDaysToDateString(lesson.lesson_run_date, 7),
            time: normalizeInputTime(lesson.start_time || '18:00')
        })
    }

    const openNativePicker = (inputRef) => {
        const input = inputRef.current
        if (!input) return
        try {
            if (typeof input.showPicker === 'function') {
                input.showPicker()
                return
            }
        } catch {
            // Some WebView builds expose showPicker but block it for specific input types.
        }
        input.focus()
        input.click()
    }

    const getSendBlockedReason = (lesson, isSending) => {
        if (isSending) return 'Звіт генерується і відправляється'
        if (busy) return 'Зачекайте, виконується інша дія'
        if (!lesson.mapping_ready) return 'Спочатку виберіть Telegram-групу в базі даних'
        if (!settings?.google_ai_api_key_set) return 'Додайте Google AI API key в основних налаштуваннях'
        return ''
    }

    const getTableWidth = (columns) => columns.reduce((sum, column) => sum + (columnWidths[column.id] || column.width), 0)

    const toggleScheduleSort = (key) => {
        setScheduleSort(prev => ({
            key,
            direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
        }))
    }

    const startColumnResize = (event, column) => {
        event.preventDefault()
        event.stopPropagation()
        const startX = event.clientX
        const startWidth = columnWidths[column.id] || column.width
        const minWidth = column.minWidth || 72

        const handleMove = (moveEvent) => {
            const delta = moveEvent.clientX - startX
            const nextWidth = Math.max(minWidth, Math.round(startWidth + delta))
            setColumnWidths(prev => ({ ...prev, [column.id]: nextWidth }))
        }

        const handleUp = () => {
            window.removeEventListener('pointermove', handleMove)
            window.removeEventListener('pointerup', handleUp)
            window.removeEventListener('pointercancel', handleUp)
            document.body.classList.remove('is-resizing-table-column')
        }

        document.body.classList.add('is-resizing-table-column')
        window.addEventListener('pointermove', handleMove)
        window.addEventListener('pointerup', handleUp, { once: true })
        window.addEventListener('pointercancel', handleUp, { once: true })
    }

    const renderHeaderCell = (column) => {
        const isSorted = scheduleSort.key === column.sortKey
        return (
            <th key={column.id}>
                <div className="parents-th-content">
                    {column.sortKey ? (
                        <button
                            type="button"
                            className={`parents-sort-btn ${isSorted ? 'active' : ''}`}
                            onClick={() => toggleScheduleSort(column.sortKey)}
                            title={`Сортувати: ${column.label}`}
                        >
                            <span>{column.label}</span>
                            <span className="parents-sort-mark">{isSorted ? (scheduleSort.direction === 'asc' ? '↑' : '↓') : ''}</span>
                        </button>
                    ) : (
                        <span className="parents-th-label">{column.label}</span>
                    )}
                    <span
                        className="parents-col-resizer"
                        onPointerDown={(event) => startColumnResize(event, column)}
                        title="Змінити ширину колонки"
                    />
                </div>
            </th>
        )
    }

    const renderDeleteButton = (onClick, disabled = false) => (
        <button
            type="button"
            className="btn btn-danger btn-sm parents-delete-button"
            onClick={onClick}
            disabled={disabled}
            title="Видалити"
            aria-label="Видалити"
        >
            <TrashIcon />
        </button>
    )

    const renderPostponeBadge = (lesson) => {
        if (!lesson?.is_postponed) return null
        return (
            <div className="parents-postpone-badge">
                <span>Перенесено до {formatFullDateTime(lesson.postponed_start_at)}</span>
                <button
                    type="button"
                    className="parents-postpone-cancel"
                    onClick={() => clearLessonPostpone(lesson.id)}
                    disabled={!!busy}
                    title="Скасувати перенесення"
                    aria-label="Скасувати перенесення"
                >
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                        <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
                    </svg>
                </button>
            </div>
        )
    }

    const renderReadOnlyScheduleCell = (lesson, column) => {
        if (column.id === 'group') {
            return (
                <div className="parents-readonly-group">
                    <strong>{lesson.group_name || '-'}</strong>
                    {renderPostponeBadge(lesson)}
                    <span>{lesson.telegram_group_name || 'TG не вибрано'}</span>
                </div>
            )
        }
        if (column.id === 'day') return lesson.day || '-'
        if (column.id === 'time') return lesson.start_time || '-'
        if (column.id === 'course') return lesson.course || '-'
        if (column.id === 'lesson_code') return lesson.lesson_code || '-'
        if (column.id === 'lesson_count') return lesson.lesson_count || '-'
        if (column.id === 'report_date') return lesson.last_report_date || '-'
        if (column.id === 'absents') return lesson.absents || '-'
        if (column.id === 'lesson_title') return lesson.lesson_title || lesson.topic || '-'
        if (column.id === 'duration') return `${lesson.duration_minutes || 90} хв`
        return ''
    }

    const renderReadonlyScheduleTable = () => (
        <div className="parents-grid-wrap">
            <table className="table parents-table parents-edit-table parents-readonly-table" style={{ width: getTableWidth(READONLY_SCHEDULE_COLUMNS) }}>
                <colgroup>
                    {READONLY_SCHEDULE_COLUMNS.map(column => (
                        <col key={column.id} style={{ width: columnWidths[column.id] || column.width }} />
                    ))}
                </colgroup>
                <thead>
                    <tr>{READONLY_SCHEDULE_COLUMNS.map(renderHeaderCell)}</tr>
                </thead>
                <tbody>
                    {sortedLessons.length === 0 ? (
                        <tr>
                            <td colSpan={READONLY_SCHEDULE_COLUMNS.length}>Розклад поки порожній. Імпортуй XLSX у вкладці “База даних”.</td>
                        </tr>
                    ) : sortedLessons.map(lesson => (
                        <tr key={lesson.id}>
                            {READONLY_SCHEDULE_COLUMNS.map(column => (
                                <td key={column.id}>{renderReadOnlyScheduleCell(lesson, column)}</td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )

    const renderScheduleTable = () => (
        <div className="parents-grid-wrap">
            <table className="table parents-table parents-edit-table" style={{ width: getTableWidth(SCHEDULE_COLUMNS) }}>
                <colgroup>
                    {SCHEDULE_COLUMNS.map(column => (
                        <col key={column.id} style={{ width: columnWidths[column.id] || column.width }} />
                    ))}
                </colgroup>
                <thead>
                    <tr>{SCHEDULE_COLUMNS.map(renderHeaderCell)}</tr>
                </thead>
                <tbody>
                    {sortedLessons.map(lesson => {
                        const courseOptions = courses.some(course => course.name === lesson.course)
                            ? courses
                            : [...courses, { id: `current-${lesson.id}`, name: lesson.course }]
                        return (
                            <tr key={lesson.id}>
                                <td className="parents-group-td">
                                    <GroupMappingCell
                                        lesson={lesson}
                                        groups={groups}
                                        onSelect={(group) => patchLesson(lesson.id, { telegram_group_id: group.id })}
                                    />
                                    {renderPostponeBadge(lesson)}
                                </td>
                                <td>
                                    <select
                                        className="parents-cell-input"
                                        value={lesson.day || 'ПН'}
                                        onChange={(event) => patchLesson(lesson.id, { day: event.target.value })}
                                    >
                                        {DAYS.map(day => <option key={day} value={day}>{day}</option>)}
                                    </select>
                                </td>
                                <td>
                                    <EditableText value={lesson.start_time} onSave={(value) => patchLesson(lesson.id, { start_time: value })} />
                                </td>
                                <td>
                                    <select
                                        className="parents-cell-input parents-course-select"
                                        value={lesson.course || ''}
                                        onChange={(event) => patchLesson(lesson.id, { course: event.target.value })}
                                    >
                                        <option value="">Курс не вибрано</option>
                                        {courseOptions.filter(course => course.name).map(course => (
                                            <option key={course.id || course.name} value={course.name}>{course.name}</option>
                                        ))}
                                    </select>
                                </td>
                                <td>
                                    <EditableText value={lesson.lesson_code} onSave={(value) => patchLesson(lesson.id, { lesson_code: value })} />
                                </td>
                                <td>
                                    <EditableText value={lesson.lesson_count} onSave={(value) => patchLesson(lesson.id, { lesson_count: value })} />
                                </td>
                                <td>
                                    <EditableText value={lesson.last_report_date} onSave={(value) => patchLesson(lesson.id, { last_report_date: value })} placeholder="DD-MM-YYYY" />
                                </td>
                                <td>
                                    <EditableText value={lesson.absents} onSave={(value) => patchLesson(lesson.id, { absents: value })} />
                                </td>
                                <td>
                                    <EditableText value={lesson.lesson_title} onSave={(value) => patchLesson(lesson.id, { lesson_title: value, topic: value })} />
                                </td>
                                <td>
                                    <EditableText type="number" value={lesson.duration_minutes} onSave={(value) => patchLesson(lesson.id, { duration_minutes: Number(value || 90) })} />
                                </td>
                                <td className="parents-actions-cell">
                                    {renderDeleteButton(() => deleteScheduleRow(lesson.id), !!busy)}
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )

    const renderCoursesSheet = () => (
        <div className="parents-course-manager">
            <div className="parents-add-row">
                <input
                    className="form-input"
                    value={newCourseName}
                    onChange={(event) => setNewCourseName(event.target.value)}
                    placeholder="Нова назва курсу"
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') addCourse()
                    }}
                />
                <button type="button" className="btn btn-primary" onClick={addCourse} disabled={busy === 'add-course'}>
                    Додати курс
                </button>
            </div>
            <div className="parents-course-list">
                {courses.map(course => (
                    <div key={course.id} className="parents-course-row">
                        <EditableText value={course.name} onSave={(value) => patchCourse(course.id, { name: value })} />
                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setActiveSheet(course.name)}>
                            Уроки
                        </button>
                        {renderDeleteButton(() => deleteCourse(course.id), !!busy)}
                    </div>
                ))}
            </div>
        </div>
    )

    const renderCourseLessonSheet = (course) => (
        <div className="parents-grid-wrap">
            <div className="parents-sheet-heading">
                <div>
                    <h3>{course.name}</h3>
                    <p className="parents-muted">Теми й тексти звітів цього курсу використовуються для автозаповнення розкладу і prompt Gemini.</p>
                </div>
                <button type="button" className="btn btn-primary btn-sm" onClick={() => addCourseLesson(course)} disabled={!!busy}>
                    + Урок
                </button>
            </div>
            <table className="table parents-table parents-edit-table">
                <thead>
                    <tr>
                        <th>№</th>
                        <th>Номер уроку</th>
                        <th>Модуль</th>
                        <th>Тема уроку</th>
                        <th>Звіт</th>
                        <th>Примітки</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {(course.lessons || []).map(item => (
                        <tr key={item.id}>
                            <td>
                                <EditableText type="number" value={item.lesson_count} onSave={(value) => patchCourseLesson(item.id, { lesson_count: Number(value || 0) })} />
                            </td>
                            <td>
                                <EditableText value={item.lesson_code} onSave={(value) => patchCourseLesson(item.id, { lesson_code: value })} />
                            </td>
                            <td>
                                <EditableText value={item.module} onSave={(value) => patchCourseLesson(item.id, { module: value })} />
                            </td>
                            <td>
                                <EditableText value={item.lesson_title} onSave={(value) => patchCourseLesson(item.id, { lesson_title: value })} />
                            </td>
                            <td>
                                <EditableText multiline value={item.lesson_report_text} onSave={(value) => patchCourseLesson(item.id, { lesson_report_text: value })} />
                            </td>
                            <td>
                                <EditableText multiline value={item.notes} onSave={(value) => patchCourseLesson(item.id, { notes: value })} />
                            </td>
                            <td className="parents-actions-cell">
                                {renderDeleteButton(() => deleteCourseLesson(item.id), !!busy)}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )

    if (loading && !settings) {
        return (
            <div className="page parents-report-page">
                <div className="loader"><div className="spinner"></div></div>
            </div>
        )
    }

    return (
        <div className="page parents-report-page">
            <div className="page-header parents-report-header">
                <div>
                    <h2>Звіт батькам</h2>
                </div>
                <button type="button" className="btn btn-secondary" onClick={loadAll} disabled={!!busy}>
                    Оновити
                </button>
            </div>

            {alert && (
                <div className={`alert ${alert.type === 'success' ? 'alert-success' : 'alert-error'}`}>
                    <span>{alert.text}</span>
                </div>
            )}

            <div className="parents-report-summary">
                <div className="card parents-stat parents-stat-primary">
                    <div className="parents-stat-icon" aria-hidden="true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                            <polyline points="14 2 14 8 20 8"></polyline>
                            <line x1="8" y1="13" x2="16" y2="13"></line>
                            <line x1="8" y1="17" x2="13" y2="17"></line>
                        </svg>
                    </div>
                    <div>
                        <span>Потребують звіт</span>
                        <strong>{pending.length}</strong>
                    </div>
                </div>
                <div className="card parents-stat parents-stat-success">
                    <div className="parents-stat-icon" aria-hidden="true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                            <polyline points="22 4 12 14.01 9 11.01"></polyline>
                        </svg>
                    </div>
                    <div>
                        <span>Готові до відправки</span>
                        <strong>{readyPendingCount}</strong>
                    </div>
                </div>
                <div className="card parents-stat parents-stat-secondary">
                    <div className="parents-stat-icon" aria-hidden="true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <rect x="3" y="4" width="18" height="18" rx="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                    </div>
                    <div>
                        <span>Уроків у розкладі</span>
                        <strong>{lessons.length}</strong>
                    </div>
                </div>
                <div className="card parents-stat parents-stat-accent">
                    <div className="parents-stat-icon" aria-hidden="true">
                        <svg xmlns="http://www.w3.org/2000/svg" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M21 15a4 4 0 0 1-4 4H7l-4 4V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"></path>
                            <path d="m9 11 2 2 4-4"></path>
                        </svg>
                    </div>
                    <div>
                        <span>TG прив'язано</span>
                        <strong>{mappedCount}/{lessons.length}</strong>
                    </div>
                </div>
            </div>

            <div className="parents-tabs" role="tablist" aria-label="Розділи звітів">
                {TABS.map(tab => (
                    <button
                        key={tab.id}
                        type="button"
                        className={`parents-tab ${activeTab === tab.id ? 'active' : ''}`}
                        onClick={() => setActiveTab(tab.id)}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab === 'pending' && (
                <section className="card parents-panel">
                    <div className="card-header">
                        <div>
                            <h3 className="card-title">Уроки які потребують звіт</h3>
                            <p className="parents-muted">
                                Готові для ручної відправки одразу після завершення уроку.
                            </p>
                        </div>
                        <button type="button" className="btn btn-secondary btn-sm" onClick={runAutoNow} disabled={busy === 'run-auto'}>
                            Перевірити авто
                        </button>
                    </div>

                    {pending.length === 0 ? (
                        <div className="parents-empty">Немає уроків, які потребують звіт.</div>
                    ) : (
                        <div className="parents-pending-list">
                            {pending.map(lesson => {
                                const isSending = busy === `send-${lesson.id}`
                                const sendBlockedReason = getSendBlockedReason(lesson, isSending)
                                return (
                                    <article key={lesson.id} className="parents-report-item">
                                        <div className="parents-report-main">
                                            <div className="parents-report-title-row">
                                                <div>
                                                    <h3>{lesson.group_name}</h3>
                                                    <p>
                                                        {lesson.course || 'Курс не вказано'} · завершився о {lesson.end_time || '-'} · {lesson.lesson_date}
                                                    </p>
                                                    <p className="parents-lesson-topic">
                                                        урок {lesson.lesson_code || lesson.lesson_count || '-'}
                                                        {lesson.lesson_title ? ` (${lesson.lesson_title})` : ''}
                                                    </p>
                                                    {lesson.is_postponed && (
                                                        <p className="parents-postponed-note">
                                                            Перенесений урок
                                                            {lesson.postponed_from_date ? ` з ${formatDateOnly(lesson.postponed_from_date)}` : ''}
                                                        </p>
                                                    )}
                                                </div>
                                                <div className={`parents-map-badge ${lesson.mapping_ready ? 'ready' : 'missing'}`}>
                                                    {lesson.mapping_ready ? lesson.telegram_group_name : 'Немає TG групи'}
                                                </div>
                                            </div>

                                            <div className="parents-send-row">
                                                <input
                                                    className="form-input"
                                                    value={absentsByLesson[lesson.id] ?? ''}
                                                    onChange={(event) => setAbsentsByLesson(prev => ({ ...prev, [lesson.id]: event.target.value }))}
                                                    placeholder="Відсутні (через кому)"
                                                />
                                                <button
                                                    type="button"
                                                    className={`btn btn-primary parents-send-button ${isSending ? 'is-loading' : ''}`}
                                                    onClick={() => sendReport(lesson.id)}
                                                    disabled={!!sendBlockedReason}
                                                    title={sendBlockedReason || 'Згенерувати звіт через Gemini і відправити в Telegram'}
                                                >
                                                    {isSending ? 'В процесі...' : (
                                                        <>
                                                            <TelegramSendIcon />
                                                            <span>Відправити</span>
                                                        </>
                                                    )}
                                                </button>
                                                <button
                                                    type="button"
                                                    className="btn btn-secondary parents-postpone-button"
                                                    onClick={(event) => openPostponeModal(lesson, event.currentTarget)}
                                                    disabled={!!busy || isSending}
                                                    title="Перенести урок на іншу дату"
                                                >
                                                    <PostponeIcon />
                                                    <span>Перенести</span>
                                                </button>
                                            </div>
                                        </div>
                                    </article>
                                )
                            })}
                        </div>
                    )}
                </section>
            )}

            {activeTab === 'schedule' && (
                <section className="card parents-panel">
                    <div className="card-header">
                        <div>
                            <h3 className="card-title">Локальний розклад</h3>
                        </div>
                    </div>
                    {renderReadonlyScheduleTable()}
                </section>
            )}

            {activeTab === 'database' && (
                <section className="card parents-panel">
                    <div className="card-header parents-db-header">
                        <div className="parents-db-title-row">
                            <h3 className="card-title">Локальна база</h3>
                            <button type="button" className="btn btn-primary btn-sm" onClick={addScheduleRow} disabled={!!busy}>
                                Додати групу
                            </button>
                        </div>
                        <div className="parents-workbook-toolbar">
                            <input
                                ref={fileInputRef}
                                type="file"
                                accept=".xlsx"
                                hidden
                                onChange={(event) => importFromFile(event.target.files?.[0])}
                            />
                            <button type="button" className="btn btn-secondary btn-sm" onClick={() => fileInputRef.current?.click()} disabled={!!busy}>
                                {busy === 'import-file' ? 'Імпортую...' : 'Імпорт XLSX'}
                            </button>
                            <button type="button" className="btn btn-secondary btn-sm" onClick={syncReportSource} disabled={!!busy}>
                                {busy === 'sync-source' ? 'Оновлюю...' : 'Оновити базу звітів'}
                            </button>
                            <button type="button" className="btn btn-primary btn-sm" onClick={exportWorkbook} disabled={!!busy}>
                                {busy === 'export' ? 'Експортую...' : 'Експорт розкладу'}
                            </button>
                        </div>
                    </div>

                    {renderScheduleTable()}

                </section>
            )}

            {activeTab === 'settings' && (
                <section className="card parents-panel">
                    <div className="card-header">
                        <div>
                            <h3 className="card-title">Налаштування звітів</h3>
                        </div>
                    </div>

                    <div className="parents-settings-grid">
                        <div className="parents-setting-pair parents-wide">
                            <label className="form-group">
                                <span className="form-label">Затримка автозвіту, хв</span>
                                <NumberStepper
                                    value={settings?.report_delay_minutes ?? 0}
                                    onChange={(value) => updateSetting('report_delay_minutes', value)}
                                    min={0}
                                    max={240}
                                    ariaLabel="Затримка автозвіту, хв"
                                />
                            </label>

                            <label className="form-group" title="Після завершення уроку і заданої затримки звіт відправиться сам, але без напису про відсутніх">
                                <span className="form-label">Автоматичні звіти</span>
                                <span className="parents-inline-toggle">
                                    <input
                                        type="checkbox"
                                        checked={!!settings?.auto_reports_enabled}
                                        onChange={(event) => updateSetting('auto_reports_enabled', event.target.checked)}
                                    />
                                    <span className="parents-inline-toggle-track">
                                        <span className="parents-inline-toggle-thumb" />
                                    </span>
                                    <span className="parents-inline-toggle-state">
                                        {settings?.auto_reports_enabled ? 'Увімкнено' : 'Вимкнено'}
                                    </span>
                                </span>
                            </label>
                        </div>

                        <div className="parents-setting-pair parents-wide">
                            <label className="form-group">
                                <span className="form-label">Затримка сповіщення, хв</span>
                                <NumberStepper
                                    value={settings?.report_notification_delay_minutes ?? 0}
                                    onChange={(value) => updateSetting('report_notification_delay_minutes', value)}
                                    min={0}
                                    max={240}
                                    ariaLabel="Затримка сповіщення, хв"
                                />
                            </label>

                            <label className="form-group" title="Показувати системне повідомлення, коли урок уже потребує звіт.">
                                <span className="form-label">Системні сповіщення</span>
                                <span className="parents-inline-toggle">
                                    <input
                                        type="checkbox"
                                        checked={!!settings?.report_notifications_enabled}
                                        onChange={(event) => updateSetting('report_notifications_enabled', event.target.checked)}
                                    />
                                    <span className="parents-inline-toggle-track">
                                        <span className="parents-inline-toggle-thumb" />
                                    </span>
                                    <span className="parents-inline-toggle-state">
                                        {settings?.report_notifications_enabled ? 'Увімкнено' : 'Вимкнено'}
                                    </span>
                                </span>
                            </label>
                        </div>

                        <label className="form-group">
                            <span className="form-label">Тривалість уроку за замовчуванням, хв</span>
                            <NumberStepper
                                value={settings?.default_duration_minutes ?? 90}
                                onChange={(value) => updateSetting('default_duration_minutes', value)}
                                min={30}
                                max={360}
                                ariaLabel="Тривалість уроку за замовчуванням, хв"
                            />
                        </label>

                        <label className="form-group" title="Тестова відправка додає позначку ТЕСТ, не оновлює дату звіту і не переводить урок на наступний. Автозвіти в цьому режимі не запускаються.">
                            <span className="form-label">Тестовий режим</span>
                            <span className="parents-inline-toggle">
                                <input
                                    type="checkbox"
                                    checked={!!settings?.test_mode}
                                    onChange={(event) => updateSetting('test_mode', event.target.checked)}
                                />
                                <span className="parents-inline-toggle-track">
                                    <span className="parents-inline-toggle-thumb" />
                                </span>
                                <span className="parents-inline-toggle-state">
                                    {settings?.test_mode ? 'Увімкнено' : 'Вимкнено'}
                                </span>
                            </span>
                        </label>

                        <label className="form-group parents-wide">
                            <span className="form-label">Prompt для Google AI</span>
                            <textarea
                                className="form-textarea parents-prompt"
                                value={settings?.prompt_template || ''}
                                onChange={(event) => updateSetting('prompt_template', event.target.value)}
                                rows={12}
                            />
                        </label>
                    </div>

                    <div className="parents-actions">
                        <button type="button" className="btn btn-secondary" onClick={resetPromptToDefault} disabled={!!busy} title="При натисканні ви повернете інструкції промта до стандартних">
                            {busy === 'reset-prompt' ? 'Повертаю...' : 'Повернути'}
                        </button>
                        <button type="button" className="btn btn-primary" onClick={saveSettings} disabled={!!busy}>
                            {busy === 'settings' ? 'Зберігаю...' : 'Зберегти'}
                        </button>
                    </div>
                </section>
            )}

            {activeTab === 'runs' && (
                <section className="card parents-panel">
                    <div className="card-header">
                        <div>
                            <h3 className="card-title">Журнал звітів</h3>
                            <p className="parents-muted">Останні генерації та відправки звітів.</p>
                        </div>
                    </div>
                    <div className="parents-runs-list">
                        {runs.length === 0 ? (
                            <div className="parents-empty">Журнал звітів порожній.</div>
                        ) : runs.map(run => (
                            <div key={run.id} className="parents-run-row">
                                <div className={`parents-run-status ${run.status === 'success' ? 'success' : 'error'}`}>
                                    {run.status === 'success' ? 'OK' : 'ERR'}
                                </div>
                                <div>
                                    <strong>{run.lesson_group_name}</strong>
                                    <span>
                                        {formatDateTime(run.created_at)}
                                        {run.is_auto ? ' · авто' : ' · вручну'}
                                        {run.is_test ? ' · тест' : ''}
                                        {run.telegram_group_name ? ` · ${run.telegram_group_name}` : ''}
                                    </span>
                                    {run.error && <p>{run.error}</p>}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {postponeModal && (
                <FloatingPanel
                    open
                    anchorRef={postponeAnchorRef}
                    panelRef={postponePanelRef}
                    className="parents-postpone-popover"
                    align="right"
                    width={368}
                    maxHeight={520}
                    zIndex={12000}
                >
                        <div className="parents-postpone-popover-header">
                            <div>
                                <h3 className="modal-title">Перенести урок</h3>
                                <p className="parents-muted">Виберіть нову дату і час початку перенесеного уроку.</p>
                            </div>
                            <button
                                type="button"
                                className="modal-close"
                                onClick={() => setPostponeModal(null)}
                                aria-label="Закрити"
                            >
                                ×
                            </button>
                        </div>

                        <div className="parents-postpone-summary">
                            <strong>{postponeModal.lesson.group_name}</strong>
                            <span>
                                {[postponeModal.lesson.course, postponeModal.lesson.lesson_code || postponeModal.lesson.lesson_count]
                                    .filter(Boolean)
                                    .join(' · ')}
                            </span>
                            <span>
                                Поточна дата уроку: {formatDateOnly(postponeModal.lesson.lesson_run_date)}
                            </span>
                        </div>

                        <div className="parents-postpone-fields">
                            <label className="form-group">
                                <span className="form-label">Дата</span>
                                <span className="parents-date-input">
                                    <input
                                        ref={postponeDateInputRef}
                                        className="form-input"
                                        type="date"
                                        value={postponeModal.date}
                                        onChange={(event) => setPostponeModal(prev => ({ ...prev, date: event.target.value }))}
                                    />
                                    <button
                                        type="button"
                                        className="parents-date-picker-button"
                                        onClick={() => openNativePicker(postponeDateInputRef)}
                                        aria-label="Відкрити календар"
                                    >
                                        <svg viewBox="0 0 24 24" aria-hidden="true">
                                            <rect x="3.5" y="5" width="17" height="15.5" rx="2.5" />
                                            <path d="M7.5 3.5v4M16.5 3.5v4M3.5 10h17" />
                                            <path d="M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01" />
                                        </svg>
                                    </button>
                                </span>
                            </label>
                            <label className="form-group">
                                <span className="form-label">Час</span>
                                <span className="parents-date-input">
                                    <input
                                        ref={postponeTimeInputRef}
                                        className="form-input"
                                        type="time"
                                        value={postponeModal.time}
                                        onChange={(event) => setPostponeModal(prev => ({ ...prev, time: event.target.value }))}
                                    />
                                    <button
                                        type="button"
                                        className="parents-date-picker-button"
                                        onClick={() => openNativePicker(postponeTimeInputRef)}
                                        aria-label="Відкрити вибір часу"
                                    >
                                        <svg viewBox="0 0 24 24" aria-hidden="true">
                                            <circle cx="12" cy="12" r="8.5" />
                                            <path d="M12 7.5V12l3.25 2" />
                                        </svg>
                                    </button>
                                </span>
                            </label>
                        </div>

                        <div className="modal-actions">
                            <button type="button" className="btn btn-secondary" onClick={() => setPostponeModal(null)} disabled={!!busy}>
                                Скасувати
                            </button>
                            <button type="button" className="btn btn-primary" onClick={postponeLesson} disabled={!!busy || !postponeModal.date || !postponeModal.time}>
                                {busy === `postpone-${postponeModal.lesson.id}` ? 'Переношу...' : 'Перенести'}
                            </button>
                        </div>
                </FloatingPanel>
            )}
        </div>
    )
}

export default ParentsReport

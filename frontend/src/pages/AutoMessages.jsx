import { useState, useEffect, useRef } from 'react'
import FilePreviewChip from '../components/FilePreviewChip'
import FloatingPanel from '../components/FloatingPanel'
import MessageComposer from '../components/MessageComposer'
import StickerPreview from '../components/StickerPreview'
import { useToast } from '../components/ToastProvider'
import { AppSelect, NumberStepper, TimePicker } from '../components/FormControls'
import { useApi } from '../hooks/useApi'
import { useClipboardFiles } from '../hooks/useClipboardFiles'
import { useDragDropFiles } from '../hooks/useDragDropFiles'
import { getSearchVariations } from '../utils/search'
import { getFileName, getFileType, isServerFile, stickerKey, toServerFile } from '../utils/fileInputs'

const DAYS = [
    { value: 'daily', label: 'щоденно' },
    { value: 'mon', label: 'понеділок' },
    { value: 'tue', label: 'вівторок' },
    { value: 'wed', label: 'середа' },
    { value: 'thu', label: 'четвер' },
    { value: 'fri', label: "п'ятниця" },
    { value: 'sat', label: 'субота' },
    { value: 'sun', label: 'неділя' }
]

const DEFAULT_ABSENT_FOLLOWUP_TEMPLATE = `Вітаю, шановні батьки!😊

👋Чекаємо на урок наших розумників у {next_lesson_day} о {next_lesson_time_dot} ⏰ за графіком !!

❗️На відпрацювання об {makeup_time}🔔 {absents}!

✅Прошу поставте ➕ або лайк 👍, що ознайомились та будете на уроці👩‍💻

✅ Прохання попереджати, якщо когось з дітей не буде😊

Всім гарних вихідних 🍰☕️`

const DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE = `Вітаю, шановні батьки!😊

👋Чекаємо на урок наших розумників завтра у {next_lesson_day} о {next_lesson_time_dot} ⏰ за графіком !!

🇺🇦 Одягайте вишиванку або білу футболку - буде тематичний урок.

✅Прошу поставте ➕ або лайк 👍, що ознайомились та будете  на  уроці👩‍💻

✅ Прохання попереджати, якщо когось з дітей не буде😊

Всім гарних вихідних  🦋`

const FOLLOWUP_PLACEHOLDERS = [
    { token: '{absents}', label: 'Відсутні' },
    { token: '{makeup_time}', label: 'Час відпрацювання' },
    { token: '{next_lesson_day}', label: 'День наступного уроку' },
    { token: '{next_lesson_time_dot}', label: 'Час наступного уроку' },
    { token: '{group}', label: 'Група' },
    { token: '{course}', label: 'Курс' },
    { token: '{lesson_code}', label: 'Урок' }
]

const FOLLOWUP_TEMPLATE_CARDS = [
    {
        key: 'absent_followup_template',
        title: 'Якщо є відсутні',
        description: 'Повідомлення з часом відпрацювання та іменами відсутніх.',
        defaultTemplate: DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
    },
    {
        key: 'no_absents_followup_template',
        title: 'Якщо відсутніх немає',
        description: 'Звичайне нагадування батькам про наступний урок.',
        defaultTemplate: DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
    }
]

const followupPreview = (value) => {
    const firstLine = String(value || '').split(/\r?\n/).map(line => line.trim()).find(Boolean)
    return firstLine || 'Шаблон порожній'
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

function AutoMessages() {
    const [autoMessages, setAutoMessages] = useState([])
    const [groups, setGroups] = useState([])
    const [loading, setLoading] = useState(false)
    const [showForm, setShowForm] = useState(false)
    const { showToast } = useToast()
    const setAlert = showToast
    const apiClient = useApi()
    const [templates, setTemplates] = useState([])
    const [formFiles, setFormFiles] = useState([])
    const [selectedStickers, setSelectedStickers] = useState([])
    const [isSaving, setIsSaving] = useState(false)
    const [followupSettings, setFollowupSettings] = useState(null)
    const [isSavingFollowupSettings, setIsSavingFollowupSettings] = useState(false)
    const [activeFollowupTemplate, setActiveFollowupTemplate] = useState(null)
    const [editingId, setEditingId] = useState(null)
    const [editDraft, setEditDraft] = useState(null)
    const textareaRef = useRef(null)
    const followupEditorRefs = useRef({})
    const fileInputRef = useRef(null)
    const dropZoneRef = useRef(null)
    const groupPickerRef = useRef(null)
    const groupPickerControlRef = useRef(null)
    const groupPickerDropdownRef = useRef(null)
    const savingRef = useRef(false)
    const [groupSearchQuery, setGroupSearchQuery] = useState('')
    const [isGroupPickerOpen, setIsGroupPickerOpen] = useState(false)

    const [formData, setFormData] = useState({
        group_id: '',
        message: '',
        send_time: '18:00',
        send_day: 'mon',
        repeat_count: 1
    })

    useEffect(() => {
        fetchData()
        fetchTemplates()
        fetchFollowupSettings()
    }, [])

    useEffect(() => {
        const handlePointerDown = (event) => {
            const insidePicker = groupPickerRef.current && groupPickerRef.current.contains(event.target)
            const insideDropdown = groupPickerDropdownRef.current && groupPickerDropdownRef.current.contains(event.target)
            if (!insidePicker && !insideDropdown) {
                setIsGroupPickerOpen(false)
            }
        }

        document.addEventListener('mousedown', handlePointerDown)
        return () => document.removeEventListener('mousedown', handlePointerDown)
    }, [])

    const fetchData = async () => {
        setLoading(true)
        try {
            const [autoMessagesData, groupsData] = await Promise.all([
                apiClient.get('/auto-messages/', { toast: false }),
                apiClient.get('/groups/', { toast: false })
            ])
            setAutoMessages(autoMessagesData)
            setGroups(groupsData)
        } catch (error) {
            setAlert({ type: 'error', text: '\u041f\u043e\u043c\u0438\u043b\u043a\u0430 \u0437\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0435\u043d\u043d\u044f \u0430\u0432\u0442\u043e\u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u044c' })
        }
        setLoading(false)
    }

    const fetchTemplates = async () => {
        try {
            const data = await apiClient.get('/templates/', { toast: false })
            setTemplates(data)
        } catch (error) {
            console.error('Templates loading error:', error)
        }
    }

    const fetchFollowupSettings = async () => {
        try {
            const data = await apiClient.get('/parents-report/settings', { toast: false })
            setFollowupSettings(data)
        } catch (error) {
            console.error('Follow-up settings loading error:', error)
        }
    }

    const resetForm = () => {
        setFormData({
            group_id: '',
            message: '',
            send_time: '18:00',
            send_day: 'mon',
            repeat_count: 1
        })
        setFormFiles([])
        setSelectedStickers([])
        setIsDragging(false)
        setGroupSearchQuery('')
        setIsGroupPickerOpen(false)
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const updateFollowupSetting = (key, value) => {
        setFollowupSettings(prev => ({ ...(prev || {}), [key]: value }))
    }

    const saveFollowupSettings = async () => {
        if (!followupSettings) return
        setIsSavingFollowupSettings(true)
        try {
            const payload = {
                absent_followup_enabled: !!followupSettings.absent_followup_enabled,
                absent_followup_schedule_mode: followupSettings.absent_followup_schedule_mode || 'after_report',
                absent_followup_delay_minutes: Number(followupSettings.absent_followup_delay_minutes ?? 5),
                absent_followup_before_lesson_time: followupSettings.absent_followup_before_lesson_time || '20:00',
                absent_followup_template: followupSettings.absent_followup_template || '',
                no_absents_followup_template: followupSettings.no_absents_followup_template || ''
            }
            const data = await apiClient.put('/parents-report/settings', payload, { toast: false })
            setFollowupSettings(data)
            setAlert({ type: 'success', text: 'Налаштування відпрацювання збережено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка збереження налаштувань' })
        } finally {
            setIsSavingFollowupSettings(false)
        }
    }

    const resetFollowupTemplate = (key) => {
        const template = FOLLOWUP_TEMPLATE_CARDS.find(card => card.key === key)?.defaultTemplate || DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
        setFollowupSettings(prev => ({
            ...(prev || {}),
            [key]: template
        }))
    }

    const toggleFollowupTemplate = (key) => {
        const nextKey = activeFollowupTemplate === key ? null : key
        setActiveFollowupTemplate(nextKey)
        if (nextKey) {
            setTimeout(() => followupEditorRefs.current[nextKey]?.focus?.(), 0)
        }
    }

    const insertFollowupText = (text, templateKey = activeFollowupTemplate) => {
        if (!templateKey) return

        const editor = followupEditorRefs.current[templateKey]
        if (editor?.insertText) {
            editor.insertText(text)
            return
        }

        setFollowupSettings(prev => ({
            ...(prev || {}),
            [templateKey]: `${prev?.[templateKey] || ''}${text}`
        }))
    }

    const insertFollowupPlaceholder = (token) => {
        insertFollowupText(token)
    }

    const toggleForm = () => {
        if (savingRef.current) return
        const next = !showForm
        setShowForm(next)
        if (!next) {
            resetForm()
        }
    }

    const appendFormFiles = (filesToAdd) => {
        const usableFiles = Array.from(filesToAdd || []).filter(Boolean)
        if (usableFiles.length > 0) {
            setFormFiles(prev => [...prev, ...usableFiles])
        }
    }

    const appendStickers = (stickersToAdd) => {
        const usableStickers = Array.from(stickersToAdd || []).filter(stickerKey)
        if (usableStickers.length === 0) return

        setSelectedStickers(prev => {
            const known = new Set(prev.map(stickerKey))
            const next = [...prev]
            for (const sticker of usableStickers) {
                const key = stickerKey(sticker)
                if (known.has(key)) continue
                if (next.length >= 12) {
                    setAlert({ type: 'warning', text: 'Можна додати до 12 наліпок в одне автоповідомлення.' })
                    break
                }
                known.add(key)
                next.push(sticker)
            }
            return next
        })
    }

    const importRemoteFile = async (url, filename = '') => {
        const data = await apiClient.post('/messages/import-url', { url, filename }, { toast: false })
        appendFormFiles([toServerFile(data, 'import')])
        setAlert({ type: 'success', text: `Файл додано: ${data.filename}` })
    }

    const { addFilesFromClipboardData, pasteFromClipboard } = useClipboardFiles({
        appendFiles: appendFormFiles,
        importRemoteFile,
        showToast: setAlert,
        hintText: '\u041d\u0430\u0442\u0438\u0441\u043d\u0456\u0442\u044c Ctrl+V \u0443 \u043f\u043e\u043b\u0456 \u0442\u0435\u043a\u0441\u0442\u0443 \u0430\u0432\u0442\u043e\u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f, \u0449\u043e\u0431 \u0432\u0441\u0442\u0430\u0432\u0438\u0442\u0438 \u0444\u0430\u0439\u043b \u0437 \u0431\u0443\u0444\u0435\u0440\u0430.',
        blockedText: '\u0414\u043e\u0441\u0442\u0443\u043f \u0434\u043e \u0431\u0443\u0444\u0435\u0440\u0430 \u0437\u0430\u0431\u043b\u043e\u043a\u043e\u0432\u0430\u043d\u043e. \u0421\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 Ctrl+V \u0443 \u043f\u043e\u043b\u0456 \u0442\u0435\u043a\u0441\u0442\u0443 \u0430\u0432\u0442\u043e\u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f.'
    })

    const { isDragging, setIsDragging, dragHandlers } = useDragDropFiles({
        dropZoneRef,
        appendFiles: appendFormFiles,
        importRemoteFile,
        showToast: setAlert,
        errorText: '\u041d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u0434\u043e\u0434\u0430\u0442\u0438 \u0444\u0430\u0439\u043b \u0437 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430'
    })

    const insertTemplate = (selectedValue) => {
        const rawValue = selectedValue?.target ? selectedValue.target.value : selectedValue
        const id = parseInt(rawValue)
        if (!id) return
        const tmpl = templates.find(t => t.id === id)
        if (tmpl) {
            if (tmpl.text) {
                setFormData(prev => ({
                    ...prev,
                    message: prev.message ? `${prev.message}\n\n${tmpl.text}` : tmpl.text
                }))
            }
            const templateFiles = tmpl.files || []
            const existingFiles = templateFiles.filter(file => file.exists !== false)
            const missingFiles = templateFiles.filter(file => file.exists === false)
            appendFormFiles(existingFiles.map(file => toServerFile(file, 'template')))
            appendStickers(tmpl.stickers || [])
            if (missingFiles.length > 0) {
                setAlert({
                    type: 'warning',
                    text: `Текст шаблону додано, але файли не знайдено: ${missingFiles.map(getFileName).join(', ')}`
                })
            }
        }
    }

    const handleFileSelect = (e) => {
        appendFormFiles(e.target.files)
        e.target.value = ''
    }

    const handlePaste = async (e) => {
        try {
            const handled = await addFilesFromClipboardData(e.clipboardData, () => e.preventDefault())
            if (handled) return
        } catch (error) {
            e.preventDefault()
            setAlert({ type: 'error', text: error.message || 'Не вдалося вставити файл з буфера' })
        }
    }

    const removeFile = (index) => {
        setFormFiles(prev => prev.filter((_, i) => i !== index))
    }

    const addSticker = (sticker) => {
        const stickerKey = sticker?.file_id || `${sticker?.pack_short_name || ''}:${sticker?.document_id || sticker?.id || ''}`
        if (!stickerKey) return
        setSelectedStickers(prev => {
            if (prev.some(item => (item.file_id || `${item.pack_short_name || ''}:${item.document_id || item.id || ''}`) === stickerKey)) {
                return prev
            }
            if (prev.length >= 12) {
                setAlert({ type: 'warning', text: 'Можна додати до 12 наліпок в одне автоповідомлення.' })
                return prev
            }
            return [...prev, sticker]
        })
    }

    const removeSticker = (sticker) => {
        const stickerKey = sticker?.file_id || `${sticker?.pack_short_name || ''}:${sticker?.document_id || sticker?.id || ''}`
        setSelectedStickers(prev => prev.filter(item => {
            const itemKey = item.file_id || `${item.pack_short_name || ''}:${item.document_id || item.id || ''}`
            return itemKey !== stickerKey
        }))
    }

    const createAutoMessage = async () => {
        if (savingRef.current) return
        if (!formData.group_id) {
            setAlert({ type: 'error', text: 'Виберіть групу!' })
            return
        }
        if (!formData.message.trim() && formFiles.length === 0 && selectedStickers.length === 0) {
            setAlert({ type: 'error', text: 'Додайте текст, файл або наліпку!' })
            return
        }

        savingRef.current = true
        setIsSaving(true)

        try {
            const payload = new FormData()
            const localFiles = formFiles.filter(file => !isServerFile(file))
            const storedFiles = formFiles
                .filter(isServerFile)
                .map(file => ({
                    storage: file.storage,
                    stored_filename: file.stored_filename,
                    filename: getFileName(file),
                    type: getFileType(file),
                    size: file.size || 0
                }))

            payload.append('group_id', String(parseInt(formData.group_id)))
            payload.append('message', formData.message.trim())
            payload.append('send_time', formData.send_time)
            payload.append('send_day', formData.send_day)
            payload.append('repeat_count', String(formData.repeat_count))
            payload.append('stored_files', JSON.stringify(storedFiles))
            payload.append('stickers', JSON.stringify(selectedStickers.map(sticker => ({
                file_id: sticker.file_id,
                document_id: sticker.document_id || sticker.id,
                emoji: sticker.emoji,
                mime_type: sticker.mime_type,
                pack_short_name: sticker.pack_short_name,
                thumb_url: sticker.thumb_url,
                animation_url: sticker.animation_url,
                preview_url: sticker.preview_url,
                is_animated: sticker.is_animated,
                is_video: sticker.is_video,
                file_name: sticker.file_name
            }))))
            localFiles.forEach(file => payload.append('files', file))

            await apiClient.form('/auto-messages/', payload, 'POST', { toast: false })
                setAlert({ type: 'success', text: 'Автоповідомлення створено!' })
                setShowForm(false)
                resetForm()
                fetchData()
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка підключення' })
        } finally {
            savingRef.current = false
            setIsSaving(false)
        }
    }

    const deleteAutoMessage = async (id) => {
        if (!confirm('Видалити це автоповідомлення?')) return

        try {
            await apiClient.delete(`/auto-messages/${id}`, { toast: false })
            fetchData()
            setAlert({ type: 'success', text: 'Автоповідомлення видалено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка видалення' })
        }
    }

    const toggleAutoMessage = async (id) => {
        try {
            await apiClient.request('PUT', `/auto-messages/${id}/toggle`, undefined, { toast: false })
            fetchData()
            setAlert({ type: 'success', text: 'Статус автоповідомлення змінено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка' })
        }
    }

    const startEditAutoMessage = (msg) => {
        setEditingId(msg.id)
        setEditDraft({
            message: msg.message || '',
            send_day: msg.send_day || 'mon',
            send_time: msg.send_time || '18:00',
            repeat_count: msg.repeat_count ?? 1
        })
    }

    const cancelEditAutoMessage = () => {
        setEditingId(null)
        setEditDraft(null)
    }

    const saveAutoMessageEdit = async (id) => {
        if (!editDraft) return
        try {
            await apiClient.put(`/auto-messages/${id}`, {
                message: editDraft.message,
                send_day: editDraft.send_day,
                send_time: editDraft.send_time,
                repeat_count: Number(editDraft.repeat_count ?? 1)
            }, { toast: false })
            setEditingId(null)
            setEditDraft(null)
            await fetchData()
            setAlert({ type: 'success', text: 'Автоповідомлення оновлено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка оновлення' })
        }
    }

    const getGroupName = (groupId) => {
        const group = groups.find(g => g.id === groupId)
        return group ? group.name : 'Невідома група'
    }

    const getDayLabel = (value) => {
        return DAYS.find(day => day.value === value || day.label === value)?.label || value
    }

    const selectedGroup = groups.find(group => String(group.id) === String(formData.group_id))
    const groupSearchTerms = getSearchVariations(groupSearchQuery)
    const filteredPickerGroups = groups.filter(group => {
        const query = groupSearchQuery.trim()
        if (!query) return true

        const searchable = [
            group.name,
            group.category_name,
            group.telegram_id,
            group.lesson_day,
            group.lesson_time
        ].filter(Boolean).join(' ').toLowerCase()

        return groupSearchTerms.some(term => searchable.includes(term))
    })
    const pickerCategories = [...new Set(
        filteredPickerGroups
            .map(group => group.category_name)
            .filter(Boolean)
    )]
    const pickerGroupsByCategory = [
        ...pickerCategories.map(categoryName => ({
            label: `📁 ${categoryName}`,
            groups: filteredPickerGroups.filter(group => group.category_name === categoryName)
        })),
        ...(filteredPickerGroups.some(group => !group.category_name)
            ? [{
                label: 'Без категорії',
                groups: filteredPickerGroups.filter(group => !group.category_name)
            }]
            : [])
    ]

    const selectPickerGroup = (group) => {
        setFormData(prev => ({ ...prev, group_id: String(group.id) }))
        setGroupSearchQuery('')
        setIsGroupPickerOpen(false)
    }

    const clearPickerGroup = () => {
        setFormData(prev => ({ ...prev, group_id: '' }))
        setGroupSearchQuery('')
        setIsGroupPickerOpen(true)
    }

    const renderFollowupSettingsCard = () => {
        if (!followupSettings) return null

        return (
            <div className="card absent-followup-card">
                <div className="absent-followup-header">
                    <div>
                        <h3 className="card-title">Повідомлення після звіту</h3>
                        <p>Програма автоматично підготує нагадування після успішного звіту і запланує його перед наступним уроком.</p>
                    </div>
                    <label className="parents-inline-toggle absent-followup-toggle">
                        <input
                            type="checkbox"
                            checked={!!followupSettings.absent_followup_enabled}
                            onChange={(event) => updateFollowupSetting('absent_followup_enabled', event.target.checked)}
                        />
                        <span className="parents-inline-toggle-track">
                            <span className="parents-inline-toggle-thumb" />
                        </span>
                        <span className="parents-inline-toggle-state">
                            {followupSettings.absent_followup_enabled ? 'Увімкнено' : 'Вимкнено'}
                        </span>
                    </label>
                </div>

                <div className="absent-followup-grid">
                    <label className="form-group">
                        <span className="form-label">Коли створювати</span>
                        <AppSelect
                            value={followupSettings.absent_followup_schedule_mode || 'after_report'}
                            options={[
                                { value: 'after_report', label: 'Після відправки звіту' },
                                { value: 'before_next_lesson', label: 'Перед наступним уроком' }
                            ]}
                            onChange={(value) => updateFollowupSetting('absent_followup_schedule_mode', value)}
                            ariaLabel="Коли створювати відкладене повідомлення"
                        />
                    </label>

                    {followupSettings.absent_followup_schedule_mode === 'before_next_lesson' ? (
                        <label className="form-group">
                            <span className="form-label">Час попереднього дня</span>
                            <TimePicker
                                value={followupSettings.absent_followup_before_lesson_time || '20:00'}
                                onChange={(value) => updateFollowupSetting('absent_followup_before_lesson_time', value)}
                                ariaLabel="Час відкладеного повідомлення перед наступним уроком"
                            />
                        </label>
                    ) : (
                        <label className="form-group">
                            <span className="form-label">Через скільки хв створити</span>
                            <NumberStepper
                                value={followupSettings.absent_followup_delay_minutes ?? 5}
                                min={0}
                                max={10080}
                                onChange={(value) => updateFollowupSetting('absent_followup_delay_minutes', value)}
                                ariaLabel="Затримка після звіту"
                            />
                        </label>
                    )}
                </div>

                <div className="followup-scenario-list">
                    {FOLLOWUP_TEMPLATE_CARDS.map(card => {
                        const isOpen = activeFollowupTemplate === card.key
                        const value = followupSettings[card.key] || ''
                        const followupEditorRef = {
                            get current() {
                                return followupEditorRefs.current[card.key] || null
                            },
                            set current(node) {
                                if (node) followupEditorRefs.current[card.key] = node
                                else delete followupEditorRefs.current[card.key]
                            }
                        }

                        return (
                            <section key={card.key} className={`followup-scenario-card ${isOpen ? 'open' : ''}`}>
                                <button
                                    type="button"
                                    className="followup-scenario-summary"
                                    onClick={() => toggleFollowupTemplate(card.key)}
                                    aria-expanded={isOpen}
                                >
                                    <span className="followup-scenario-icon">{card.key === 'absent_followup_template' ? '🔔' : '✅'}</span>
                                    <span className="followup-scenario-main">
                                        <strong>{card.title}</strong>
                                        <small>{card.description}</small>
                                        <span>{followupPreview(value)}</span>
                                    </span>
                                    <span className="followup-scenario-action">{isOpen ? 'Згорнути' : 'Редагувати'}</span>
                                </button>

                                {isOpen && (
                                    <div className="followup-scenario-editor">
                                        <MessageComposer
                                            value={value}
                                            setValue={(nextText) => updateFollowupSetting(card.key, nextText)}
                                            context="auto_message"
                                            onAlert={setAlert}
                                            disabled={isSavingFollowupSettings}
                                            rows={7}
                                            editorRef={followupEditorRef}
                                            allowFiles={false}
                                            allowStickers={false}
                                            editorClassName="form-textarea absent-followup-template"
                                            placeholder={'\u041d\u0430\u043f\u0438\u0448\u0456\u0442\u044c \u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f...'}
                                            placeholderTokens={FOLLOWUP_PLACEHOLDERS}
                                        />

                                        <div className="followup-placeholder-panel">
                                            <span>Вставити змінну</span>
                                            <div className="followup-placeholder-list">
                                                {FOLLOWUP_PLACEHOLDERS.map(item => (
                                                    <button
                                                        key={item.token}
                                                        type="button"
                                                        className="followup-placeholder-chip"
                                                        onClick={() => insertFollowupPlaceholder(item.token)}
                                                        title={item.token}
                                                    >
                                                        {item.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="followup-editor-actions">
                                            <button
                                                type="button"
                                                className="btn btn-secondary btn-sm"
                                                onClick={() => resetFollowupTemplate(card.key)}
                                            >
                                                Повернути шаблон
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </section>
                        )
                    })}
                </div>

                <div className="absent-followup-actions">
                    <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={saveFollowupSettings}
                        disabled={isSavingFollowupSettings}
                    >
                        {isSavingFollowupSettings ? 'Зберігаю...' : 'Зберегти повідомлення'}
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div>
            <div className="page-header">
                <h2>Автоповідомлення</h2>
                <p>Налаштуйте автоматичні повідомлення з текстом і файлами</p>
            </div>

            <div style={{ marginBottom: '24px' }}>
                <button className="btn btn-primary" onClick={toggleForm} disabled={isSaving}>
                    {showForm ? '× Закрити' : '+ Додати автоповідомлення'}
                </button>
            </div>

            {showForm && (
                <div className="card">
                    <h3 className="card-title" style={{ marginBottom: '20px' }}>Нове автоповідомлення</h3>

                    <div className="form-group">
                        <label className="form-label">Група</label>
                        <div className="group-picker" ref={groupPickerRef}>
                            {selectedGroup && (
                                <div className="group-picker-selected">
                                    <span>{selectedGroup.name}</span>
                                    {selectedGroup.category_name && <small>{selectedGroup.category_name}</small>}
                                    <button type="button" onClick={clearPickerGroup} aria-label="Очистити вибір">×</button>
                                </div>
                            )}
                            <div className={`group-picker-control ${isGroupPickerOpen ? 'open' : ''}`} ref={groupPickerControlRef}>
                                <input
                                    type="text"
                                    className="group-picker-input"
                                    value={groupSearchQuery}
                                    placeholder={selectedGroup ? 'Знайти іншу групу...' : 'Пошук групи...'}
                                    onChange={(event) => {
                                        setGroupSearchQuery(event.target.value)
                                        setIsGroupPickerOpen(true)
                                    }}
                                    onFocus={() => setIsGroupPickerOpen(true)}
                                />
                                <button
                                    type="button"
                                    className="group-picker-toggle"
                                    onClick={() => setIsGroupPickerOpen(prev => !prev)}
                                    aria-label="Відкрити список груп"
                                >
                                    ▾
                                </button>
                            </div>
                            <FloatingPanel
                                open={isGroupPickerOpen}
                                anchorRef={groupPickerControlRef}
                                panelRef={groupPickerDropdownRef}
                                className="group-picker-dropdown"
                                matchWidth
                                maxHeight={320}
                                zIndex={11000}
                            >
                                    {filteredPickerGroups.length === 0 ? (
                                        <div className="group-picker-empty">Групи не знайдено</div>
                                    ) : (
                                        pickerGroupsByCategory.map(section => (
                                            <div className="group-picker-section" key={section.label}>
                                                <div className="group-picker-section-title">{section.label}</div>
                                                {section.groups.map(group => (
                                                    <button
                                                        type="button"
                                                        key={group.id}
                                                        className={`group-picker-option ${String(group.id) === String(formData.group_id) ? 'selected' : ''}`}
                                                        onClick={() => selectPickerGroup(group)}
                                                    >
                                                        <span>{group.name}</span>
                                                        <small>
                                                            {[group.lesson_day, group.lesson_time].filter(Boolean).join(' · ') || 'Telegram група'}
                                                        </small>
                                                    </button>
                                                ))}
                                            </div>
                                        ))
                                    )}
                            </FloatingPanel>
                        </div>
                    </div>
                    <MessageComposer
                        value={formData.message}
                        setValue={(nextMessage) => setFormData(prev => ({ ...prev, message: nextMessage }))}
                        context="auto_message"
                        onAlert={setAlert}
                        disabled={isSaving}
                        label={'\u0422\u0435\u043a\u0441\u0442 \u043f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f \u0442\u0430 \u0444\u0430\u0439\u043b\u0438'}
                        placeholder={'\u041d\u0430\u043f\u0440\u0438\u043a\u043b\u0430\u0434: \u0421\u043a\u043e\u0440\u043e \u0443\u0440\u043e\u043a! \u0410\u0431\u043e \u043f\u0435\u0440\u0435\u0442\u044f\u0433\u043d\u0456\u0442\u044c \u0444\u0430\u0439\u043b\u0438 \u0441\u044e\u0434\u0438...'}
                        rows={5}
                        editorRef={textareaRef}
                        fileInputRef={fileInputRef}
                        onFileSelect={handleFileSelect}
                        pasteFromClipboard={pasteFromClipboard}
                        onPaste={handlePaste}
                        dropZoneRef={dropZoneRef}
                        dragHandlers={dragHandlers}
                        isDragging={isDragging}
                        dropLabel={'\u0412\u0456\u0434\u043f\u0443\u0441\u0442\u0456\u0442\u044c \u0444\u0430\u0439\u043b\u0438 \u0442\u0443\u0442'}
                        files={formFiles}
                        selectedStickers={selectedStickers}
                        onAddSticker={addSticker}
                        onRemoveSticker={removeSticker}
                        onRemoveFile={(_, index) => removeFile(index)}
                        defaultFileStorage="import"
                        onOpenFileError={(text) => setAlert({ type: 'warning', text })}
                        beforeEditor={templates.length > 0 && (
                            <div className="template-insert-bar" style={{ marginBottom: '8px' }}>
                                <label>{'\u0428\u0430\u0431\u043b\u043e\u043d:'}</label>
                                <AppSelect
                                    value=""
                                    options={templates.map(t => ({ value: t.id, label: t.name }))}
                                    placeholder={'\u0412\u0438\u0431\u0440\u0430\u0442\u0438 \u0448\u0430\u0431\u043b\u043e\u043d \u0434\u043b\u044f \u0432\u0441\u0442\u0430\u0432\u043a\u0438...'}
                                    onChange={insertTemplate}
                                    ariaLabel={'\u0412\u0438\u0431\u0440\u0430\u0442\u0438 \u0448\u0430\u0431\u043b\u043e\u043d \u0434\u043b\u044f \u0432\u0441\u0442\u0430\u0432\u043a\u0438'}
                                />
                            </div>
                        )}
                    />

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px' }}>
                        <div className="form-group">
                            <label className="form-label">День відправки</label>
                            <AppSelect
                                value={formData.send_day}
                                options={DAYS}
                                onChange={(value) => setFormData({ ...formData, send_day: value })}
                                ariaLabel="День відправки"
                            />
                        </div>

                        <div className="form-group">
                            <label className="form-label">Час відправки</label>
                            <TimePicker
                                value={formData.send_time}
                                onChange={(value) => setFormData({ ...formData, send_time: value })}
                                ariaLabel="Час відправки"
                            />
                        </div>

                        <div className="form-group">
                            <label className="form-label">Кількість повторів</label>
                            <NumberStepper
                                min={0}
                                max={1000}
                                value={formData.repeat_count}
                                onChange={(value) => setFormData({ ...formData, repeat_count: value })}
                                ariaLabel="Кількість повторів"
                            />
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '6px' }}>
                                * Вкажіть <strong>0</strong> для постійної відправки без обмежень.
                            </div>
                        </div>
                    </div>

                    <button
                        className="btn btn-success"
                        onClick={createAutoMessage}
                        disabled={isSaving}
                        aria-busy={isSaving}
                    >
                        {isSaving ? 'Зберігаю...' : 'Зберегти'}
                    </button>
                </div>
            )}

            <div className="card">
                <h3 className="card-title" style={{ marginBottom: '20px' }}>Список автоповідомлень</h3>

                {loading ? (
                    <div className="loader"><div className="spinner"></div></div>
                ) : autoMessages.length === 0 ? (
                    <div className="empty-state">
                        <p>Автоповідомлень немає. Створіть перше!</p>
                    </div>
                ) : (
                    <div className="table-container">
                        <table className="table">
                            <thead>
                                <tr>
                                    <th>Група</th>
                                    <th>Повідомлення</th>
                                    <th>Вкладення</th>
                                    <th>День</th>
                                    <th>Час</th>
                                    <th>Повтори</th>
                                    <th>Статус</th>
                                    <th>Дії</th>
                                </tr>
                            </thead>
                            <tbody>
                                {autoMessages.map(msg => {
                                    const isEditing = editingId === msg.id
                                    const isFollowup = msg.source === 'parent_report_absent_followup' || msg.source === 'parent_report_followup'
                                    const followupType = msg.metadata?.type || (msg.source === 'parent_report_absent_followup' ? 'absent_followup' : '')
                                    const followupLabel = followupType === 'regular_followup' ? 'Нагадування' : 'Відпрацювання'
                                    return (
                                    <tr key={msg.id} className={isFollowup ? 'auto-followup-row' : ''}>
                                        <td>
                                            <strong>{getGroupName(msg.group_id)}</strong>
                                            {isFollowup && (
                                                <span className="auto-followup-badge">{followupLabel}</span>
                                            )}
                                            {isFollowup && msg.metadata?.absents && (
                                                <small className="auto-followup-meta">
                                                    🔔 {msg.metadata.absents}
                                                </small>
                                            )}
                                            {isFollowup && followupType === 'regular_followup' && msg.metadata?.next_lesson_day && (
                                                <small className="auto-followup-meta">
                                                    🔔 {msg.metadata.next_lesson_day} о {msg.metadata.next_lesson_time}
                                                </small>
                                            )}
                                        </td>
                                        <td className="auto-message-text-cell">
                                            {isEditing ? (
                                                <textarea
                                                    className="form-textarea auto-edit-textarea"
                                                    value={editDraft?.message || ''}
                                                    onChange={(event) => setEditDraft(prev => ({ ...(prev || {}), message: event.target.value }))}
                                                    rows={6}
                                                />
                                            ) : (
                                                <div className="auto-message-preview">
                                                    {msg.message || <span style={{ color: 'var(--text-secondary)' }}>Без тексту</span>}
                                                </div>
                                            )}
                                        </td>
                                        <td style={{ minWidth: '220px' }}>
                                            {(msg.files && msg.files.length > 0) || (msg.stickers && msg.stickers.length > 0) ? (
                                                <div className="template-files" style={{ marginTop: 0 }}>
                                                    {(msg.files || []).map(file => (
                                                        <FilePreviewChip
                                                            key={file.id}
                                                            file={{ ...file, storage: 'auto' }}
                                                            defaultStorage="auto"
                                                            compact
                                                            removable={false}
                                                            onOpenError={(text) => setAlert({ type: 'warning', text })}
                                                        />
                                                    ))}
                                                    {(msg.stickers || []).map((sticker, index) => {
                                                        const stickerKey = sticker.file_id || `${sticker.pack_short_name || ''}:${sticker.document_id || sticker.id || index}`
                                                        return (
                                                            <span key={stickerKey} className="history-sticker-chip" title="Наліпка">
                                                                <StickerPreview sticker={sticker} />
                                                            </span>
                                                        )
                                                    })}
                                                </div>
                                            ) : (
                                                <span style={{ color: 'var(--text-secondary)' }}>-</span>
                                            )}
                                        </td>
                                        <td>
                                            {isEditing ? (
                                                <AppSelect
                                                    value={editDraft?.send_day || msg.send_day}
                                                    options={DAYS}
                                                    onChange={(value) => setEditDraft(prev => ({ ...(prev || {}), send_day: value }))}
                                                    ariaLabel="День відправки"
                                                />
                                            ) : getDayLabel(msg.send_day)}
                                        </td>
                                        <td>
                                            {isEditing ? (
                                                <TimePicker
                                                    value={editDraft?.send_time || msg.send_time}
                                                    onChange={(value) => setEditDraft(prev => ({ ...(prev || {}), send_time: value }))}
                                                    ariaLabel="Час відправки"
                                                />
                                            ) : msg.send_time}
                                        </td>
                                        <td>
                                            {isEditing ? (
                                                <NumberStepper
                                                    min={0}
                                                    max={1000}
                                                    value={editDraft?.repeat_count ?? msg.repeat_count}
                                                    onChange={(value) => setEditDraft(prev => ({ ...(prev || {}), repeat_count: value }))}
                                                    ariaLabel="Кількість повторів"
                                                />
                                            ) : msg.repeat_count === 0
                                                ? <span style={{ color: 'var(--success)', fontWeight: 'bold' }}>Безкінечно ({msg.sent_count})</span>
                                                : `${msg.sent_count} / ${msg.repeat_count}`
                                            }
                                        </td>
                                        <td>
                                            <span className={`badge ${msg.is_active ? 'badge-success' : 'badge-danger'}`}>
                                                {msg.is_active ? 'Активне' : 'Вимкнено'}
                                            </span>
                                        </td>
                                        <td>
                                            <div className="btn-group">
                                                {isEditing ? (
                                                    <>
                                                        <button
                                                            className="btn btn-primary btn-sm"
                                                            onClick={() => saveAutoMessageEdit(msg.id)}
                                                        >
                                                            Зберегти
                                                        </button>
                                                        <button
                                                            className="btn btn-secondary btn-sm"
                                                            onClick={cancelEditAutoMessage}
                                                        >
                                                            Скасувати
                                                        </button>
                                                    </>
                                                ) : (
                                                    <>
                                                        <button
                                                            className="btn btn-secondary btn-sm"
                                                            onClick={() => startEditAutoMessage(msg)}
                                                            title="Редагувати"
                                                        >
                                                            ✎
                                                        </button>
                                                        <button
                                                            className="btn btn-secondary btn-sm"
                                                            onClick={() => toggleAutoMessage(msg.id)}
                                                            title={msg.is_active ? 'Стоп' : 'Запустити'}
                                                        >
                                                            {isFollowup
                                                                ? (msg.is_active ? 'Стоп' : 'Запустити')
                                                                : (msg.is_active ? '⏸' : '▶')}
                                                        </button>
                                                        <button
                                                            className="btn btn-danger btn-sm auto-delete-button"
                                                            onClick={() => deleteAutoMessage(msg.id)}
                                                            title="Видалити"
                                                            aria-label="Видалити"
                                                        >
                                                            <TrashIcon />
                                                        </button>
                                                    </>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                    )
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {renderFollowupSettingsCard()}
        </div>
    )
}

export default AutoMessages

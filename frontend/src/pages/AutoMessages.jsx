import { useState, useEffect, useRef } from 'react'
import EmojiPicker from '../components/EmojiPicker'
import FilePreviewChip from '../components/FilePreviewChip'
import FloatingPanel from '../components/FloatingPanel'
import StickerIcon from '../components/StickerIcon'
import StickerPicker from '../components/StickerPicker'
import StickerPreview from '../components/StickerPreview'
import TelegramTextToolbar from '../components/TelegramTextToolbar'
import RichTelegramEditor from '../components/RichTelegramEditor'
import MagicTextButton from '../components/MagicTextButton'
import { AppSelect, NumberStepper, TimePicker } from '../components/FormControls'
import { getSearchVariations } from '../utils/search'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'
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
    const [alert, setAlert] = useState(null)
    const [templates, setTemplates] = useState([])
    const [showEmoji, setShowEmoji] = useState(false)
    const [showStickers, setShowStickers] = useState(false)
    const [formFiles, setFormFiles] = useState([])
    const [selectedStickers, setSelectedStickers] = useState([])
    const [isDragging, setIsDragging] = useState(false)
    const [isSaving, setIsSaving] = useState(false)
    const [followupSettings, setFollowupSettings] = useState(null)
    const [isSavingFollowupSettings, setIsSavingFollowupSettings] = useState(false)
    const [editingId, setEditingId] = useState(null)
    const [editDraft, setEditDraft] = useState(null)
    const textareaRef = useRef(null)
    const fileInputRef = useRef(null)
    const dropZoneRef = useRef(null)
    const groupPickerRef = useRef(null)
    const groupPickerControlRef = useRef(null)
    const groupPickerDropdownRef = useRef(null)
    const emojiButtonRef = useRef(null)
    const stickerButtonRef = useRef(null)
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
        if (!alert) return
        const timer = setTimeout(() => setAlert(null), 5000)
        return () => clearTimeout(timer)
    }, [alert])

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
            const [autoMsgRes, groupsRes] = await Promise.all([
                fetch(`${API_URL}/auto-messages/`),
                fetch(`${API_URL}/groups/`)
            ])
            setAutoMessages(await autoMsgRes.json())
            setGroups(await groupsRes.json())
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка завантаження автоповідомлень' })
        }
        setLoading(false)
    }

    const fetchTemplates = async () => {
        try {
            const response = await fetch(`${API_URL}/templates/`)
            const data = await response.json()
            setTemplates(data)
        } catch (error) {
            console.error('Помилка завантаження шаблонів:', error)
        }
    }

    const fetchFollowupSettings = async () => {
        try {
            const response = await fetch(`${API_URL}/parents-report/settings`)
            const data = await response.json()
            if (response.ok) {
                setFollowupSettings(data)
            }
        } catch (error) {
            console.error('Помилка завантаження налаштувань відпрацювання:', error)
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
        setShowEmoji(false)
        setShowStickers(false)
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
            const response = await fetch(`${API_URL}/parents-report/settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || 'Не вдалося зберегти налаштування')
            }
            setFollowupSettings(data)
            setAlert({ type: 'success', text: 'Налаштування відпрацювання збережено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка збереження налаштувань' })
        } finally {
            setIsSavingFollowupSettings(false)
        }
    }

    const resetFollowupTemplate = (key) => {
        const template = key === 'no_absents_followup_template'
            ? DEFAULT_NO_ABSENTS_FOLLOWUP_TEMPLATE
            : DEFAULT_ABSENT_FOLLOWUP_TEMPLATE
        setFollowupSettings(prev => ({
            ...(prev || {}),
            [key]: template
        }))
    }

    const toggleForm = () => {
        if (savingRef.current) return
        const next = !showForm
        setShowForm(next)
        if (!next) {
            resetForm()
        }
    }

    const isServerFile = (file) => file && file.source === 'server'

    const getFileName = (file) => file?.name || file?.filename || file?.original_filename || 'file'

    const getFileType = (file) => file?.type || file?.content_type || 'application/octet-stream'

    const toServerFile = (file, storage = 'template') => ({
        source: 'server',
        storage: file.storage || storage,
        stored_filename: file.stored_filename,
        name: file.filename || file.original_filename || file.name || 'file',
        filename: file.filename || file.original_filename || file.name || 'file',
        type: file.type || file.content_type || 'application/octet-stream',
        size: file.size || 0
    })

    const appendFormFiles = (filesToAdd) => {
        const usableFiles = Array.from(filesToAdd || []).filter(Boolean)
        if (usableFiles.length > 0) {
            setFormFiles(prev => [...prev, ...usableFiles])
        }
    }

    const stickerKey = (sticker) => sticker?.file_id || `${sticker?.pack_short_name || ''}:${sticker?.document_id || sticker?.id || ''}`

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

    const insertTextAtCursor = (text) => {
        if (!text) return
        const el = textareaRef.current
        const current = formData.message
        if (el?.insertText) {
            el.insertText(text)
            return
        }
        if (!el) {
            setFormData(prev => ({ ...prev, message: prev.message ? `${prev.message}\n\n${text}` : text }))
            return
        }
        const start = el.selectionStart ?? current.length
        const end = el.selectionEnd ?? current.length
        const newValue = current.slice(0, start) + text + current.slice(end)
        setFormData(prev => ({ ...prev, message: newValue }))
        setTimeout(() => {
            el.focus()
            const cursor = start + text.length
            el.setSelectionRange(cursor, cursor)
        }, 0)
    }

    const extractUrlFromHtml = (html) => {
        if (!html) return ''
        const doc = new DOMParser().parseFromString(html, 'text/html')
        return doc.querySelector('img, video, source, a')?.getAttribute('src')
            || doc.querySelector('a')?.getAttribute('href')
            || ''
    }

    const extractUrlFromText = (text) => {
        const match = (text || '').match(/https?:\/\/[^\s"'<>]+/i)
        return match ? match[0] : ''
    }

    const importRemoteFile = async (url, filename = '') => {
        const response = await fetch(`${API_URL}/messages/import-url`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url, filename })
        })
        const data = await response.json()
        if (!response.ok) {
            throw new Error(data.detail || 'Не вдалося імпортувати файл')
        }
        appendFormFiles([toServerFile(data, 'import')])
        setAlert({ type: 'success', text: `Файл додано: ${data.filename}` })
    }

    const addFilesFromClipboardData = async (clipboardData, preventDefault = false) => {
        const files = []
        for (const item of Array.from(clipboardData?.items || [])) {
            if (item.kind === 'file') {
                const file = item.getAsFile()
                if (file) files.push(file)
            }
        }

        if (files.length > 0) {
            if (preventDefault) preventDefault()
            appendFormFiles(files)
            return true
        }

        const htmlUrl = extractUrlFromHtml(clipboardData?.getData('text/html'))
        const textUrl = extractUrlFromText(
            clipboardData?.getData('text/uri-list') || clipboardData?.getData('text/plain')
        )
        const url = htmlUrl || textUrl
        if (url) {
            if (preventDefault) preventDefault()
            await importRemoteFile(url)
            return true
        }

        return false
    }

    const pasteFromClipboard = async () => {
        try {
            if (navigator.clipboard?.read) {
                const items = await navigator.clipboard.read()
                const files = []
                for (const item of items) {
                    for (const type of item.types) {
                        if (type.startsWith('image/') || type.startsWith('video/') || type === 'application/pdf') {
                            const blob = await item.getType(type)
                            const extension = type.split('/')[1]?.replace('jpeg', 'jpg') || 'bin'
                            files.push(new File([blob], `clipboard_${Date.now()}.${extension}`, { type }))
                            break
                        }
                    }
                }
                if (files.length > 0) {
                    appendFormFiles(files)
                    return
                }
            }
            setAlert({ type: 'info', text: 'Натисніть Ctrl+V у полі тексту автоповідомлення, щоб вставити файл з буфера.' })
        } catch (error) {
            setAlert({ type: 'warning', text: 'Доступ до буфера заблоковано. Спробуйте Ctrl+V у полі тексту автоповідомлення.' })
        }
    }

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

    const insertEmoji = (emoji) => {
        const el = textareaRef.current
        const current = formData.message
        if (el?.insertText) {
            el.insertText(emoji)
            return
        }
        if (!el) {
            setFormData(prev => ({ ...prev, message: prev.message + emoji }))
            return
        }
        const start = el.selectionStart
        const end = el.selectionEnd
        const newVal = current.slice(0, start) + emoji + current.slice(end)
        setFormData(prev => ({ ...prev, message: newVal }))
        setTimeout(() => {
            el.focus()
            el.setSelectionRange(start + emoji.length, start + emoji.length)
        }, 0)
    }

    const handleFileSelect = (e) => {
        appendFormFiles(e.target.files)
        e.target.value = ''
    }

    const handleDragEnter = (e) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragging(true)
    }

    const handleDragOver = (e) => {
        e.preventDefault()
        e.stopPropagation()
    }

    const handleDragLeave = (e) => {
        e.preventDefault()
        e.stopPropagation()
        if (dropZoneRef.current && dropZoneRef.current.contains(e.relatedTarget)) {
            return
        }
        setIsDragging(false)
    }

    const handleDrop = async (e) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragging(false)

        const droppedFiles = Array.from(e.dataTransfer.files || []).filter(file => file.size > 0)
        if (droppedFiles.length > 0) {
            appendFormFiles(droppedFiles)
            return
        }

        const htmlUrl = extractUrlFromHtml(e.dataTransfer.getData('text/html'))
        const textUrl = extractUrlFromText(e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain'))
        const url = htmlUrl || textUrl
        if (!url) return

        try {
            await importRemoteFile(url)
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Не вдалося додати файл з браузера' })
        }
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

            const response = await fetch(`${API_URL}/auto-messages/`, {
                method: 'POST',
                body: payload
            })
            const data = await response.json().catch(() => ({}))

            if (response.ok) {
                setAlert({ type: 'success', text: 'Автоповідомлення створено!' })
                setShowForm(false)
                resetForm()
                fetchData()
            } else {
                setAlert({ type: 'error', text: data.detail || 'Помилка створення автоповідомлення' })
            }
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
            const response = await fetch(`${API_URL}/auto-messages/${id}`, { method: 'DELETE' })
            if (!response.ok) {
                const data = await response.json().catch(() => ({}))
                throw new Error(data.detail || 'Помилка видалення')
            }
            fetchData()
            setAlert({ type: 'success', text: 'Автоповідомлення видалено' })
        } catch (error) {
            setAlert({ type: 'error', text: error.message || 'Помилка видалення' })
        }
    }

    const toggleAutoMessage = async (id) => {
        try {
            const response = await fetch(`${API_URL}/auto-messages/${id}/toggle`, { method: 'PUT' })
            if (!response.ok) {
                const data = await response.json().catch(() => ({}))
                throw new Error(data.detail || 'Помилка')
            }
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
            const response = await fetch(`${API_URL}/auto-messages/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: editDraft.message,
                    send_day: editDraft.send_day,
                    send_time: editDraft.send_time,
                    repeat_count: Number(editDraft.repeat_count ?? 1)
                })
            })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || 'Не вдалося оновити автоповідомлення')
            }
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

    return (
        <div>
            <div className="page-header">
                <h2>Автоповідомлення</h2>
                <p>Налаштуйте автоматичні повідомлення з текстом і файлами</p>
            </div>

            {alert && (
                <div className={`alert alert-${alert.type}`}>
                    {alert.text}
                </div>
            )}

            {followupSettings && (
                <div className="card absent-followup-card">
                    <div className="absent-followup-header">
                        <div>
                            <h3 className="card-title">Повідомлення після звіту</h3>
                            <p>
                                Після успішного звіту програма створить відкладене повідомлення: окремо для уроків з відсутніми і без відсутніх.
                            </p>
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
                            <span className="form-label">Коли створювати відкладене</span>
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
                                <span className="form-label">Затримка після звіту, хв</span>
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

                    <div className="absent-followup-template-grid">
                        <div className="absent-followup-template-panel">
                            <label className="form-group">
                                <span className="form-label">Якщо є відсутні</span>
                                <textarea
                                    className="form-textarea absent-followup-template"
                                    value={followupSettings.absent_followup_template || ''}
                                    onChange={(event) => updateFollowupSetting('absent_followup_template', event.target.value)}
                                    rows={8}
                                />
                            </label>
                            <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => resetFollowupTemplate('absent_followup_template')}
                            >
                                Повернути шаблон
                            </button>
                        </div>

                        <div className="absent-followup-template-panel">
                            <label className="form-group">
                                <span className="form-label">Якщо відсутніх немає</span>
                                <textarea
                                    className="form-textarea absent-followup-template"
                                    value={followupSettings.no_absents_followup_template || ''}
                                    onChange={(event) => updateFollowupSetting('no_absents_followup_template', event.target.value)}
                                    rows={8}
                                />
                            </label>
                            <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                onClick={() => resetFollowupTemplate('no_absents_followup_template')}
                            >
                                Повернути шаблон
                            </button>
                        </div>
                    </div>

                    <span className="absent-followup-hint">
                        Плейсхолдери: {'{absents}'}, {'{makeup_time}'}, {'{next_lesson_day}'}, {'{next_lesson_time_dot}'}, {'{group}'}, {'{course}'}, {'{lesson_code}'}.
                    </span>

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
            )}

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

                    <div
                        ref={dropZoneRef}
                        onDragEnter={handleDragEnter}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                        style={{
                            position: 'relative',
                            borderRadius: 'var(--radius-sm)',
                            border: isDragging ? '2px dashed var(--primary)' : '1px solid transparent',
                            background: isDragging ? 'rgba(99, 102, 241, 0.06)' : 'transparent',
                            transition: 'border 0.15s ease, background 0.15s ease',
                            padding: isDragging ? '10px' : '0'
                        }}
                    >
                        <div
                            style={{
                                position: 'absolute',
                                inset: 0,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                background: 'rgba(30, 41, 59, 0.88)',
                                borderRadius: 'var(--radius-sm)',
                                color: 'var(--primary)',
                                fontWeight: 'bold',
                                fontSize: '1.05rem',
                                pointerEvents: 'none',
                                zIndex: 10,
                                opacity: isDragging ? 1 : 0,
                                visibility: isDragging ? 'visible' : 'hidden',
                                transition: 'opacity 0.1s ease'
                            }}
                        >
                            Відпустіть файли тут
                        </div>

                        <div className="form-group">
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                                <label className="form-label" style={{ margin: 0 }}>Текст повідомлення та файли</label>
                                <div className="message-tools-row">
                                    <MagicTextButton
                                        value={formData.message}
                                        setValue={(nextMessage) => setFormData(prev => ({ ...prev, message: nextMessage }))}
                                        context="auto_message"
                                        onAlert={setAlert}
                                        disabled={isSaving}
                                    />
                                    <div className="emoji-picker-wrap">
                                        <button
                                            ref={emojiButtonRef}
                                            className="emoji-trigger-btn"
                                            onClick={() => {
                                                setShowEmoji(v => !v)
                                                setShowStickers(false)
                                            }}
                                            title="Додати смайлик"
                                            type="button"
                                            style={{ fontSize: '1.3rem', opacity: 1 }}
                                        >
                                            😊
                                        </button>
                                        {showEmoji && (
                                            <EmojiPicker
                                                anchorRef={emojiButtonRef}
                                                onSelect={(emoji) => insertEmoji(emoji)}
                                                onClose={() => setShowEmoji(false)}
                                            />
                                        )}
                                    </div>
                                    <div className="sticker-picker-wrap">
                                        <button
                                            ref={stickerButtonRef}
                                            className="emoji-trigger-btn"
                                            onClick={() => {
                                                setShowStickers(v => !v)
                                                setShowEmoji(false)
                                            }}
                                            title="Додати наліпку"
                                            type="button"
                                            style={{ opacity: 1 }}
                                        >
                                            <StickerIcon />
                                        </button>
                                        {showStickers && (
                                            <StickerPicker
                                                anchorRef={stickerButtonRef}
                                                onSelect={addSticker}
                                                onClose={() => setShowStickers(false)}
                                            />
                                        )}
                                    </div>
                                    <TelegramTextToolbar
                                        textareaRef={textareaRef}
                                        value={formData.message}
                                        setValue={(nextMessage) => setFormData(prev => ({ ...prev, message: nextMessage }))}
                                    />
                                    <button
                                        type="button"
                                        className="btn btn-secondary btn-sm"
                                        onClick={() => fileInputRef.current?.click()}
                                    >
                                        + Додати файли
                                    </button>
                                    <button
                                        type="button"
                                        className="btn btn-secondary btn-sm"
                                        onClick={pasteFromClipboard}
                                    >
                                        Вставити з буфера
                                    </button>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        multiple
                                        style={{ display: 'none' }}
                                        onChange={handleFileSelect}
                                    />
                                </div>
                            </div>

                            {templates.length > 0 && (
                                <div className="template-insert-bar" style={{ marginBottom: '8px' }}>
                                    <label>Шаблон:</label>
                                    <AppSelect
                                        value=""
                                        options={templates.map(t => ({ value: t.id, label: t.name }))}
                                        placeholder="Вибрати шаблон для вставки..."
                                        onChange={insertTemplate}
                                        ariaLabel="Вибрати шаблон для вставки"
                                    />
                                </div>
                            )}

                            <RichTelegramEditor
                                ref={textareaRef}
                                className="form-textarea"
                                placeholder="Наприклад: Скоро урок! Або перетягніть файли сюди..."
                                value={formData.message}
                                onChange={(e) => setFormData({ ...formData, message: e.target.value })}
                                onPaste={handlePaste}
                                rows={5}
                                style={{ position: 'relative', zIndex: 1 }}
                            />

                            {formFiles.length > 0 && (
                                <div className="file-preview-list" style={{ marginTop: '12px', marginBottom: 0 }}>
                                    {formFiles.map((file, index) => (
                                        <FilePreviewChip
                                            key={`${getFileName(file)}-${index}`}
                                            file={file}
                                            defaultStorage={isServerFile(file) ? file.storage : 'import'}
                                            onRemove={() => removeFile(index)}
                                            onOpenError={(text) => setAlert({ type: 'warning', text })}
                                        />
                                    ))}
                                </div>
                            )}

                            {selectedStickers.length > 0 && (
                                <div className="selected-sticker-list">
                                    {selectedStickers.map(sticker => {
                                        const stickerKey = sticker.file_id || `${sticker.pack_short_name || ''}:${sticker.document_id || sticker.id || ''}`
                                        return (
                                            <div key={stickerKey} className="selected-sticker-chip">
                                                <StickerPreview sticker={sticker} />
                                                <button
                                                    type="button"
                                                    className="selected-sticker-remove"
                                                    onClick={() => removeSticker(sticker)}
                                                    title="Прибрати наліпку"
                                                >
                                                    ×
                                                </button>
                                            </div>
                                        )
                                    })}
                                </div>
                            )}
                        </div>
                    </div>

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
        </div>
    )
}

export default AutoMessages

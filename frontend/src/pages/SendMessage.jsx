import { useState, useEffect, useRef } from 'react'
import { saveFilesToDB, getFilesFromDB, deleteOldFilesFromDB } from '../utils/db'
import { getSearchVariations } from '../utils/search'
import EmojiPicker from '../components/EmojiPicker'
import FilePreviewChip from '../components/FilePreviewChip'
import HistoryFileChip from '../components/HistoryFileChip'
import StickerPicker from '../components/StickerPicker'
import StickerPreview from '../components/StickerPreview'
import StickerIcon from '../components/StickerIcon'
import TelegramTextToolbar from '../components/TelegramTextToolbar'
import RichTelegramEditor from '../components/RichTelegramEditor'
import MagicTextButton from '../components/MagicTextButton'
import TelegramSendIcon from '../components/TelegramSendIcon'
import { AppSelect } from '../components/FormControls'

// URL бекенду
const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'
const HISTORY_RETENTION_DAYS = 7

function SendMessage() {
    const [groups, setGroups] = useState([])
    const [categories, setCategories] = useState([])
    const [categoryFilter, setCategoryFilter] = useState(null) // null = всі, id = конкретна категорія
    const [selectedGroups, setSelectedGroups] = useState([])
    const [message, setMessage] = useState('')
    const [loading, setLoading] = useState(false)
    const [sending, setSending] = useState(false)
    const [alert, setAlert] = useState(null)
    const [selectedFiles, setSelectedFiles] = useState([])
    const [isDragging, setIsDragging] = useState(false)
    const [history, setHistory] = useState([])
    const [expandedMsgIds, setExpandedMsgIds] = useState([])
    const [isHistoryExpanded, setIsHistoryExpanded] = useState(() => {
        return localStorage.getItem('isHistoryExpanded') === 'true'
    })
    const [templates, setTemplates] = useState([])
    const [showEmoji, setShowEmoji] = useState(false)
    const [showStickers, setShowStickers] = useState(false)
    const [selectedStickers, setSelectedStickers] = useState([])
    const [searchQuery, setSearchQuery] = useState('')
    const [isGroupsExpanded, setIsGroupsExpanded] = useState(false)
    const [isCreatingCategory, setIsCreatingCategory] = useState(false)
    const [newCategoryName, setNewCategoryName] = useState('')
    const [contextMenu, setContextMenu] = useState(null)
    const [categoryContextMenu, setCategoryContextMenu] = useState(null)
    const [renamingCategory, setRenamingCategory] = useState(null)
    const [renameCategoryName, setRenameCategoryName] = useState('')
    const [draggedGroupIds, setDraggedGroupIds] = useState([])
    const [dragOverCategory, setDragOverCategory] = useState(null)
    const textareaRef = useRef(null)
    const fileInputRef = useRef(null)
    const emojiButtonRef = useRef(null)
    const stickerButtonRef = useRef(null)

    // Фільтровані групи по категорії та пошуку
    const filteredGroups = groups.filter(g => {
        const matchesCategory = categoryFilter === null
            ? true
            : categoryFilter === 0
                ? !g.category_id
                : g.category_id === categoryFilter;
        
        if (!matchesCategory) return false;
        if (!searchQuery) return true;

        const searchVars = getSearchVariations(searchQuery);
        const groupName = g.name.toLowerCase();
        
        return searchVars.some(term => groupName.includes(term));
    });

    // Завантаження історії та очищення старих записів
    useEffect(() => {
        const loadHistory = async () => {
            try {
                const savedHistory = JSON.parse(localStorage.getItem('messageHistory')) || []
                const now = new Date().getTime()
                const retentionMs = HISTORY_RETENTION_DAYS * 24 * 60 * 60 * 1000
                const validHistory = savedHistory.filter(item => (now - item.timestamp) < retentionMs)
                setHistory(validHistory)
                if (savedHistory.length !== validHistory.length) {
                    localStorage.setItem('messageHistory', JSON.stringify(validHistory))
                }
                
                // Видаляємо старі файли з IndexedDB
                const validIds = validHistory.map(h => h.id)
                await deleteOldFilesFromDB(validIds)
            } catch (e) {
                setHistory([])
                try {
                    await deleteOldFilesFromDB([])
                } catch (_) {}
            }
        }
        loadHistory()
    }, [])

    useEffect(() => {
        localStorage.setItem('isHistoryExpanded', isHistoryExpanded)
    }, [isHistoryExpanded])

    useEffect(() => {
        const closeMenu = () => {
            setContextMenu(null)
            setCategoryContextMenu(null)
        }
        window.addEventListener('click', closeMenu)
        window.addEventListener('scroll', closeMenu, true)
        return () => {
            window.removeEventListener('click', closeMenu)
            window.removeEventListener('scroll', closeMenu, true)
        }
    }, [])

    // Завантажуємо список груп, категорії та шаблони
    useEffect(() => {
        fetchGroups()
        fetchCategories()
        fetchTemplates()
    }, [])

    // Створення категорії інлайн
    const handleCreateCategory = async () => {
        if (!newCategoryName.trim()) {
            setIsCreatingCategory(false)
            return
        }
        try {
            const response = await fetch(`${API_URL}/categories/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newCategoryName.trim() })
            })
            if (response.ok) {
                const newCat = await response.json()
                setCategories([...categories, newCat])
                setCategoryFilter(newCat.id)
            }
        } catch (error) {
            console.error('Помилка створення категорії:', error)
        }
        setNewCategoryName('')
        setIsCreatingCategory(false)
    }

    const openCategoryContextMenu = (e, category) => {
        e.preventDefault()
        e.stopPropagation()
        setContextMenu(null)
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
            setAlert({ type: 'error', text: error.message || 'Помилка перейменування категорії' })
        }
    }

    // Drag & Drop
    const handleGroupDragStart = (e, groupId) => {
        const ids = selectedGroups.includes(groupId) ? selectedGroups : [groupId]
        setDraggedGroupIds(ids)
        e.dataTransfer.setData('groupId', String(groupId))
        e.dataTransfer.setData('groupIds', JSON.stringify(ids))
        e.dataTransfer.effectAllowed = 'move'
    }

    const handleGroupDragEnd = () => {
        setDraggedGroupIds([])
        setDragOverCategory(null)
    }

    const handleGroupDragOver = (e, categoryKey) => {
        e.preventDefault() // Дозволяє drop
        e.stopPropagation()
        e.dataTransfer.dropEffect = 'move'
        setDragOverCategory(categoryKey)
    }

    const handleGroupDragLeave = (e, categoryKey) => {
        if (e.currentTarget.contains(e.relatedTarget)) return
        setDragOverCategory(prev => prev === categoryKey ? null : prev)
    }

    const handleGroupDrop = async (e, categoryId) => {
        e.preventDefault()
        e.stopPropagation()
        setDragOverCategory(null)

        let groupIds = []
        try {
            groupIds = JSON.parse(e.dataTransfer.getData('groupIds') || '[]')
        } catch (_) {
            groupIds = []
        }

        const fallbackGroupId = parseInt(e.dataTransfer.getData('groupId'))
        if (!Array.isArray(groupIds) || groupIds.length === 0) {
            groupIds = fallbackGroupId ? [fallbackGroupId] : []
        }

        groupIds = [...new Set(groupIds.map(id => parseInt(id)).filter(Boolean))]
        if (groupIds.length === 0) return

        const previousGroups = groups
        const targetCategory = categoryId ? categories.find(cat => cat.id === categoryId) : null
        const groupIdSet = new Set(groupIds)

        setGroups(prev => prev.map(group => (
            groupIdSet.has(group.id)
                ? { ...group, category_id: categoryId, category_name: targetCategory?.name || null }
                : group
        )))

        try {
            const response = await fetch(`${API_URL}/groups/bulk-category`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_ids: groupIds, category_id: categoryId })
            })

            if (!response.ok) {
                const data = await response.json().catch(() => ({}))
                throw new Error(data.detail || 'Не вдалося перенести групи')
            }
            setAlert({ type: 'success', text: `Перенесено груп: ${groupIds.length}` })
        } catch (error) {
            console.error('Помилка оновлення групи:', error)
            setGroups(previousGroups)
            setAlert({ type: 'error', text: error.message || 'Помилка перенесення груп' })
            fetchGroups()
        } finally {
            setDraggedGroupIds([])
        }
    }

    const fetchGroups = async () => {
        setLoading(true)
        try {
            const response = await fetch(`${API_URL}/groups/`)
            if (response.ok) {
                const data = await response.json()
                setGroups(data)
            }
        } catch (error) {
            console.error('Помилка завантаження груп:', error)
        }
        setLoading(false)
    }

    const fetchCategories = async () => {
        try {
            const response = await fetch(`${API_URL}/categories/`)
            if (response.ok) {
                const data = await response.json()
                setCategories(data)
            }
        } catch (error) {
            console.error('Помилка завантаження категорій:', error)
        }
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

    const isServerFile = (file) => file && file.source === 'server'

    const getFileName = (file) => file.name || file.filename || file.original_filename || 'file'

    const getFileType = (file) => file.type || file.content_type || 'application/octet-stream'

    const toServerFile = (file, storage = 'template') => ({
        source: 'server',
        storage: file.storage || storage,
        stored_filename: file.stored_filename,
        name: file.filename || file.original_filename || file.name || 'file',
        filename: file.filename || file.original_filename || file.name || 'file',
        type: file.type || file.content_type || 'application/octet-stream',
        size: file.size || 0,
        template_file_id: file.id || file.template_file_id || null
    })

    const stickerKey = (sticker) => sticker?.file_id || `${sticker?.pack_short_name || ''}:${sticker?.document_id || sticker?.id || ''}`

    const appendFiles = (filesToAdd) => {
        const usableFiles = filesToAdd.filter(Boolean)
        if (usableFiles.length > 0) {
            setSelectedFiles(prev => [...prev, ...usableFiles])
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
                    setAlert({ type: 'warning', text: 'Можна додати до 12 наліпок за одну відправку.' })
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
        if (el?.insertText) {
            el.insertText(text)
            return
        }
        if (!el) {
            setMessage(prev => prev + text)
            return
        }
        const start = el.selectionStart ?? message.length
        const end = el.selectionEnd ?? message.length
        const newValue = message.slice(0, start) + text + message.slice(end)
        setMessage(newValue)
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
        appendFiles([toServerFile(data, 'import')])
        setAlert({ type: 'success', text: `Файл додано: ${data.filename}` })
    }

    const addFilesFromClipboardData = async (clipboardData, preventDefault = false) => {
        const files = []
        for (const item of Array.from(clipboardData.items || [])) {
            if (item.kind === 'file') {
                const file = item.getAsFile()
                if (file) files.push(file)
            }
        }

        if (files.length > 0) {
            if (preventDefault) preventDefault()
            appendFiles(files)
            return true
        }

        const htmlUrl = extractUrlFromHtml(clipboardData.getData('text/html'))
        const textUrl = extractUrlFromText(clipboardData.getData('text/uri-list') || clipboardData.getData('text/plain'))
        const url = htmlUrl || textUrl
        if (url) {
            if (preventDefault) preventDefault()
            await importRemoteFile(url)
            return true
        }

        return false
    }

    const importDesktopClipboardFiles = async () => {
        const desktopApi = window.pywebview?.api
        if (!desktopApi?.import_clipboard_files) return false

        const result = await desktopApi.import_clipboard_files()
        const files = Array.isArray(result?.files) ? result.files : []
        if (files.length === 0) return false

        appendFiles(files.map(file => toServerFile(file, 'import')))
        return true
    }

    const pasteFromClipboard = async (filesOnly = false) => {
        try {
            if (await importDesktopClipboardFiles()) {
                return
            }

            if (navigator.clipboard?.read) {
                try {
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
                        appendFiles(files)
                        return
                    }
                } catch (_) {}
            }

            if (!filesOnly && navigator.clipboard?.readText) {
                const text = await navigator.clipboard.readText()
                insertTextAtCursor(text)
                return
            }

            setAlert({ type: 'info', text: 'Натисніть Ctrl+V у полі повідомлення, щоб вставити файли з буфера.' })
        } catch (error) {
            setAlert({ type: 'warning', text: 'Доступ до буфера заблоковано. Спробуйте Ctrl+V у полі повідомлення.' })
        }
    }

    // Вставити обраний шаблон у поле вводу
    const insertTemplate = (selectedValue) => {
        const rawValue = selectedValue?.target ? selectedValue.target.value : selectedValue
        const id = parseInt(rawValue)
        if (!id) return
        const tmpl = templates.find(t => t.id === id)
        if (tmpl) {
            if (tmpl.text) {
                setMessage(prev => prev ? prev + '\n\n' + tmpl.text : tmpl.text)
            }
            const templateFiles = tmpl.files || []
            const existingFiles = templateFiles.filter(file => file.exists !== false)
            const missingFiles = templateFiles.filter(file => file.exists === false)
            appendFiles(existingFiles.map(file => toServerFile(file, 'template')))
            appendStickers(tmpl.stickers || [])
            if (missingFiles.length > 0) {
                setAlert({
                    type: 'warning',
                    text: `Текст шаблону додано, але файли не знайдено: ${missingFiles.map(getFileName).join(', ')}`
                })
            }
        }
    }

    // Вставити емодзі у позицію курсора
    const insertEmoji = (emoji) => {
        const el = textareaRef.current
        if (el?.insertText) {
            el.insertText(emoji)
            return
        }
        if (!el) { setMessage(prev => prev + emoji); return }
        const start = el.selectionStart
        const end = el.selectionEnd
        const newVal = message.slice(0, start) + emoji + message.slice(end)
        setMessage(newVal)
        // Повертаємо фокус та ставимо курсор після емодзі
        setTimeout(() => {
            el.focus()
            el.setSelectionRange(start + emoji.length, start + emoji.length)
        }, 0)
    }

    // Вибір/зняття групи
    const toggleGroup = (groupId) => {
        setSelectedGroups(prev =>
            prev.includes(groupId)
                ? prev.filter(id => id !== groupId)
                : [...prev, groupId]
        )
    }

    // Вибрати всі групи (з урахуванням фільтра)
    const selectAll = () => {
        setSelectedGroups(prev => {
            const filtered = filteredGroups.map(g => g.id)
            return [...new Set([...prev, ...filtered])]
        })
    }

    // Скинути вибір
    const clearSelection = () => {
        setSelectedGroups([])
    }

    // Вибрати всі групи однієї категорії
    const selectByCategory = (catId) => {
        const catGroups = catId === 0
            ? groups.filter(g => !g.category_id).map(g => g.id)
            : groups.filter(g => g.category_id === catId).map(g => g.id)
        setSelectedGroups(prev => [...new Set([...prev, ...catGroups])])
    }

    // Вибір файлів та Drag & Drop
    const dropZoneRef = useRef(null)

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
        // Ігноруємо вихід на дочірній елемент всередині зони
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
            appendFiles(droppedFiles)
            return
        }

        const htmlUrl = extractUrlFromHtml(e.dataTransfer.getData('text/html'))
        const textUrl = extractUrlFromText(e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain'))
        const url = htmlUrl || textUrl
        if (url) {
            try {
                await importRemoteFile(url)
            } catch (error) {
                setAlert({ type: 'error', text: error.message || 'Не вдалося додати файл з браузера' })
            }
        }
    }

    const addSticker = (sticker) => {
        const key = stickerKey(sticker)
        if (!key) return
        setSelectedStickers(prev => {
            if (prev.some(item => stickerKey(item) === key)) return prev
            if (prev.length >= 12) {
                setAlert({ type: 'warning', text: 'Можна додати до 12 наліпок за одну відправку.' })
                return prev
            }
            return [...prev, sticker]
        })
    }

    const handleFileSelect = (e) => {
        if (e.target.files && e.target.files.length > 0) {
            appendFiles(Array.from(e.target.files))
        }
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

    const handleContextMenu = (e) => {
        e.preventDefault()
        e.stopPropagation()
        textareaRef.current?.focus()
        setCategoryContextMenu(null)
        setContextMenu({ x: e.clientX, y: e.clientY })
    }

    const runTextCommand = (command) => {
        textareaRef.current?.focus()
        document.execCommand(command)
        setTimeout(() => {
            if (textareaRef.current) setMessage(textareaRef.current.value)
        }, 0)
        setContextMenu(null)
    }

    const clearMessageText = () => {
        setMessage('')
        textareaRef.current?.focus()
        setContextMenu(null)
    }

    const clearAttachments = () => {
        setSelectedFiles([])
        setSelectedStickers([])
        setContextMenu(null)
    }

    const removeFile = (index) => {
        setSelectedFiles(prev => prev.filter((_, i) => i !== index))
    }

    const removeSticker = (stickerToRemove) => {
        const key = typeof stickerToRemove === 'string' ? stickerToRemove : stickerKey(stickerToRemove)
        setSelectedStickers(prev => prev.filter(sticker => stickerKey(sticker) !== key))
    }

    // Відправка повідомлення
    const sendMessage = async () => {
        if (selectedGroups.length === 0) {
            setAlert({ type: 'error', text: 'Виберіть хоча б одну групу!' })
            return
        }
        if (!message.trim() && selectedFiles.length === 0 && selectedStickers.length === 0) {
            setAlert({ type: 'error', text: 'Введіть текст повідомлення, додайте файли або виберіть наліпку!' })
            return
        }

        setSending(true)
        
        // Таймаут 10 хвилин — великі файли можуть довго завантажуватись у Telegram перший раз
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 600000)
        
        try {
            const formData = new FormData()
            formData.append('group_ids', JSON.stringify(selectedGroups))
            formData.append('message', message)
            
            const storedFiles = []
            selectedFiles.forEach(file => {
                if (isServerFile(file)) {
                    storedFiles.push({
                        storage: file.storage,
                        stored_filename: file.stored_filename,
                        filename: getFileName(file),
                        type: getFileType(file)
                    })
                } else {
                    formData.append('files', file)
                }
            })
            formData.append('stored_files', JSON.stringify(storedFiles))
            formData.append('stickers', JSON.stringify(selectedStickers.map(sticker => ({
                file_id: sticker.file_id,
                document_id: sticker.document_id || sticker.id,
                emoji: sticker.emoji,
                mime_type: sticker.mime_type,
                pack_short_name: sticker.pack_short_name
            }))))

            const response = await fetch(`${API_URL}/messages/send`, {
                method: 'POST',
                body: formData,
                signal: controller.signal
            })

            if (response.ok) {
                const result = await response.json()
                const successCount = result.results.filter(r => r.success).length
                const failedResults = result.results.filter(r => !r.success)
                const elapsed = result.elapsed_seconds ? ` (${result.elapsed_seconds}с)` : ''
                
                // Отримуємо імена груп для збереження
                const groupNames = groups
                    .filter(g => selectedGroups.includes(g.id))
                    .map(g => g.name)

                // Збереження в історію
                const historyId = Date.now()
                const newHistoryItem = {
                    id: historyId,
                    timestamp: historyId,
                    dateStr: new Date().toLocaleString('uk-UA'),
                    message: message,
                    files: selectedFiles.map(getFileName),
                    stickers: selectedStickers.map(sticker => ({
                        file_id: sticker.file_id,
                        document_id: sticker.document_id || sticker.id,
                        emoji: sticker.emoji,
                        mime_type: sticker.mime_type,
                        is_animated: sticker.is_animated,
                        is_video: sticker.is_video,
                        thumb_url: sticker.thumb_url,
                        animation_url: sticker.animation_url,
                        preview_url: sticker.preview_url,
                        pack_short_name: sticker.pack_short_name
                    })),
                    groupCount: result.results.length,
                    successCount: successCount,
                    groupIds: selectedGroups,
                    groupNames: groupNames,
                    groupResults: result.results.map(r => ({
                        group_id: r.group_id,
                        group_name: r.group_name,
                        success: r.success,
                        error: r.error || null
                    }))
                }
                
                // Зберігаємо файли в IndexedDB
                if (selectedFiles.length > 0) {
                    try {
                        await saveFilesToDB(historyId, selectedFiles)
                    } catch (e) {
                        console.error('Не вдалося зберегти файли локально', e)
                    }
                }
                
                const updatedHistory = [newHistoryItem, ...history]
                setHistory(updatedHistory)
                localStorage.setItem('messageHistory', JSON.stringify(updatedHistory))

                // Детальне повідомлення про результат
                if (failedResults.length === 0) {
                    setAlert({
                        type: 'success',
                        text: `✅ Повідомлення успішно відправлено у всі ${successCount} груп!${elapsed}`
                    })
                } else {
                    const failedNames = failedResults.map(r => r.group_name).join(', ')
                    setAlert({
                        type: failedResults.length === result.results.length ? 'error' : 'warning',
                        text: `Відправлено у ${successCount} з ${result.results.length} груп${elapsed}. Помилки: ${failedNames}`
                    })
                }
                setMessage('')
                setSelectedGroups([])
                setSelectedFiles([])
                setSelectedStickers([])
            } else {
                const error = await response.json()
                let errorText = 'Помилка відправки'
                if (error.detail) {
                    errorText = Array.isArray(error.detail) 
                        ? error.detail.map(e => e.msg || JSON.stringify(e)).join(', ')
                        : error.detail
                }
                setAlert({ type: 'error', text: errorText })
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                setAlert({ type: 'error', text: 'Перевищено час очікування (10 хв). Спробуйте відправити менший обсяг файлів.' })
            } else {
                setAlert({ type: 'error', text: 'Помилка підключення до сервера' })
            }
        } finally {
            clearTimeout(timeoutId)
        }
        setSending(false)
    }

    const toggleMsgExpand = (id) => {
        setExpandedMsgIds(prev => 
            prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
        )
    }

    const repeatMessage = async (item) => {
        setMessage(item.message || '')
        if (item.groupIds) {
            setSelectedGroups(item.groupIds)
        }
        
        if (item.files && item.files.length > 0) {
            try {
                const storedFiles = await getFilesFromDB(item.id)
                if (storedFiles && storedFiles.length > 0) {
                    setSelectedFiles(storedFiles)
                    setAlert({ type: 'success', text: 'Текст, групи та файли завантажено. Можна відправляти.' })
                } else {
                    setSelectedFiles([])
                    setAlert({ type: 'error', text: 'Текст та групи завантажено. На жаль, файли вже були видалені або недоступні.' })
                }
            } catch (e) {
                setSelectedFiles([])
                setAlert({ type: 'error', text: 'Текст та групи завантажено. Помилка відновлення файлів.' })
            }
        } else {
            setSelectedFiles([])
            setAlert({ type: 'success', text: 'Текст та групи завантажено. Можна відправляти.' })
        }
        setSelectedStickers(item.stickers || [])
        window.scrollTo({ top: 0, behavior: 'smooth' })
    }

    // Автоматично ховаємо сповіщення
    useEffect(() => {
        if (alert) {
            const timer = setTimeout(() => setAlert(null), 5000)
            return () => clearTimeout(timer)
        }
    }, [alert])

    return (
        <div>
            <div className="page-header">
                <h2>📨 Відправка повідомлень</h2>
                <p>Відправте повідомлення у вибрані групи Telegram</p>
            </div>

            {/* Сповіщення */}
            {alert && (
                <div className={`alert alert-${alert.type}`}>
                    {alert.text}
                </div>
            )}

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

            {/* Вибір груп */}
            <div className="card">
                <div className="card-header" style={{ display: 'flex', flexWrap: 'wrap', gap: '15px', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flexWrap: 'wrap' }}>
                        <h3 className="card-title" style={{ margin: 0 }}>Виберіть групи</h3>
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
                    <div className="btn-group">
                        <button className="btn btn-secondary btn-sm" onClick={selectAll}>
                            Вибрати всі
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={clearSelection}>
                            Скинути вибір
                        </button>
                    </div>
                </div>

                {/* Фільтр по категоріях */}
                <div className="category-filter">
                    <button
                        className={`category-chip ${categoryFilter === null ? 'active' : ''}`}
                        onClick={() => {
                            if (categoryFilter === null && !searchQuery && isGroupsExpanded) {
                                setIsGroupsExpanded(false)
                            } else {
                                setCategoryFilter(null)
                                setIsGroupsExpanded(true)
                            }
                        }}
                    >
                        Усі
                        <span className="chip-count">{groups.length}</span>
                    </button>
                    {categories.map(cat => {
                        const count = groups.filter(g => g.category_id === cat.id).length
                        return (
                            <button
                                key={cat.id}
                                className={`category-chip ${categoryFilter === cat.id ? 'active' : ''} ${dragOverCategory === cat.id ? 'drag-over' : ''}`}
                                onClick={() => setCategoryFilter(categoryFilter === cat.id ? null : cat.id)}
                                onContextMenu={(e) => openCategoryContextMenu(e, cat)}
                                onDragOver={(e) => handleGroupDragOver(e, cat.id)}
                                onDragLeave={(e) => handleGroupDragLeave(e, cat.id)}
                                onDrop={(e) => handleGroupDrop(e, cat.id)}
                            >
                                📁 {cat.name}
                                <span className="chip-count">{count}</span>
                            </button>
                        )
                    })}
                    
                    {groups.some(g => !g.category_id) && (
                        <button
                            className={`category-chip ${categoryFilter === 0 ? 'active' : ''} ${dragOverCategory === 'none' ? 'drag-over' : ''}`}
                            onClick={() => {
                                if (categoryFilter === 0) {
                                    setCategoryFilter(null)
                                    setIsGroupsExpanded(false)
                                } else {
                                    setCategoryFilter(0)
                                    setIsGroupsExpanded(true)
                                }
                            }}
                            onDragOver={(e) => handleGroupDragOver(e, 'none')}
                            onDragLeave={(e) => handleGroupDragLeave(e, 'none')}
                            onDrop={(e) => handleGroupDrop(e, null)}
                        >
                            Без категорії
                            <span className="chip-count">{groups.filter(g => !g.category_id).length}</span>
                        </button>
                    )}

                    {/* Інлайн створення категорії */}
                    {isCreatingCategory ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                            <input
                                autoFocus
                                type="text"
                                className="form-input"
                                style={{ padding: '4px 8px', borderRadius: '16px', fontSize: '0.85rem', width: '120px', minHeight: 'auto', border: '1px solid var(--primary)' }}
                                placeholder="Назва..."
                                value={newCategoryName}
                                onChange={e => setNewCategoryName(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter') handleCreateCategory()
                                    if (e.key === 'Escape') setIsCreatingCategory(false)
                                }}
                                onBlur={handleCreateCategory}
                            />
                        </div>
                    ) : (
                        <button
                            className="category-chip"
                            style={{ borderStyle: 'dashed', padding: '6px 10px' }}
                            onClick={() => setIsCreatingCategory(true)}
                            title="Додати нову категорію"
                        >
                            +
                        </button>
                    )}
                </div>

                {loading ? (
                    <div className="loader">
                        <div className="spinner"></div>
                    </div>
                ) : groups.length === 0 ? (
                    <div className="empty-state">
                        <p>Групи не знайдено. Додайте групи в Налаштуваннях.</p>
                    </div>
                ) : (
                    <>
                        {categoryFilter === null && !searchQuery && !isGroupsExpanded ? (
                            <button 
                                className="btn btn-secondary" 
                                style={{ width: '100%', padding: '16px', display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', borderStyle: 'dashed' }}
                                onClick={() => setIsGroupsExpanded(true)}
                                type="button"
                            >
                                <span>▶ Показати всі {groups.length} груп</span>
                            </button>
                        ) : (
                            <>
                                <div className="group-checkbox-list">
                                    {filteredGroups.map(group => (
                                        <label
                                            key={group.id}
                                            draggable={true}
                                            onDragStart={(e) => handleGroupDragStart(e, group.id)}
                                            onDragEnd={handleGroupDragEnd}
                                            className={`group-checkbox-item ${selectedGroups.includes(group.id) ? 'selected' : ''}`}
                                            style={{ cursor: 'grab' }}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={selectedGroups.includes(group.id)}
                                                onChange={() => toggleGroup(group.id)}
                                            />
                                            <div style={{ minWidth: 0, overflow: 'hidden', flex: 1 }}>
                                                <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
                                                    {group.name}
                                                    {group.category_name && (
                                                        <span className="category-badge">{group.category_name}</span>
                                                    )}
                                                </div>
                                                {group.lesson_day && group.lesson_time && (
                                                    <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                                        {group.lesson_day} о {group.lesson_time}
                                                    </div>
                                                )}
                                            </div>
                                        </label>
                                    ))}
                                </div>
                                {categoryFilter === null && !searchQuery && isGroupsExpanded && (
                                    <div style={{ textAlign: 'center', marginTop: '16px' }}>
                                        <button type="button" className="btn btn-secondary btn-sm" onClick={() => setIsGroupsExpanded(false)}>
                                            ▲ Згорнути список
                                        </button>
                                    </div>
                                )}
                            </>
                        )}
                    </>
                )}

                <div style={{ marginTop: '16px', color: 'var(--text-secondary)' }}>
                    Вибрано груп: <strong>{selectedGroups.length}</strong>
                    {draggedGroupIds.length > 1 && (
                        <span className="drag-transfer-count">Переноситься: {draggedGroupIds.length}</span>
                    )}
                </div>
            </div>

            {/* Текст повідомлення */}
            <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
                    <h3 className="card-title" style={{ margin: 0 }}>Текст повідомлення та файли</h3>
                    
                    {/* Кнопка додавання файлу */}
                    <div className="message-tools-row">
                        <MagicTextButton
                            value={message}
                            setValue={setMessage}
                            context="message"
                            onAlert={setAlert}
                            disabled={sending}
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
                                style={{ fontSize: '1.5rem', opacity: 1 }}
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
                            value={message}
                            setValue={setMessage}
                        />
                        <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer', margin: 0 }}>
                            <span style={{ fontSize: '1.2em', marginRight: '4px' }}>+</span> Прикріпити
                            <input 
                                ref={fileInputRef}
                                type="file" 
                                multiple 
                                style={{ display: 'none' }} 
                                onChange={handleFileSelect}
                            />
                        </label>
                    </div>
                </div>

                {/* Панель вставки шаблону */}
                {templates.length > 0 && (
                    <div className="template-insert-bar">
                        <label>📋 Шаблон:</label>
                        <AppSelect
                            value=""
                            options={templates.map(t => ({ value: t.id, label: t.name }))}
                            placeholder="Вибрати шаблон для вставки..."
                            onChange={insertTemplate}
                            ariaLabel="Вибрати шаблон для вставки"
                        />
                    </div>
                )}

                <div 
                    ref={dropZoneRef}
                    className="form-group"
                    onDragEnter={handleDragEnter}
                        onDragOver={handleDragOver}
                        onDragLeave={handleDragLeave}
                        onDrop={handleDrop}
                        style={{
                        position: 'relative',
                        borderRadius: 'var(--radius-sm)',
                        border: isDragging ? '2px dashed var(--primary)' : '1px solid transparent',
                        transition: 'border 0.15s ease',
                        background: isDragging ? 'rgba(99, 102, 241, 0.06)' : 'transparent'
                    }}
                >
                    {/* Оверлей ЗАВЖДИ в DOM — показується/ховається через CSS, без ремонтування DOM */}
                    <div 
                        style={{
                            position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'rgba(30, 41, 59, 0.88)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--primary)',
                            fontWeight: 'bold', fontSize: '1.2rem',
                            pointerEvents: 'none', // Не перехоплює події миші — важливо!
                            zIndex: 10,
                            opacity: isDragging ? 1 : 0,
                            visibility: isDragging ? 'visible' : 'hidden',
                            transition: 'opacity 0.1s ease'
                        }}
                    >
                        📁 Відпустіть файли тут...
                    </div>
                    <RichTelegramEditor
                        ref={textareaRef}
                        className="form-textarea"
                        placeholder="Введіть текст повідомлення або перетягніть файли сюди..."
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        onPaste={handlePaste}
                        onMenuPaste={() => pasteFromClipboard(false)}
                        rows={5}
                        style={{ position: 'relative', zIndex: 1, border: 'none' }}
                    />
                </div>


                {contextMenu && (
                    <div
                        className="context-menu"
                        style={{ left: contextMenu.x, top: contextMenu.y }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <button type="button" onClick={() => runTextCommand('undo')}>Скасувати</button>
                        <button type="button" onClick={() => runTextCommand('redo')}>Повторити</button>
                        <div className="context-menu-separator" />
                        <button type="button" onClick={() => runTextCommand('cut')}>Вирізати</button>
                        <button type="button" onClick={() => runTextCommand('copy')}>Копіювати</button>
                        <button type="button" onClick={() => { setContextMenu(null); pasteFromClipboard(false) }}>Вставити</button>
                        <button type="button" onClick={() => runTextCommand('selectAll')}>Вибрати все</button>
                        <div className="context-menu-separator" />
                        <button type="button" onClick={() => { setContextMenu(null); fileInputRef.current?.click() }}>Прикріпити файл</button>
                        <button type="button" onClick={() => { setContextMenu(null); pasteFromClipboard(true) }}>Вставити файли з буфера</button>
                        <div className="context-menu-separator" />
                        <button type="button" onClick={clearMessageText}>Очистити текст</button>
                        <button type="button" onClick={clearAttachments}>Очистити вкладення</button>
                    </div>
                )}


                {/* Список вибраних файлів */}
                {selectedFiles.length > 0 && (
                    <div className="file-preview-list">
                        {selectedFiles.map((file, index) => (
                            <FilePreviewChip
                                key={`${getFileName(file)}-${index}`}
                                file={file}
                                defaultStorage="template"
                                onRemove={() => removeFile(index)}
                                onOpenError={(text) => setAlert({ type: 'warning', text })}
                            />
                        ))}
                    </div>
                )}

                {selectedStickers.length > 0 && (
                    <div className="selected-sticker-list">
                        {selectedStickers.map(sticker => (
                            <div key={sticker.file_id} className="selected-sticker-chip">
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
                        ))}
                    </div>
                )}

                <button
                    className="btn btn-primary"
                    onClick={sendMessage}
                    disabled={sending}
                    style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center' }}
                >
                    {sending ? (
                        <>
                            <span className="spinner" style={{ width: '18px', height: '18px', borderWidth: '2px' }}></span>
                            {`Відправка у ${selectedGroups.length} груп...`}
                        </>
                    ) : (
                        <>
                            <TelegramSendIcon />
                            {`Відправити${selectedGroups.length > 0 ? ` (${selectedGroups.length})` : ''}${selectedStickers.length > 0 ? ` • наліпок: ${selectedStickers.length}` : ''}`}
                        </>
                    )}
                </button>
            </div>

            {/* Історія відправлень */}
            <div className="card" style={{ marginTop: '20px' }}>
                <div 
                    className="card-header" 
                    style={{ 
                        cursor: 'pointer', 
                        marginBottom: isHistoryExpanded ? '20px' : '0', 
                        borderBottom: isHistoryExpanded ? '1px solid var(--border)' : 'none', 
                        paddingBottom: isHistoryExpanded ? '16px' : '0' 
                    }}
                    onClick={() => setIsHistoryExpanded(!isHistoryExpanded)}
                >
                    <h3 className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: 0 }}>
                        <span style={{ fontSize: '0.8em', transition: 'transform 0.2s', transform: isHistoryExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                        Історія відправлень
                    </h3>
                </div>

                {isHistoryExpanded && (
                    history.length === 0 ? (
                        <div style={{ color: 'var(--text-secondary)' }}>Історія порожня. Вона зберігатиметься тут останні 7 днів.</div>
                    ) : (
                        <div className="table-container">
                            <table className="table">
                                <thead>
                                    <tr>
                                        <th>Дата</th>
                                        <th>Групи</th>
                                        <th>Повідомлення</th>
                                        <th>Файли / наліпки</th>
                                        <th>Успішність</th>
                                        <th>Дія</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {history.map(item => {
                                        const isMsgExpanded = expandedMsgIds.includes(item.id);
                                        const groupResults = item.groupResults || (item.groupNames || []).map((name, i) => ({
                                            group_name: name,
                                            success: i < (item.successCount || 0),
                                            error: null
                                        }));
                                        return (
                                        <tr key={item.id}>
                                            <td style={{ whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{item.dateStr}</td>
                                            <td style={{ maxWidth: '150px' }}>
                                                {groupResults.length > 0 ? (
                                                    <div className="history-file-list">
                                                        {groupResults.map((g, i) => (
                                                            <span
                                                                key={i}
                                                                style={{
                                                                    fontSize: '0.85em',
                                                                    background: 'var(--bg-card)',
                                                                    padding: '3px 6px',
                                                                    borderRadius: '4px',
                                                                    border: '1px solid var(--border)',
                                                                    display: 'flex',
                                                                    alignItems: 'center',
                                                                    gap: '6px',
                                                                    minWidth: 0
                                                                }}
                                                                title={g.error ? `${g.group_name}: ${g.error}` : g.group_name}
                                                            >
                                                                <span style={{ color: g.success ? 'var(--success)' : 'var(--danger)', fontWeight: 700, flex: '0 0 auto' }}>
                                                                    {g.success ? '✓' : '✕'}
                                                                </span>
                                                                <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                                    {g.group_name}
                                                                </span>
                                                            </span>
                                                        ))}
                                                    </div>
                                                ) : <span style={{ color: 'var(--text-secondary)' }}>-</span>}
                                            </td>
                                            <td style={{ maxWidth: '300px' }}>
                                                {item.message ? (
                                                    <div>
                                                        <div style={{ 
                                                            overflow: isMsgExpanded ? 'visible' : 'hidden', 
                                                            textOverflow: isMsgExpanded ? 'clip' : 'ellipsis', 
                                                            whiteSpace: isMsgExpanded ? 'pre-wrap' : 'nowrap',
                                                            maxHeight: isMsgExpanded ? 'none' : '1.5em'
                                                        }}>
                                                            {item.message}
                                                        </div>
                                                        {item.message.length > 40 && (
                                                            <button 
                                                                onClick={() => toggleMsgExpand(item.id)}
                                                                style={{ background: 'none', border: 'none', color: 'var(--primary)', padding: 0, marginTop: '4px', cursor: 'pointer', fontSize: '0.85em' }}
                                                            >
                                                                {isMsgExpanded ? 'Згорнути' : 'Розгорнути'}
                                                            </button>
                                                        )}
                                                    </div>
                                                ) : <span style={{ color: 'var(--text-secondary)' }}>Без тексту</span>}
                                            </td>
                                            <td>
                                                {(item.files && item.files.length > 0) || (item.stickers && item.stickers.length > 0) ? (
                                                    <div className="history-file-list">
                                                        {(item.files || []).map((f, i) => (
                                                            <HistoryFileChip
                                                                key={`${item.id}-${i}-${f}`}
                                                                historyId={item.id}
                                                                fileIndex={i}
                                                                fileName={f}
                                                                onOpenError={(text) => setAlert({ type: 'warning', text })}
                                                            />
                                                        ))}
                                                        {(item.stickers || []).map((sticker, i) => (
                                                            <span key={`${item.id}-sticker-${i}`} className="history-sticker-chip" title="Наліпка">
                                                                <StickerPreview sticker={sticker} />
                                                            </span>
                                                        ))}
                                                    </div>
                                                ) : <span style={{ color: 'var(--text-secondary)' }}>-</span>}
                                            </td>
                                            <td>
                                                <span className={`badge ${item.successCount === item.groupCount ? 'badge-success' : 'badge-warning'}`}>
                                                    {item.successCount} / {item.groupCount}
                                                </span>
                                            </td>
                                            <td>
                                                <button 
                                                    className="btn btn-secondary btn-sm"
                                                    onClick={() => repeatMessage(item)}
                                                >
                                                    Повторити
                                                </button>
                                            </td>
                                        </tr>
                                    )})}
                                </tbody>
                            </table>
                        </div>
                    )
                )}
            </div>
        </div>
    )
}

export default SendMessage

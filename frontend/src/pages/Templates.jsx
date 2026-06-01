import { useState, useEffect, useRef } from 'react'
import EmojiPicker from '../components/EmojiPicker'
import FilePreviewChip from '../components/FilePreviewChip'
import StickerIcon from '../components/StickerIcon'
import StickerPicker from '../components/StickerPicker'
import StickerPreview from '../components/StickerPreview'
import TelegramTextToolbar from '../components/TelegramTextToolbar'
import RichTelegramEditor from '../components/RichTelegramEditor'
import MagicTextButton from '../components/MagicTextButton'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

function Templates() {
    const [templates, setTemplates] = useState([])
    const [loading, setLoading] = useState(true)
    const [alert, setAlert] = useState(null)
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingTemplate, setEditingTemplate] = useState(null)
    const [formName, setFormName] = useState('')
    const [formText, setFormText] = useState('')
    const [existingFiles, setExistingFiles] = useState([])
    const [formFiles, setFormFiles] = useState([])
    const [saving, setSaving] = useState(false)
    const [showEmoji, setShowEmoji] = useState(false)
    const [showStickers, setShowStickers] = useState(false)
    const [selectedStickers, setSelectedStickers] = useState([])
    const [isDragging, setIsDragging] = useState(false)
    const textareaRef = useRef(null)
    const fileInputRef = useRef(null)
    const dropZoneRef = useRef(null)
    const emojiButtonRef = useRef(null)
    const stickerButtonRef = useRef(null)

    useEffect(() => {
        if (!alert) return
        const timer = setTimeout(() => setAlert(null), 4000)
        return () => clearTimeout(timer)
    }, [alert])

    useEffect(() => {
        fetchTemplates()
    }, [])

    const fetchTemplates = async () => {
        setLoading(true)
        try {
            const response = await fetch(`${API_URL}/templates/`)
            const data = await response.json()
            setTemplates(data)
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка завантаження шаблонів' })
        }
        setLoading(false)
    }

    const resetModalState = () => {
        setEditingTemplate(null)
        setFormName('')
        setFormText('')
        setExistingFiles([])
        setFormFiles([])
        setShowEmoji(false)
        setShowStickers(false)
        setSelectedStickers([])
        setIsDragging(false)
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const openCreateModal = () => {
        resetModalState()
        setIsModalOpen(true)
    }

    const openEditModal = (template) => {
        setEditingTemplate(template)
        setFormName(template.name)
        setFormText(template.text || '')
        setExistingFiles(template.files || [])
        setFormFiles([])
        setShowEmoji(false)
        setShowStickers(false)
        setSelectedStickers(template.stickers || [])
        setIsDragging(false)
        setIsModalOpen(true)
    }

    const closeModal = () => {
        setIsModalOpen(false)
        resetModalState()
    }

    const isServerFile = (file) => file && file.source === 'server'

    const getFileName = (file) => file?.name || file?.filename || file?.original_filename || 'file'

    const getFileType = (file) => file?.type || file?.content_type || 'application/octet-stream'

    const toServerFile = (file, storage = 'import') => ({
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

    const addSticker = (sticker) => {
        const key = stickerKey(sticker)
        if (!key) return

        setSelectedStickers(prev => {
            if (prev.some(item => stickerKey(item) === key)) return prev
            if (prev.length >= 12) {
                setAlert({ type: 'warning', text: 'Можна додати до 12 наліпок в один шаблон.' })
                return prev
            }
            return [...prev, sticker]
        })
    }

    const removeSticker = (sticker) => {
        const key = stickerKey(sticker)
        setSelectedStickers(prev => prev.filter(item => stickerKey(item) !== key))
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
            setAlert({ type: 'info', text: 'Натисніть Ctrl+V у полі тексту шаблона, щоб вставити файл з буфера.' })
        } catch (error) {
            setAlert({ type: 'warning', text: 'Доступ до буфера заблоковано. Спробуйте Ctrl+V у полі тексту шаблона.' })
        }
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

    const removeExistingFile = (id) => {
        setExistingFiles(prev => prev.filter(file => file.id !== id))
    }

    const removeNewFile = (index) => {
        setFormFiles(prev => prev.filter((_, i) => i !== index))
    }

    const insertEmoji = (emoji) => {
        const el = textareaRef.current
        if (el?.insertText) {
            el.insertText(emoji)
            return
        }
        if (!el) {
            setFormText(prev => prev + emoji)
            return
        }
        const start = el.selectionStart
        const end = el.selectionEnd
        const newVal = formText.slice(0, start) + emoji + formText.slice(end)
        setFormText(newVal)
        setTimeout(() => {
            el.focus()
            el.setSelectionRange(start + emoji.length, start + emoji.length)
        }, 0)
    }

    const saveTemplate = async () => {
        if (!formName.trim()) {
            setAlert({ type: 'error', text: 'Введіть назву шаблону!' })
            return
        }
        if (!formText.trim() && existingFiles.length === 0 && formFiles.length === 0 && selectedStickers.length === 0) {
            setAlert({ type: 'error', text: 'Додайте текст, файл або наліпку до шаблону!' })
            return
        }

        setSaving(true)
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

            payload.append('name', formName.trim())
            payload.append('text', formText.trim())
            payload.append('keep_file_ids', JSON.stringify(existingFiles.map(file => file.id)))
            payload.append('stored_files', JSON.stringify(storedFiles))
            payload.append('stickers', JSON.stringify(selectedStickers.map(sticker => ({
                file_id: sticker.file_id,
                document_id: sticker.document_id || sticker.id,
                id: sticker.id,
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

            const url = editingTemplate
                ? `${API_URL}/templates/${editingTemplate.id}`
                : `${API_URL}/templates/`
            const method = editingTemplate ? 'PUT' : 'POST'

            const response = await fetch(url, { method, body: payload })
            const data = await response.json().catch(() => ({}))

            if (response.ok) {
                setAlert({ type: 'success', text: editingTemplate ? 'Шаблон оновлено!' : 'Шаблон створено!' })
                closeModal()
                fetchTemplates()
            } else {
                setAlert({ type: 'error', text: data.detail || 'Помилка збереження шаблону' })
            }
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка підключення до сервера' })
        }
        setSaving(false)
    }

    const deleteTemplate = async (template) => {
        if (!window.confirm(`Видалити шаблон "${template.name}"?`)) return

        try {
            const response = await fetch(`${API_URL}/templates/${template.id}`, { method: 'DELETE' })
            if (response.ok) {
                setAlert({ type: 'success', text: 'Шаблон видалено' })
                fetchTemplates()
            } else {
                setAlert({ type: 'error', text: 'Помилка видалення' })
            }
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка підключення до сервера' })
        }
    }

    return (
        <div>
            <div className="page-header">
                <h2>Шаблони повідомлень</h2>
                <p>Збережіть готові тексти та файли для швидкого використання</p>
            </div>

            {alert && (
                <div className={`alert alert-${alert.type}`}>
                    {alert.text}
                </div>
            )}

            <div className="card">
                <div className="card-header">
                    <h3 className="card-title">Мої шаблони</h3>
                    <button className="btn btn-primary btn-sm" onClick={openCreateModal}>
                        + Новий шаблон
                    </button>
                </div>

                {loading ? (
                    <div className="loader">
                        <div className="spinner"></div>
                    </div>
                ) : templates.length === 0 ? (
                    <div className="empty-state">
                        <div style={{ fontSize: '3rem', marginBottom: '12px' }}>📋</div>
                        <p style={{ fontWeight: 600, marginBottom: '8px' }}>Шаблонів ще немає</p>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                            Натисніть "Новий шаблон", щоб створити першу заготовку
                        </p>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {templates.map(template => (
                            <div key={template.id} className="template-card">
                                <div className="template-card-info">
                                    <div className="template-card-name">{template.name}</div>
                                    <div className="template-card-text">{template.text}</div>
                                    {template.files && template.files.length > 0 && (
                                        <div className="template-files">
                                            {template.files.map(file => (
                                                <FilePreviewChip
                                                    key={file.id}
                                                    file={file}
                                                    defaultStorage="template"
                                                    removable={false}
                                                    compact
                                                    onOpenError={(text) => setAlert({ type: 'warning', text })}
                                                />
                                            ))}
                                        </div>
                                    )}
                                    {template.stickers && template.stickers.length > 0 && (
                                        <div className="template-files">
                                            {template.stickers.map((sticker, index) => (
                                                <span
                                                    key={stickerKey(sticker) || `template-sticker-${index}`}
                                                    className="history-sticker-chip"
                                                    title="Наліпка"
                                                >
                                                    <StickerPreview sticker={sticker} />
                                                </span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div className="template-card-actions">
                                    <button
                                        className="btn btn-secondary btn-sm"
                                        onClick={() => openEditModal(template)}
                                    >
                                        Редагувати
                                    </button>
                                    <button
                                        className="btn btn-danger btn-sm"
                                        onClick={() => deleteTemplate(template)}
                                    >
                                        Видалити
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {isModalOpen && (
                <div className="modal-overlay" onClick={closeModal}>
                    <div className="modal" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <h3 className="modal-title">
                                {editingTemplate ? 'Редагувати шаблон' : 'Новий шаблон'}
                            </h3>
                            <button className="modal-close" onClick={closeModal}>×</button>
                        </div>

                        <div className="form-group">
                            <label className="form-label">Назва шаблону</label>
                            <input
                                type="text"
                                className="form-input"
                                placeholder='Наприклад: "Посилання на Zoom"'
                                value={formName}
                                onChange={e => setFormName(e.target.value)}
                            />
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
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', gap: '8px', flexWrap: 'wrap' }}>
                                    <label className="form-label" style={{ margin: 0 }}>Текст шаблону</label>
                                    <div className="message-tools-row">
                                        <MagicTextButton
                                            value={formText}
                                            setValue={setFormText}
                                            context="template"
                                            onAlert={setAlert}
                                            disabled={saving}
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
                                            value={formText}
                                            setValue={setFormText}
                                        />
                                    </div>
                                </div>
                                <RichTelegramEditor
                                    ref={textareaRef}
                                    className="form-textarea"
                                    placeholder="Введіть текст шаблону або перетягніть файли сюди..."
                                    value={formText}
                                    onChange={e => setFormText(e.target.value)}
                                    onPaste={handlePaste}
                                    rows={6}
                                    style={{ position: 'relative', zIndex: 1 }}
                                />
                            </div>

                            <div className="form-group">
                                <label className="form-label">Файли шаблону</label>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
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

                                {(existingFiles.length > 0 || formFiles.length > 0) && (
                                    <div className="template-files" style={{ marginTop: '10px' }}>
                                        {existingFiles.map(file => (
                                            <FilePreviewChip
                                                key={`existing-${file.id}`}
                                                file={file}
                                                defaultStorage="template"
                                                onRemove={() => removeExistingFile(file.id)}
                                                onOpenError={(text) => setAlert({ type: 'warning', text })}
                                            />
                                        ))}
                                        {formFiles.map((file, index) => (
                                            <FilePreviewChip
                                                key={`new-${getFileName(file)}-${index}`}
                                                file={file}
                                                defaultStorage="import"
                                                onRemove={() => removeNewFile(index)}
                                                onOpenError={(text) => setAlert({ type: 'warning', text })}
                                            />
                                        ))}
                                    </div>
                                )}
                                {selectedStickers.length > 0 && (
                                    <div className="selected-sticker-list">
                                        {selectedStickers.map((sticker, index) => (
                                            <div
                                                key={stickerKey(sticker) || `selected-sticker-${index}`}
                                                className="selected-sticker-chip"
                                            >
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
                            </div>
                        </div>

                        <div className="btn-group">
                            <button
                                className="btn btn-primary"
                                onClick={saveTemplate}
                                disabled={saving}
                            >
                                {saving ? 'Збереження...' : 'Зберегти'}
                            </button>
                            <button className="btn btn-secondary" onClick={closeModal}>
                                Скасувати
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default Templates

import { useState, useEffect, useRef } from 'react'
import FilePreviewChip from '../components/FilePreviewChip'
import MessageComposer from '../components/MessageComposer'
import StickerPreview from '../components/StickerPreview'
import { useToast } from '../components/ToastProvider'
import { useApi } from '../hooks/useApi'
import { useClipboardFiles } from '../hooks/useClipboardFiles'
import { useDragDropFiles } from '../hooks/useDragDropFiles'
import { getFileName, getFileType, isServerFile, stickerKey, toServerFile } from '../utils/fileInputs'


function Templates() {
    const [templates, setTemplates] = useState([])
    const [loading, setLoading] = useState(true)
    const { showToast } = useToast()
    const setAlert = showToast
    const apiClient = useApi()
    const [isModalOpen, setIsModalOpen] = useState(false)
    const [editingTemplate, setEditingTemplate] = useState(null)
    const [formName, setFormName] = useState('')
    const [formText, setFormText] = useState('')
    const [existingFiles, setExistingFiles] = useState([])
    const [formFiles, setFormFiles] = useState([])
    const [saving, setSaving] = useState(false)
    const [selectedStickers, setSelectedStickers] = useState([])
    const textareaRef = useRef(null)
    const fileInputRef = useRef(null)
    const dropZoneRef = useRef(null)

    useEffect(() => {
        fetchTemplates()
    }, [])

    const fetchTemplates = async () => {
        setLoading(true)
        try {
            const data = await apiClient.get('/templates/', { toast: false })
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
        setSelectedStickers(template.stickers || [])
        setIsDragging(false)
        setIsModalOpen(true)
    }

    const closeModal = () => {
        setIsModalOpen(false)
        resetModalState()
    }

    const appendFormFiles = (filesToAdd) => {
        const usableFiles = Array.from(filesToAdd || []).filter(Boolean)
        if (usableFiles.length > 0) {
            setFormFiles(prev => [...prev, ...usableFiles])
        }
    }

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

    const importRemoteFile = async (url, filename = '') => {
        const data = await apiClient.post('/messages/import-url', { url, filename }, { toast: false })
        appendFormFiles([toServerFile(data, 'import')])
        setAlert({ type: 'success', text: `\u0424\u0430\u0439\u043b \u0434\u043e\u0434\u0430\u043d\u043e: ${data.filename}` })
    }

    const { addFilesFromClipboardData, pasteFromClipboard } = useClipboardFiles({
        appendFiles: appendFormFiles,
        importRemoteFile,
        showToast: setAlert,
        hintText: '\u041d\u0430\u0442\u0438\u0441\u043d\u0456\u0442\u044c Ctrl+V \u0443 \u043f\u043e\u043b\u0456 \u0442\u0435\u043a\u0441\u0442\u0443 \u0448\u0430\u0431\u043b\u043e\u043d\u0430, \u0449\u043e\u0431 \u0432\u0441\u0442\u0430\u0432\u0438\u0442\u0438 \u0444\u0430\u0439\u043b \u0437 \u0431\u0443\u0444\u0435\u0440\u0430.',
        blockedText: '\u0414\u043e\u0441\u0442\u0443\u043f \u0434\u043e \u0431\u0443\u0444\u0435\u0440\u0430 \u0437\u0430\u0431\u043b\u043e\u043a\u043e\u0432\u0430\u043d\u043e. \u0421\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 Ctrl+V \u0443 \u043f\u043e\u043b\u0456 \u0442\u0435\u043a\u0441\u0442\u0443 \u0448\u0430\u0431\u043b\u043e\u043d\u0430.'
    })

    const { isDragging, setIsDragging, dragHandlers } = useDragDropFiles({
        dropZoneRef,
        appendFiles: appendFormFiles,
        importRemoteFile,
        showToast: setAlert,
        errorText: '\u041d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u0434\u043e\u0434\u0430\u0442\u0438 \u0444\u0430\u0439\u043b \u0437 \u0431\u0440\u0430\u0443\u0437\u0435\u0440\u0430'
    })

    const handlePaste = async (e) => {
        try {
            const handled = await addFilesFromClipboardData(e.clipboardData, () => e.preventDefault())
            if (handled) return
        } catch (error) {
            e.preventDefault()
            setAlert({ type: 'error', text: error.message || '\u041d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u0432\u0441\u0442\u0430\u0432\u0438\u0442\u0438 \u0444\u0430\u0439\u043b \u0437 \u0431\u0443\u0444\u0435\u0440\u0430' })
        }
    }


    const removeExistingFile = (id) => {
        setExistingFiles(prev => prev.filter(file => file.id !== id))
    }

    const removeNewFile = (index) => {
        setFormFiles(prev => prev.filter((_, i) => i !== index))
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
                ? `/templates/${editingTemplate.id}`
                : '/templates/'
            const method = editingTemplate ? 'PUT' : 'POST'

            await apiClient.form(url, payload, method, { toast: false })
            setAlert({ type: 'success', text: editingTemplate ? '\u0428\u0430\u0431\u043b\u043e\u043d \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e!' : '\u0428\u0430\u0431\u043b\u043e\u043d \u0441\u0442\u0432\u043e\u0440\u0435\u043d\u043e!' })
            closeModal()
            fetchTemplates()
        } catch (error) {
            setAlert({ type: 'error', text: 'Помилка підключення до сервера' })
        }
        setSaving(false)
    }

    const deleteTemplate = async (template) => {
        if (!window.confirm(`Видалити шаблон "${template.name}"?`)) return

        try {
            await apiClient.delete(`/templates/${template.id}`, { toast: false })
            setAlert({ type: 'success', text: '\u0428\u0430\u0431\u043b\u043e\u043d \u0432\u0438\u0434\u0430\u043b\u0435\u043d\u043e' })
            fetchTemplates()
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

                        <MessageComposer
                            value={formText}
                            setValue={setFormText}
                            context="template"
                            onAlert={setAlert}
                            disabled={saving}
                            label={'\u0422\u0435\u043a\u0441\u0442 \u0448\u0430\u0431\u043b\u043e\u043d\u0443'}
                            placeholder={'\u0412\u0432\u0435\u0434\u0456\u0442\u044c \u0442\u0435\u043a\u0441\u0442 \u0448\u0430\u0431\u043b\u043e\u043d\u0443 \u0430\u0431\u043e \u043f\u0435\u0440\u0435\u0442\u044f\u0433\u043d\u0456\u0442\u044c \u0444\u0430\u0439\u043b\u0438 \u0441\u044e\u0434\u0438...'}
                            rows={6}
                            editorRef={textareaRef}
                            fileInputRef={fileInputRef}
                            onFileSelect={handleFileSelect}
                            pasteFromClipboard={pasteFromClipboard}
                            onPaste={handlePaste}
                            dropZoneRef={dropZoneRef}
                            dragHandlers={dragHandlers}
                            isDragging={isDragging}
                            dropLabel={'\u0412\u0456\u0434\u043f\u0443\u0441\u0442\u0456\u0442\u044c \u0444\u0430\u0439\u043b\u0438 \u0442\u0443\u0442'}
                            existingFiles={existingFiles}
                            files={formFiles}
                            selectedStickers={selectedStickers}
                            onAddSticker={addSticker}
                            onRemoveSticker={removeSticker}
                            onRemoveExistingFile={(file) => removeExistingFile(file.id)}
                            onRemoveFile={(_, index) => removeNewFile(index)}
                            defaultFileStorage="import"
                            existingFileStorage="template"
                            onOpenFileError={(text) => setAlert({ type: 'warning', text })}
                        />

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

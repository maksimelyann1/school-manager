import { useRef, useState } from 'react'
import EmojiPicker from './EmojiPicker'
import FilePreviewChip from './FilePreviewChip'
import MagicTextButton from './MagicTextButton'
import RichTelegramEditor from './RichTelegramEditor'
import StickerIcon from './StickerIcon'
import StickerPicker from './StickerPicker'
import StickerPreview from './StickerPreview'
import TelegramTextToolbar from './TelegramTextToolbar'
import { getFileName, isServerFile, stickerKey } from '../utils/fileInputs'

function MessageComposer({
    value,
    setValue,
    context = 'message',
    disabled = false,
    onAlert,
    label,
    placeholder,
    rows = 5,
    editorRef,
    className = '',
    editorClassName = 'form-textarea',
    editorStyle,
    allowMagic = true,
    allowEmoji = true,
    allowStickers = true,
    allowFiles = true,
    allowFormatting = true,
    fileInputRef,
    onFileSelect,
    pasteFromClipboard,
    onPaste,
    onMenuPaste,
    onContextMenu,
    dropZoneRef,
    dragHandlers,
    isDragging = false,
    dropLabel = 'Відпустіть файли тут',
    files = [],
    existingFiles = [],
    selectedStickers = [],
    onAddSticker,
    onRemoveSticker,
    onRemoveFile,
    onRemoveExistingFile,
    defaultFileStorage = 'import',
    existingFileStorage = 'template',
    onOpenFileError,
    toolbarEnd,
    beforeEditor,
    afterEditor,
    placeholderTokens
}) {
    const internalEditorRef = useRef(null)
    const internalFileInputRef = useRef(null)
    const emojiButtonRef = useRef(null)
    const stickerButtonRef = useRef(null)
    const [showEmoji, setShowEmoji] = useState(false)
    const [showStickers, setShowStickers] = useState(false)

    const activeEditorRef = editorRef || internalEditorRef
    const activeFileInputRef = fileInputRef || internalFileInputRef

    const updateValue = (nextValue) => {
        if (typeof setValue === 'function') {
            setValue(nextValue)
        }
    }

    const insertTextAtCursor = (text) => {
        if (!text) return
        const editor = activeEditorRef.current
        if (editor?.insertText) {
            editor.insertText(text)
            return
        }

        const currentValue = String(value || '')
        const start = editor?.selectionStart ?? currentValue.length
        const end = editor?.selectionEnd ?? currentValue.length
        const nextValue = currentValue.slice(0, start) + text + currentValue.slice(end)
        updateValue(nextValue)

        window.setTimeout(() => {
            editor?.focus?.()
            const cursor = start + text.length
            editor?.setSelectionRange?.(cursor, cursor)
        }, 0)
    }

    const handleEmojiSelect = (emoji) => {
        insertTextAtCursor(emoji)
    }

    const handleFileSelect = (event) => {
        onFileSelect?.(event)
        event.target.value = ''
    }

    const handlePasteFromClipboard = () => {
        pasteFromClipboard?.(true)
    }

    const hasDrag = Boolean(dragHandlers)
    const hasFiles = existingFiles.length > 0 || files.length > 0
    const hasStickers = selectedStickers.length > 0

    return (
        <div className={`message-composer ${className}`}>
            {(label || allowFiles) && (
                <div className="message-composer-head">
                    {label && <label className="form-label message-composer-label">{label}</label>}
                    {allowFiles && (
                        <div className="composer-toolbar-files" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <button
                                type="button"
                                className="btn btn-secondary btn-sm composer-file-btn"
                                onClick={() => activeFileInputRef.current?.click()}
                                disabled={disabled}
                            >
                                + Додати файли
                            </button>
                            {pasteFromClipboard && (
                                <button
                                    type="button"
                                    className="btn btn-secondary btn-sm composer-file-btn"
                                    onClick={handlePasteFromClipboard}
                                    disabled={disabled}
                                >
                                    Вставити з буфера
                                </button>
                            )}
                            <input
                                ref={activeFileInputRef}
                                type="file"
                                multiple
                                style={{ display: 'none' }}
                                onChange={handleFileSelect}
                            />
                        </div>
                    )}
                </div>
            )}

            {(allowFormatting || allowMagic || allowEmoji || allowStickers || toolbarEnd) && (
                <div className="message-composer-toolbar">
                    {allowFormatting && (
                        <div className="composer-toolbar-format">
                            <TelegramTextToolbar
                                textareaRef={activeEditorRef}
                                value={value}
                                setValue={updateValue}
                            />
                        </div>
                    )}
                    <div className="message-composer-actions">
                        {allowMagic && (
                            <MagicTextButton
                                value={value}
                                setValue={updateValue}
                                context={context}
                                onAlert={onAlert}
                                disabled={disabled}
                            />
                        )}
                        {allowEmoji && (
                            <div className="emoji-picker-wrap">
                                <button
                                    ref={emojiButtonRef}
                                    className="emoji-trigger-btn"
                                    onClick={() => {
                                        setShowEmoji(prev => !prev)
                                        setShowStickers(false)
                                    }}
                                    title="Додати смайлик"
                                    type="button"
                                    style={{ fontSize: '1.25rem', opacity: 1, padding: '2px 4px' }}
                                >
                                    😊
                                </button>
                                {showEmoji && (
                                    <EmojiPicker
                                        anchorRef={emojiButtonRef}
                                        onSelect={handleEmojiSelect}
                                        onClose={() => setShowEmoji(false)}
                                    />
                                )}
                            </div>
                        )}
                        {allowStickers && (
                            <div className="sticker-picker-wrap">
                                <button
                                    ref={stickerButtonRef}
                                    className="emoji-trigger-btn"
                                    onClick={() => {
                                        setShowStickers(prev => !prev)
                                        setShowEmoji(false)
                                    }}
                                    title="Додати наліпку"
                                    type="button"
                                    style={{ opacity: 1, padding: '2px 4px' }}
                                >
                                    <StickerIcon />
                                </button>
                                {showStickers && (
                                    <StickerPicker
                                        anchorRef={stickerButtonRef}
                                        onSelect={onAddSticker}
                                        onClose={() => setShowStickers(false)}
                                    />
                                )}
                            </div>
                        )}
                        {toolbarEnd}
                    </div>
                </div>
            )}

            {beforeEditor}

            <div
                ref={dropZoneRef}
                className={`message-composer-dropzone ${isDragging ? 'dragging' : ''}`}
                {...(hasDrag ? dragHandlers : {})}
            >
                <div className="message-composer-drop-overlay" aria-hidden="true">
                    {dropLabel}
                </div>
                <RichTelegramEditor
                    ref={activeEditorRef}
                    className={editorClassName}
                    placeholder={placeholder}
                    value={value}
                    onChange={(event) => updateValue(event.target.value)}
                    onPaste={onPaste}
                    onMenuPaste={onMenuPaste}
                    onContextMenu={onContextMenu}
                    rows={rows}
                    style={editorStyle}
                    placeholderTokens={placeholderTokens}
                />
            </div>

            {hasFiles && (
                <div className="file-preview-list">
                    {existingFiles.map(file => (
                        <FilePreviewChip
                            key={`existing-${file.id || getFileName(file)}`}
                            file={file}
                            defaultStorage={existingFileStorage}
                            onRemove={onRemoveExistingFile ? () => onRemoveExistingFile(file) : undefined}
                            onOpenError={onOpenFileError}
                        />
                    ))}
                    {files.map((file, index) => (
                        <FilePreviewChip
                            key={`file-${getFileName(file)}-${index}`}
                            file={file}
                            defaultStorage={isServerFile(file) ? file.storage : defaultFileStorage}
                            onRemove={onRemoveFile ? () => onRemoveFile(file, index) : undefined}
                            onOpenError={onOpenFileError}
                        />
                    ))}
                </div>
            )}

            {hasStickers && (
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
                                onClick={() => onRemoveSticker?.(sticker)}
                                title="Прибрати наліпку"
                            >
                                ×
                            </button>
                        </div>
                    ))}
                </div>
            )}

            {afterEditor}
        </div>
    )
}

export default MessageComposer

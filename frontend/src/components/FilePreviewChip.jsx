import { useEffect, useMemo, useState } from 'react'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'
const VIDEO_THUMBNAIL_LIMIT = 2
const MAX_VIDEO_THUMBNAIL_BYTES = 80 * 1024 * 1024

let activeVideoThumbnails = 0
const videoThumbnailQueue = []

const releaseVideoSlot = () => {
    activeVideoThumbnails = Math.max(0, activeVideoThumbnails - 1)
    if (videoThumbnailQueue.length > 0 && activeVideoThumbnails < VIDEO_THUMBNAIL_LIMIT) {
        activeVideoThumbnails += 1
        const resolve = videoThumbnailQueue.shift()
        resolve(releaseVideoSlot)
    }
}

const acquireVideoSlot = () => new Promise(resolve => {
    if (activeVideoThumbnails < VIDEO_THUMBNAIL_LIMIT) {
        activeVideoThumbnails += 1
        resolve(releaseVideoSlot)
    } else {
        videoThumbnailQueue.push(resolve)
    }
})

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'gif'])
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'avi', 'mkv'])

const getFileName = (file) => file?.name || file?.filename || file?.original_filename || 'file'

const getFileType = (file) => file?.type || file?.content_type || 'application/octet-stream'

const getExtension = (file) => {
    const name = getFileName(file)
    const part = name.includes('.') ? name.split('.').pop() : ''
    return (part || '').toLowerCase()
}

const isServerFile = (file) => Boolean(file?.stored_filename)

const isImageFile = (file) => {
    const type = getFileType(file).toLowerCase()
    return type.startsWith('image/') || IMAGE_EXTENSIONS.has(getExtension(file))
}

const isVideoFile = (file) => {
    const type = getFileType(file).toLowerCase()
    return type.startsWith('video/') || VIDEO_EXTENSIONS.has(getExtension(file))
}

const previewUrlForServerFile = (file, defaultStorage) => {
    const storage = file.storage || defaultStorage || 'template'
    const params = new URLSearchParams({
        storage,
        stored_filename: file.stored_filename
    })
    return `${API_URL}/files/preview?${params.toString()}`
}

const generateVideoThumbnail = (sourceUrl, isCrossOrigin) => new Promise((resolve, reject) => {
    const video = document.createElement('video')
    const canvas = document.createElement('canvas')
    let settled = false

    const cleanup = () => {
        video.pause()
        video.removeAttribute('src')
        video.load()
    }

    const finish = (value) => {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        cleanup()
        resolve(value)
    }

    const fail = () => {
        if (settled) return
        settled = true
        clearTimeout(timeout)
        cleanup()
        reject(new Error('thumbnail failed'))
    }

    const drawFrame = () => {
        try {
            const width = video.videoWidth
            const height = video.videoHeight
            if (!width || !height) {
                fail()
                return
            }

            const maxSide = 96
            const scale = Math.min(maxSide / width, maxSide / height, 1)
            canvas.width = Math.max(1, Math.round(width * scale))
            canvas.height = Math.max(1, Math.round(height * scale))
            const context = canvas.getContext('2d')
            context.drawImage(video, 0, 0, canvas.width, canvas.height)
            finish(canvas.toDataURL('image/jpeg', 0.76))
        } catch (error) {
            fail()
        }
    }

    const timeout = setTimeout(fail, 3500)
    video.muted = true
    video.playsInline = true
    video.preload = 'metadata'
    if (isCrossOrigin) {
        video.crossOrigin = 'anonymous'
    }
    video.addEventListener('loadeddata', drawFrame, { once: true })
    video.addEventListener('error', fail, { once: true })
    video.src = sourceUrl
    video.load()
})

function FilePreviewChip({
    file,
    defaultStorage = 'template',
    onRemove,
    onOpenError,
    removable = true,
    compact = false
}) {
    const [preview, setPreview] = useState({ kind: 'icon', url: '' })
    const fileName = getFileName(file)
    const extension = getExtension(file)
    const fileType = getFileType(file)
    const serverBacked = isServerFile(file)
    const missing = file?.exists === false
    const canOpenInSystemApp = serverBacked && !missing
    const kind = useMemo(() => {
        if (isImageFile(file)) return 'image'
        if (isVideoFile(file)) return 'video'
        return 'document'
    }, [file])

    useEffect(() => {
        let cancelled = false
        let objectUrl = null

        setPreview({ kind: 'icon', url: '' })

        if (!file || missing) {
            return () => {}
        }

        const sourceUrl = serverBacked
            ? previewUrlForServerFile(file, defaultStorage)
            : URL.createObjectURL(file)

        if (!serverBacked) {
            objectUrl = sourceUrl
        }

        if (kind === 'image') {
            setPreview({ kind: 'image', url: sourceUrl })
            return () => {
                cancelled = true
                if (objectUrl) URL.revokeObjectURL(objectUrl)
            }
        }

        if (kind !== 'video' || (file.size || 0) > MAX_VIDEO_THUMBNAIL_BYTES) {
            if (objectUrl) URL.revokeObjectURL(objectUrl)
            return () => {
                cancelled = true
            }
        }

        let releaseSlot = null
        acquireVideoSlot()
            .then(async release => {
                releaseSlot = release
                if (cancelled) {
                    release()
                    releaseSlot = null
                    return
                }
                try {
                    const thumbnail = await generateVideoThumbnail(sourceUrl, serverBacked)
                    if (!cancelled) {
                        setPreview({ kind: 'image', url: thumbnail })
                    }
                } catch (error) {
                    if (!cancelled) {
                        setPreview({ kind: 'icon', url: '' })
                    }
                } finally {
                    if (objectUrl) {
                        URL.revokeObjectURL(objectUrl)
                        objectUrl = null
                    }
                    if (releaseSlot) {
                        releaseSlot()
                    }
                    releaseSlot = null
                }
            })

        return () => {
            cancelled = true
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl)
                objectUrl = null
            }
        }
    }, [defaultStorage, file, kind, missing, serverBacked])

    const openFile = async () => {
        if (missing) {
            onOpenError?.('Файл не знайдено на диску.')
            return
        }
        if (!canOpenInSystemApp) {
            onOpenError?.('Відкриття у системній програмі доступне для файлів, які вже збережені у шаблоні або кеші.')
            return
        }

        try {
            const response = await fetch(`${API_URL}/files/open`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    storage: file.storage || defaultStorage || 'template',
                    stored_filename: file.stored_filename
                })
            })
            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || 'Не вдалося відкрити файл')
            }
        } catch (error) {
            onOpenError?.(error.message || 'Не вдалося відкрити файл')
        }
    }

    const label = missing
        ? `${fileName} - файл не знайдено`
        : canOpenInSystemApp
            ? `${fileName} - відкрити у системній програмі`
            : fileName

    return (
        <div
            className={`file-preview-chip ${compact ? 'compact' : ''} ${missing ? 'missing' : ''} ${canOpenInSystemApp ? 'openable' : ''} ${!removable || !onRemove ? 'no-remove' : ''}`}
            title={label}
            onClick={openFile}
            role={canOpenInSystemApp ? 'button' : undefined}
            tabIndex={canOpenInSystemApp ? 0 : undefined}
            onKeyDown={(e) => {
                if (canOpenInSystemApp && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    openFile()
                }
            }}
        >
            <div className="file-preview-thumb">
                {preview.kind === 'image' && preview.url ? (
                    <img src={preview.url} alt="" loading="lazy" draggable={false} />
                ) : (
                    <span className={`file-preview-icon ${kind}`}>
                        {kind === 'image' ? 'IMG' : kind === 'video' ? 'VID' : (extension || 'FILE').slice(0, 4).toUpperCase()}
                    </span>
                )}
            </div>
            <div className="file-preview-info">
                <span className="file-preview-name">{fileName}</span>
                <span className="file-preview-meta">
                    {serverBacked && <span className="file-preview-badge">cache</span>}
                    {kind === 'video' && <span className="file-preview-badge">кадр</span>}
                    {!serverBacked && <span>{fileType.split('/')[0] || 'file'}</span>}
                </span>
            </div>
            {removable && onRemove && (
                <button
                    type="button"
                    className="file-preview-remove"
                    onClick={(e) => {
                        e.stopPropagation()
                        onRemove()
                    }}
                    title="Прибрати файл"
                >
                    ×
                </button>
            )}
        </div>
    )
}

export default FilePreviewChip

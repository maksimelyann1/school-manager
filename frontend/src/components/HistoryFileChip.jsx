import { useEffect, useRef, useState } from 'react'
import { getFilesFromDB } from '../utils/db'

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'
const MAX_VIDEO_THUMBNAIL_BYTES = 80 * 1024 * 1024

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'webp', 'bmp', 'gif'])
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'mov', 'm4v', 'avi', 'mkv'])

const getFileName = (file, fallback = 'file') => file?.name || file?.filename || file?.original_filename || fallback
const getFileType = (file) => file?.type || file?.content_type || 'application/octet-stream'
const isServerFile = (file) => Boolean(file?.stored_filename)

const getExtensionFromName = (name) => {
    const part = (name || '').includes('.') ? name.split('.').pop() : ''
    return (part || '').toLowerCase()
}

const getKind = (file, fallbackName) => {
    const type = getFileType(file).toLowerCase()
    const extension = getExtensionFromName(getFileName(file, fallbackName))
    if (type.startsWith('image/') || IMAGE_EXTENSIONS.has(extension)) return 'image'
    if (type.startsWith('video/') || VIDEO_EXTENSIONS.has(extension)) return 'video'
    return 'document'
}

const getTypeLabel = (fileName, file) => {
    const kind = getKind(file, fileName)
    if (kind === 'image') return 'IMG'
    if (kind === 'video') return 'VID'
    const extension = getExtensionFromName(fileName)
    return (extension || 'FILE').slice(0, 4).toUpperCase()
}

const previewUrlForServerFile = (file) => {
    const params = new URLSearchParams({
        storage: file.storage || 'import',
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
            if (!video.videoWidth || !video.videoHeight) {
                fail()
                return
            }
            const maxSide = 190
            const scale = Math.min(maxSide / video.videoWidth, maxSide / video.videoHeight, 1)
            canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
            canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
            finish(canvas.toDataURL('image/jpeg', 0.78))
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

function HistoryFileChip({ historyId, fileIndex, fileName, onOpenError }) {
    const rootRef = useRef(null)
    const [loadedFile, setLoadedFile] = useState(null)
    const [isHovering, setIsHovering] = useState(false)
    const [isOpening, setIsOpening] = useState(false)
    const [preview, setPreview] = useState({ status: 'idle', url: '', kind: 'document' })
    const [popoverPosition, setPopoverPosition] = useState({ top: 0, left: 0 })

    const loadFile = async () => {
        if (loadedFile) return loadedFile
        const files = await getFilesFromDB(historyId)
        const file = files?.[fileIndex]
        if (!file) {
            throw new Error('Файл вже недоступний в історії.')
        }
        setLoadedFile(file)
        return file
    }

    const updatePopoverPosition = () => {
        const rect = rootRef.current?.getBoundingClientRect()
        if (!rect) return
        const preferredLeft = rect.right + 10
        const left = preferredLeft + 220 < window.innerWidth
            ? preferredLeft
            : Math.max(12, rect.left - 230)
        const top = Math.min(Math.max(12, rect.top - 24), window.innerHeight - 210)
        setPopoverPosition({ top, left })
    }

    useEffect(() => {
        if (!isHovering) return undefined

        let cancelled = false
        let objectUrl = null

        const buildPreview = async () => {
            updatePopoverPosition()
            setPreview({ status: 'loading', url: '', kind: 'document' })

            try {
                const file = await loadFile()
                if (cancelled) return

                const kind = getKind(file, fileName)
                if (kind === 'document') {
                    setPreview({ status: 'unsupported', url: '', kind })
                    return
                }

                const sourceUrl = isServerFile(file)
                    ? previewUrlForServerFile(file)
                    : URL.createObjectURL(file)

                if (!isServerFile(file)) {
                    objectUrl = sourceUrl
                }

                if (kind === 'image') {
                    setPreview({ status: 'ready', url: sourceUrl, kind })
                    return
                }

                if ((file.size || 0) > MAX_VIDEO_THUMBNAIL_BYTES) {
                    setPreview({ status: 'unsupported', url: '', kind })
                    return
                }

                const thumbnail = await generateVideoThumbnail(sourceUrl, isServerFile(file))
                if (!cancelled) {
                    setPreview({ status: 'ready', url: thumbnail, kind })
                }
                if (objectUrl) {
                    URL.revokeObjectURL(objectUrl)
                    objectUrl = null
                }
            } catch (error) {
                if (!cancelled) {
                    setPreview({ status: 'missing', url: '', kind: 'document' })
                }
            }
        }

        buildPreview()

        return () => {
            cancelled = true
            if (objectUrl) {
                URL.revokeObjectURL(objectUrl)
            }
        }
    }, [isHovering, historyId, fileIndex, fileName])

    const openFile = async () => {
        if (isOpening) return
        setIsOpening(true)

        try {
            const file = await loadFile()
            let response

            if (isServerFile(file)) {
                response = await fetch(`${API_URL}/files/open`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        storage: file.storage || 'import',
                        stored_filename: file.stored_filename
                    })
                })
            } else {
                const formData = new FormData()
                formData.append('file', file, getFileName(file, fileName))
                response = await fetch(`${API_URL}/files/open-upload`, {
                    method: 'POST',
                    body: formData
                })
            }

            const data = await response.json().catch(() => ({}))
            if (!response.ok) {
                throw new Error(data.detail || 'Не вдалося відкрити файл.')
            }
        } catch (error) {
            onOpenError?.(error.message || 'Не вдалося відкрити файл.')
        } finally {
            setIsOpening(false)
        }
    }

    const typeLabel = getTypeLabel(fileName, loadedFile)
    const kind = getKind(loadedFile, fileName)

    return (
        <>
            <button
                ref={rootRef}
                type="button"
                className={`history-file-chip ${kind}`}
                title={`${fileName} - відкрити у системній програмі`}
                onMouseEnter={() => setIsHovering(true)}
                onMouseLeave={() => setIsHovering(false)}
                onFocus={() => setIsHovering(true)}
                onBlur={() => setIsHovering(false)}
                onClick={openFile}
                disabled={isOpening}
            >
                <span className="history-file-type">{typeLabel}</span>
                <span className="history-file-name">{fileName}</span>
            </button>
            {isHovering && preview.status !== 'unsupported' && (
                <div
                    className={`history-file-popover ${preview.status}`}
                    style={{ top: popoverPosition.top, left: popoverPosition.left }}
                >
                    {preview.status === 'ready' && preview.url ? (
                        <img src={preview.url} alt="" draggable={false} />
                    ) : preview.status === 'missing' ? (
                        <span>Файл вже недоступний</span>
                    ) : (
                        <span>Завантаження...</span>
                    )}
                </div>
            )}
        </>
    )
}

export default HistoryFileChip

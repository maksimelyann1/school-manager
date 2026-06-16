import { useCallback, useRef, useState } from 'react'
import { filesFromDataTransfer, urlFromTransferData } from '../utils/fileInputs'

export function useDragDropFiles({
    dropZoneRef,
    appendFiles,
    importRemoteFile,
    showToast,
    errorText = 'Не вдалося додати файл з браузера'
} = {}) {
    const [isDragging, setIsDragging] = useState(false)
    const dragDepthRef = useRef(0)

    const onDragEnter = useCallback((event) => {
        event.preventDefault()
        event.stopPropagation()
        dragDepthRef.current += 1
        setIsDragging(true)
    }, [])

    const onDragOver = useCallback((event) => {
        event.preventDefault()
        event.stopPropagation()
    }, [])

    const onDragLeave = useCallback((event) => {
        event.preventDefault()
        event.stopPropagation()
        if (dropZoneRef?.current && dropZoneRef.current.contains(event.relatedTarget)) return
        dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
        if (dragDepthRef.current === 0) setIsDragging(false)
    }, [dropZoneRef])

    const onDrop = useCallback(async (event) => {
        event.preventDefault()
        event.stopPropagation()
        dragDepthRef.current = 0
        setIsDragging(false)

        const files = filesFromDataTransfer(event.dataTransfer)
        if (files.length > 0) {
            appendFiles?.(files)
            return true
        }

        const url = urlFromTransferData(event.dataTransfer)
        if (!url || !importRemoteFile) return false

        try {
            await importRemoteFile(url)
            return true
        } catch (error) {
            showToast?.({ type: 'error', text: error.message || errorText })
            return false
        }
    }, [appendFiles, errorText, importRemoteFile, showToast])

    return {
        isDragging,
        setIsDragging,
        dragHandlers: {
            onDragEnter,
            onDragOver,
            onDragLeave,
            onDrop
        }
    }
}

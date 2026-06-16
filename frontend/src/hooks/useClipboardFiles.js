import { useCallback } from 'react'
import {
    filesFromClipboardData,
    filesFromNavigatorClipboard,
    toServerFile,
    urlFromTransferData
} from '../utils/fileInputs'

export function useClipboardFiles({
    appendFiles,
    importRemoteFile,
    insertText,
    showToast,
    includeText = false,
    useDesktopClipboard = false,
    defaultStorage = 'import',
    hintText = 'Натисніть Ctrl+V у полі тексту, щоб вставити файл з буфера.',
    blockedText = 'Доступ до буфера заблоковано. Спробуйте Ctrl+V у полі тексту.'
} = {}) {
    const notify = useCallback((type, text) => {
        if (typeof showToast === 'function') showToast({ type, text })
    }, [showToast])

    const addFilesFromClipboardData = useCallback(async (clipboardData, preventDefault) => {
        const files = filesFromClipboardData(clipboardData)
        if (files.length > 0) {
            preventDefault?.()
            appendFiles?.(files)
            return true
        }

        const url = urlFromTransferData(clipboardData)
        if (url && importRemoteFile) {
            preventDefault?.()
            await importRemoteFile(url)
            return true
        }

        return false
    }, [appendFiles, importRemoteFile])

    const pasteFromClipboard = useCallback(async (filesOnly = false) => {
        try {
            if (useDesktopClipboard && window.pywebview?.api?.import_clipboard_files) {
                const result = await window.pywebview.api.import_clipboard_files()
                const files = Array.isArray(result?.files) ? result.files : []
                if (files.length > 0) {
                    appendFiles?.(files.map(file => toServerFile(file, defaultStorage)))
                    return true
                }
            }

            const files = await filesFromNavigatorClipboard()
            if (files.length > 0) {
                appendFiles?.(files)
                return true
            }

            if (!filesOnly && includeText && navigator.clipboard?.readText) {
                const text = await navigator.clipboard.readText()
                if (text) {
                    insertText?.(text)
                    return true
                }
            }

            notify('info', hintText)
            return false
        } catch (_) {
            notify('warning', blockedText)
            return false
        }
    }, [appendFiles, blockedText, defaultStorage, hintText, includeText, insertText, notify, useDesktopClipboard])

    return {
        addFilesFromClipboardData,
        pasteFromClipboard
    }
}

export const isServerFile = (file) => file && file.source === 'server'

export const getFileName = (file) => (
    file?.name || file?.filename || file?.original_filename || 'file'
)

export const getFileType = (file) => (
    file?.type || file?.content_type || 'application/octet-stream'
)

export const toServerFile = (file, storage = 'import') => ({
    source: 'server',
    storage: file?.storage || storage,
    stored_filename: file?.stored_filename,
    name: file?.filename || file?.original_filename || file?.name || 'file',
    filename: file?.filename || file?.original_filename || file?.name || 'file',
    type: file?.type || file?.content_type || 'application/octet-stream',
    size: file?.size || 0,
    template_file_id: file?.id || file?.template_file_id || null
})

export const stickerKey = (sticker) => (
    sticker?.file_id || `${sticker?.pack_short_name || ''}:${sticker?.document_id || sticker?.id || ''}`
)

export function extractUrlFromHtml(html) {
    if (!html) return ''
    const doc = new DOMParser().parseFromString(html, 'text/html')
    return doc.querySelector('img, video, source')?.getAttribute('src')
        || doc.querySelector('a')?.getAttribute('href')
        || ''
}

export function extractUrlFromText(text) {
    const match = (text || '').match(/https?:\/\/[^\s"'<>]+/i)
    return match ? match[0] : ''
}

export function filesFromDataTransfer(dataTransfer) {
    return Array.from(dataTransfer?.files || []).filter(file => file.size > 0)
}

export function filesFromClipboardData(clipboardData) {
    const files = []
    for (const item of Array.from(clipboardData?.items || [])) {
        if (item.kind === 'file') {
            const file = item.getAsFile()
            if (file) files.push(file)
        }
    }
    return files
}

export function urlFromTransferData(data) {
    return extractUrlFromHtml(data?.getData?.('text/html'))
        || extractUrlFromText(data?.getData?.('text/uri-list') || data?.getData?.('text/plain'))
}

export async function filesFromNavigatorClipboard() {
    if (!navigator.clipboard?.read) return []

    const items = await navigator.clipboard.read()
    const files = []
    for (const item of items) {
        for (const type of item.types || []) {
            if (type.startsWith('image/') || type.startsWith('video/') || type === 'application/pdf') {
                const blob = await item.getType(type)
                const extension = type.split('/')[1]?.replace('jpeg', 'jpg') || 'bin'
                files.push(new File([blob], `clipboard_${Date.now()}.${extension}`, { type }))
                break
            }
        }
    }
    return files
}

const FORMAT_MAP = {
    bold: {
        id: 'bold',
        label: 'B',
        title: 'Жирний',
        menuLabel: 'Жирний',
        shortcut: 'Ctrl+B',
        before: '**',
        after: '**',
        placeholder: 'жирний текст'
    },
    italic: {
        id: 'italic',
        label: 'I',
        title: 'Курсив',
        menuLabel: 'Курсив',
        shortcut: 'Ctrl+I',
        before: '__',
        after: '__',
        placeholder: 'курсив'
    },
    underline: {
        id: 'underline',
        label: 'U',
        title: 'Підкреслений',
        menuLabel: 'Підкреслений',
        shortcut: 'Ctrl+U',
        before: '--',
        after: '--',
        placeholder: 'підкреслений текст'
    },
    strike: {
        id: 'strike',
        label: 'S',
        title: 'Закреслений',
        menuLabel: 'Закреслений',
        shortcut: 'Ctrl+Shift+X',
        before: '~~',
        after: '~~',
        placeholder: 'закреслений текст'
    },
    quote: {
        id: 'quote',
        label: '❝',
        title: 'Цитата',
        menuLabel: 'Цитата',
        shortcut: 'Ctrl+Shift+.',
        placeholder: 'цитата'
    },
    monospace: {
        id: 'monospace',
        label: 'M',
        title: 'Моноширинний',
        menuLabel: 'Моноширинний',
        shortcut: 'Ctrl+Shift+M',
        placeholder: 'код'
    },
    spoiler: {
        id: 'spoiler',
        label: '▣',
        title: 'Спойлер',
        menuLabel: 'Спойлер',
        shortcut: 'Ctrl+Shift+P',
        before: '||',
        after: '||',
        placeholder: 'спойлер'
    },
    link: {
        id: 'link',
        label: '↗',
        title: 'Створити посилання',
        menuLabel: 'Створити посилання',
        shortcut: 'Ctrl+K',
        placeholder: 'посилання'
    },
    date: {
        id: 'date',
        label: 'D',
        title: 'Дата',
        menuLabel: 'Дата',
        shortcut: 'Ctrl+Shift+D'
    },
    clear: {
        id: 'clear',
        label: 'Tx',
        title: 'Без форматування',
        menuLabel: 'Без форматування',
        shortcut: 'Ctrl+Shift+N'
    }
}

export const TELEGRAM_FORMATS = [
    FORMAT_MAP.bold,
    FORMAT_MAP.italic,
    FORMAT_MAP.underline,
    FORMAT_MAP.strike,
    FORMAT_MAP.quote,
    FORMAT_MAP.monospace,
    FORMAT_MAP.spoiler,
    FORMAT_MAP.link,
    FORMAT_MAP.date,
    FORMAT_MAP.clear
]

export const TELEGRAM_QUICK_FORMATS = [
    FORMAT_MAP.bold,
    FORMAT_MAP.italic,
    FORMAT_MAP.underline,
    FORMAT_MAP.strike,
    FORMAT_MAP.quote,
    FORMAT_MAP.monospace,
    FORMAT_MAP.spoiler,
    FORMAT_MAP.link,
    FORMAT_MAP.date,
    FORMAT_MAP.clear
]

const HTML_ENTITY_MAP = {
    '&amp;': '&',
    '&lt;': '<',
    '&gt;': '>',
    '&quot;': '"',
    '&#39;': "'"
}

export const getTelegramFormat = (formatId) => FORMAT_MAP[formatId] || null

export const escapeTelegramHtml = (value) => String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

export const normalizeTelegramUrl = (rawUrl) => {
    const url = String(rawUrl || '').trim()
    if (!url) return ''
    if (/^(https?:|mailto:|tg:)/i.test(url)) return url
    return `https://${url}`
}

export const currentDateText = () => {
    try {
        return new Intl.DateTimeFormat('uk-UA', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date()).replace(',', '')
    } catch (_) {
        return new Date().toLocaleString()
    }
}

export const isTelegramFormatElement = (element) => {
    if (element?.isContentEditable && element.dataset.telegramFormatting === 'true') {
        return true
    }

    return !!(
        element
        && (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement)
        && element.dataset.telegramFormatting === 'true'
        && !element.disabled
        && !element.readOnly
    )
}

export const getEditableSelectionText = (element) => {
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
        const start = element.selectionStart ?? 0
        const end = element.selectionEnd ?? 0
        return element.value.slice(Math.min(start, end), Math.max(start, end))
    }
    if (element?.isContentEditable) {
        const selection = window.getSelection()
        if (!selection || selection.rangeCount === 0) return ''
        const range = selection.getRangeAt(0)
        return element.contains(range.commonAncestorContainer) ? selection.toString() : ''
    }
    return window.getSelection()?.toString() || ''
}

export const stripTelegramFormatting = (value) => {
    let text = String(value || '')

    text = text.replace(/<a\b[^>]*>(.*?)<\/a>/gis, '$1')
    text = text.replace(/<\/?(b|strong|i|em|u|s|del|strike|code|pre|blockquote|spoiler)(?:\s+[^>]*)?>/gi, '')
    text = text.replace(/\[(.*?)\]\((.*?)\)/gs, '$1')
    text = text.replace(/\*\*(.*?)\*\*/gs, '$1')
    text = text.replace(/__(.*?)__/gs, '$1')
    text = text.replace(/--(.*?)--/gs, '$1')
    text = text.replace(/~~(.*?)~~/gs, '$1')
    text = text.replace(/\|\|(.*?)\|\|/gs, '$1')
    text = text.replace(/```[^\n`]*\n?([\s\S]*?)\n?```/g, '$1')
    text = text.replace(/`([^`]+)`/g, '$1')

    return text.replace(/&(amp|lt|gt|quot|#39);/g, (entity) => HTML_ENTITY_MAP[entity] || entity)
}

export const buildTelegramFormattedText = (formatId, selectedText, options = {}) => {
    const format = getTelegramFormat(formatId)
    if (!format) return null

    if (formatId === 'clear') {
        return stripTelegramFormatting(selectedText)
    }

    if (formatId === 'date') {
        return currentDateText()
    }

    const text = selectedText || format.placeholder || ''

    if (formatId === 'link') {
        const normalizedUrl = normalizeTelegramUrl(options.url)
        if (!normalizedUrl) return null
        return `[${text}](${normalizedUrl})`
    }

    if (formatId === 'quote') {
        return `<blockquote>${escapeTelegramHtml(text)}</blockquote>`
    }

    if (formatId === 'monospace') {
        if (text.includes('\n')) return `\`\`\`\n${text}\n\`\`\``
        return `\`${text}\``
    }

    return `${format.before}${text}${format.after}`
}

export const applyTelegramFormatToValue = (value, start, end, formatId, options = {}) => {
    const safeValue = String(value || '')
    const selectionStart = Math.max(0, Math.min(start ?? safeValue.length, safeValue.length))
    const selectionEnd = Math.max(selectionStart, Math.min(end ?? selectionStart, safeValue.length))
    const selectedText = safeValue.slice(selectionStart, selectionEnd)
    const nextText = buildTelegramFormattedText(formatId, selectedText, options)

    if (nextText === null) return null

    const nextValue = `${safeValue.slice(0, selectionStart)}${nextText}${safeValue.slice(selectionEnd)}`
    const cursor = selectionStart + nextText.length

    return {
        value: nextValue,
        selectionStart: cursor,
        selectionEnd: cursor
    }
}

const setNativeValue = (element, value) => {
    const prototype = element instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype
    const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value')
    descriptor?.set?.call(element, value)
}

export const applyTelegramFormatToElement = (element, formatId, options = {}) => {
    if (!isTelegramFormatElement(element)) return false

    if (element.__telegramEditorApi?.applyFormat) {
        return element.__telegramEditorApi.applyFormat(formatId, options)
    }

    const start = element.selectionStart ?? element.value.length
    const end = element.selectionEnd ?? start
    const preparedOptions = { ...options }

    if (formatId === 'link' && !preparedOptions.url) {
        const url = window.prompt('Вставте посилання', 'https://')
        if (url === null) return false
        preparedOptions.url = url
    }

    const result = applyTelegramFormatToValue(element.value, start, end, formatId, preparedOptions)
    if (!result) return false

    element.focus()
    setNativeValue(element, result.value)
    element.dispatchEvent(new Event('input', { bubbles: true }))

    requestAnimationFrame(() => {
        element.focus()
        element.setSelectionRange(result.selectionStart, result.selectionEnd)
    })

    return true
}

export const applyTelegramFormatToControlledInput = ({
    textareaRef,
    value,
    setValue,
    formatId,
    options = {}
}) => {
    const element = textareaRef.current
    const currentValue = String(value || '')
    const start = element?.selectionStart ?? currentValue.length
    const end = element?.selectionEnd ?? start
    const preparedOptions = { ...options }

    if (formatId === 'link' && !preparedOptions.url) {
        const url = window.prompt('Вставте посилання', 'https://')
        if (url === null) return false
        preparedOptions.url = url
    }

    const result = applyTelegramFormatToValue(currentValue, start, end, formatId, preparedOptions)
    if (!result) return false

    setValue(result.value)

    requestAnimationFrame(() => {
        if (!element) return
        element.focus()
        element.setSelectionRange(result.selectionStart, result.selectionEnd)
    })

    return true
}

export const handleTelegramFormattingKeyDown = (event, textareaRef, value, setValue) => {
    const usesModifier = event.ctrlKey || event.metaKey
    if (!usesModifier) return false

    const key = event.key.toLowerCase()
    const code = event.code
    const shift = event.shiftKey
    let formatId = ''

    if (!shift && key === 'b') formatId = 'bold'
    else if (!shift && key === 'i') formatId = 'italic'
    else if (!shift && key === 'u') formatId = 'underline'
    else if (!shift && key === 'k') formatId = 'link'
    else if (shift && key === 'x') formatId = 'strike'
    else if (shift && key === 'm') formatId = 'monospace'
    else if (shift && key === 'p') formatId = 'spoiler'
    else if (shift && key === 'd') formatId = 'date'
    else if (shift && key === 'n') formatId = 'clear'
    else if (shift && (key === '.' || code === 'Period')) formatId = 'quote'

    if (!formatId) return false

    event.preventDefault()
    applyTelegramFormatToControlledInput({ textareaRef, value, setValue, formatId })
    return true
}

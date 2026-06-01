import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
    TELEGRAM_FORMATS,
    currentDateText,
    escapeTelegramHtml,
    getTelegramFormat,
    normalizeTelegramUrl,
    stripTelegramFormatting
} from '../utils/telegramFormatting'

const SUPPORTED_HTML_RE = /<\/?(?:a|b|strong|i|em|u|s|del|strike|code|pre|blockquote|spoiler)\b/i
const BLOCK_TAGS = new Set(['div', 'p', 'li'])

const escapeAttr = (value) => escapeTelegramHtml(value).replace(/"/g, '&quot;')

const markdownToEditorHtml = (value, { preserveNewlines = true } = {}) => {
    let html = escapeTelegramHtml(value).replace(/\r\n/g, '\n')

    html = html.replace(/```(?:[^\n`]*)\n?([\s\S]*?)\n?```/g, (_, code) => (
        `<pre><code>${code}</code></pre>`
    ))
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>')
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|mailto:[^)\s]+|tg:[^)\s]+)\)/g, (_, text, url) => (
        `<a href="${escapeAttr(url)}">${text}</a>`
    ))
    html = html.replace(/\*\*([\s\S]+?)\*\*/g, '<strong>$1</strong>')
    html = html.replace(/__([\s\S]+?)__/g, '<em>$1</em>')
    html = html.replace(/--([\s\S]+?)--/g, '<u>$1</u>')
    html = html.replace(/~~([\s\S]+?)~~/g, '<s>$1</s>')
    html = html.replace(/\|\|([\s\S]+?)\|\|/g, '<span class="telegram-spoiler" data-telegram-format="spoiler">$1</span>')

    return preserveNewlines ? html.replace(/\n/g, '<br>') : html
}

const sanitizeEditorNode = (node, { inCode = false } = {}) => {
    if (node.nodeType === Node.TEXT_NODE) {
        const text = node.nodeValue || ''
        return inCode ? escapeTelegramHtml(text).replace(/\r\n/g, '\n').replace(/\n/g, '<br>') : markdownToEditorHtml(text)
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const tag = node.tagName.toLowerCase()
    if (tag === 'br') return '<br>'

    const childHtml = Array.from(node.childNodes)
        .map(child => sanitizeEditorNode(child, { inCode: inCode || tag === 'code' || tag === 'pre' }))
        .join('')

    if (tag === 'b' || tag === 'strong') return `<strong>${childHtml}</strong>`
    if (tag === 'i' || tag === 'em') return `<em>${childHtml}</em>`
    if (tag === 'u') return `<u>${childHtml}</u>`
    if (tag === 's' || tag === 'del' || tag === 'strike') return `<s>${childHtml}</s>`
    if (tag === 'code') return `<code>${childHtml}</code>`
    if (tag === 'pre') return `<pre>${childHtml}</pre>`
    if (tag === 'blockquote') return `<blockquote>${childHtml}</blockquote>`
    if (tag === 'spoiler') return `<span class="telegram-spoiler" data-telegram-format="spoiler">${childHtml}</span>`
    if (tag === 'a') {
        const href = normalizeTelegramUrl(node.getAttribute('href') || '')
        return href ? `<a href="${escapeAttr(href)}">${childHtml}</a>` : childHtml
    }

    if (BLOCK_TAGS.has(tag)) return `${childHtml}<br>`
    return childHtml
}

const telegramMarkupToEditorHtml = (value) => {
    const raw = String(value || '')
    if (!raw) return ''

    if (!SUPPORTED_HTML_RE.test(raw)) {
        return markdownToEditorHtml(raw)
    }

    const doc = new DOMParser().parseFromString(raw.replace(/\r\n/g, '\n').replace(/\n/g, '<br>'), 'text/html')
    return Array.from(doc.body.childNodes).map(child => sanitizeEditorNode(child)).join('')
}

const serializeEditorNode = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
        return escapeTelegramHtml((node.nodeValue || '').replace(/\u00a0/g, ' '))
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const tag = node.tagName.toLowerCase()
    if (tag === 'br') return '\n'

    const inner = Array.from(node.childNodes).map(serializeEditorNode).join('')

    if (tag === 'b' || tag === 'strong') return `<b>${inner}</b>`
    if (tag === 'i' || tag === 'em') return `<i>${inner}</i>`
    if (tag === 'u') return `<u>${inner}</u>`
    if (tag === 's' || tag === 'del' || tag === 'strike') return `<s>${inner}</s>`
    if (tag === 'code') return `<code>${inner}</code>`
    if (tag === 'pre') return `<pre>${inner}</pre>`
    if (tag === 'blockquote') return `<blockquote>${inner}</blockquote>`
    if (tag === 'a') {
        const href = normalizeTelegramUrl(node.getAttribute('href') || '')
        return href ? `<a href="${escapeAttr(href)}">${inner}</a>` : inner
    }
    if (node.dataset?.telegramFormat === 'spoiler' || tag === 'spoiler') {
        return `<spoiler>${inner}</spoiler>`
    }
    if (BLOCK_TAGS.has(tag)) return `${inner}\n`

    return inner
}

const editorHtmlToTelegramMarkup = (element) => {
    if (!element) return ''
    return Array.from(element.childNodes)
        .map(serializeEditorNode)
        .join('')
        .replace(/\n{3,}/g, '\n\n')
        .replace(/\n$/, '')
}

const isRangeInside = (root, range) => {
    if (!root || !range) return false
    const container = range.commonAncestorContainer
    return container === root || root.contains(container)
}

const placeCaretAfter = (node) => {
    const range = document.createRange()
    range.setStartAfter(node)
    range.collapse(true)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(range)
    return range
}

const buildTextFragment = (text) => {
    const fragment = document.createDocumentFragment()
    const parts = String(text || '').replace(/\r\n/g, '\n').split('\n')
    let lastNode = null

    parts.forEach((part, index) => {
        if (index > 0) {
            lastNode = document.createElement('br')
            fragment.appendChild(lastNode)
        }
        if (part) {
            lastNode = document.createTextNode(part)
            fragment.appendChild(lastNode)
        }
    })

    if (!lastNode) {
        lastNode = document.createTextNode('')
        fragment.appendChild(lastNode)
    }

    return { fragment, lastNode }
}

function RichTelegramEditor({
    value,
    onChange,
    onPaste,
    onMenuPaste,
    placeholder = '',
    rows = 5,
    className = 'form-textarea',
    style = {}
}, ref) {
    const editorRef = useRef(null)
    const savedRangeRef = useRef(null)
    const lastValueRef = useRef(String(value || ''))
    const initialHtml = useMemo(() => telegramMarkupToEditorHtml(value), [])
    const [isEmpty, setIsEmpty] = useState(!String(value || '').trim())
    const [isFocused, setIsFocused] = useState(false)

    const updateEmptyState = () => {
        const editor = editorRef.current
        const text = (editor?.textContent || '').replace(/\u200b/g, '').trim()
        setIsEmpty(!editor || text.length === 0)
    }

    const saveSelection = () => {
        const editor = editorRef.current
        const selection = window.getSelection()
        if (!editor || !selection || selection.rangeCount === 0) return
        const range = selection.getRangeAt(0)
        if (isRangeInside(editor, range)) {
            savedRangeRef.current = range.cloneRange()
        }
    }

    const focusEditor = () => {
        const editor = editorRef.current
        if (!editor) return
        editor.focus()
    }

    const ensureRange = () => {
        const editor = editorRef.current
        if (!editor) return null

        const selection = window.getSelection()
        if (selection?.rangeCount) {
            const activeRange = selection.getRangeAt(0)
            if (isRangeInside(editor, activeRange)) {
                savedRangeRef.current = activeRange.cloneRange()
                return activeRange
            }
        }

        if (savedRangeRef.current && isRangeInside(editor, savedRangeRef.current)) {
            const restored = savedRangeRef.current.cloneRange()
            editor.focus()
            selection.removeAllRanges()
            selection.addRange(restored)
            return restored
        }

        editor.focus()
        const range = document.createRange()
        range.selectNodeContents(editor)
        range.collapse(false)
        selection.removeAllRanges()
        selection.addRange(range)
        savedRangeRef.current = range.cloneRange()
        return range
    }

    const emitChange = () => {
        const editor = editorRef.current
        const nextValue = editorHtmlToTelegramMarkup(editor)
        lastValueRef.current = nextValue
        updateEmptyState()
        onChange?.({ target: { value: nextValue } })
    }

    const selectNodeContents = (node) => {
        const range = document.createRange()
        range.selectNodeContents(node)
        const selection = window.getSelection()
        selection.removeAllRanges()
        selection.addRange(range)
        savedRangeRef.current = range.cloneRange()
    }

    const insertPlainText = (text) => {
        const range = ensureRange()
        if (!range) return false

        range.deleteContents()
        const { fragment, lastNode } = buildTextFragment(text)
        range.insertNode(fragment)
        placeCaretAfter(lastNode)
        saveSelection()
        emitChange()
        return true
    }

    const applyFormat = (formatId, options = {}) => {
        const editor = editorRef.current
        const format = getTelegramFormat(formatId)
        const range = ensureRange()
        if (!editor || !format || !range) return false

        if (formatId === 'clear') {
            const text = range.collapsed
                ? stripTelegramFormatting(editorHtmlToTelegramMarkup(editor))
                : stripTelegramFormatting(range.toString())

            if (range.collapsed) {
                editor.textContent = text
                const nextRange = document.createRange()
                nextRange.selectNodeContents(editor)
                nextRange.collapse(false)
                const selection = window.getSelection()
                selection.removeAllRanges()
                selection.addRange(nextRange)
                savedRangeRef.current = nextRange.cloneRange()
            } else {
                insertPlainText(text)
                return true
            }

            emitChange()
            return true
        }

        if (formatId === 'date') {
            return insertPlainText(currentDateText())
        }

        const selectedText = range.toString()
        if (range.collapsed || !selectedText) {
            return false
        }

        let wrapper = null

        if (formatId === 'bold') wrapper = document.createElement('strong')
        else if (formatId === 'italic') wrapper = document.createElement('em')
        else if (formatId === 'underline') wrapper = document.createElement('u')
        else if (formatId === 'strike') wrapper = document.createElement('s')
        else if (formatId === 'quote') wrapper = document.createElement('blockquote')
        else if (formatId === 'monospace') wrapper = document.createElement(selectedText.includes('\n') ? 'pre' : 'code')
        else if (formatId === 'spoiler') {
            wrapper = document.createElement('span')
            wrapper.className = 'telegram-spoiler'
            wrapper.dataset.telegramFormat = 'spoiler'
        } else if (formatId === 'link') {
            const rawUrl = options.url || window.prompt('Вставте посилання', 'https://')
            if (rawUrl === null) return false
            const href = normalizeTelegramUrl(rawUrl)
            if (!href) return false
            wrapper = document.createElement('a')
            wrapper.href = href
        }

        if (!wrapper) return false

        const content = range.extractContents()
        wrapper.appendChild(content)
        range.insertNode(wrapper)
        selectNodeContents(wrapper)
        emitChange()
        return true
    }

    const handleInput = () => {
        saveSelection()
        emitChange()
    }

    const handleFocus = () => {
        setIsFocused(true)
        saveSelection()
    }

    const handleBlur = () => {
        setIsFocused(false)
        saveSelection()
        updateEmptyState()
    }

    const handlePaste = (event) => {
        onPaste?.(event)
        if (event.defaultPrevented) return

        event.preventDefault()
        const text = event.clipboardData?.getData('text/plain') || ''
        insertPlainText(text)
    }

    const handleMenuPaste = async () => {
        focusEditor()
        if (!onMenuPaste) return false
        await onMenuPaste()
        return true
    }

    const handleKeyDown = (event) => {
        const usesModifier = event.ctrlKey || event.metaKey
        if (!usesModifier) return

        const key = event.key.toLowerCase()
        const code = event.code
        const shift = event.shiftKey
        let formatId = ''

        if (!shift && key === 'a') {
            const editor = editorRef.current
            if (!editor) return
            event.preventDefault()
            const range = document.createRange()
            range.selectNodeContents(editor)
            const selection = window.getSelection()
            selection.removeAllRanges()
            selection.addRange(range)
            savedRangeRef.current = range.cloneRange()
            return
        }

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

        if (!formatId) return

        event.preventDefault()
        applyFormat(formatId)
    }

    useImperativeHandle(ref, () => ({
        focus: focusEditor,
        insertText: insertPlainText,
        applyFormat,
        menuPaste: handleMenuPaste,
        get value() {
            return lastValueRef.current
        },
        setSelectionRange: () => {},
        select: () => {
            const editor = editorRef.current
            if (!editor) return
            const range = document.createRange()
            range.selectNodeContents(editor)
            const selection = window.getSelection()
            selection.removeAllRanges()
            selection.addRange(range)
            savedRangeRef.current = range.cloneRange()
        }
    }))

    useEffect(() => {
        const editor = editorRef.current
        if (!editor) return

        editor.__telegramEditorApi = { applyFormat, insertText: insertPlainText, menuPaste: handleMenuPaste }
        return () => {
            if (editor.__telegramEditorApi) delete editor.__telegramEditorApi
        }
    }, [applyFormat, onMenuPaste])

    useEffect(() => {
        const editor = editorRef.current
        const nextValue = String(value || '')
        if (!editor || nextValue === lastValueRef.current) return

        editor.innerHTML = telegramMarkupToEditorHtml(nextValue)
        lastValueRef.current = nextValue
        updateEmptyState()
    }, [value])

    return (
        <div
            ref={editorRef}
            className={`${className} telegram-rich-editor`}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-multiline="true"
            aria-label={placeholder}
            data-placeholder={placeholder}
            data-empty={isEmpty && !isFocused ? 'true' : 'false'}
            data-telegram-formatting="true"
            data-telegram-editor="true"
            style={{ ...style, '--telegram-editor-rows': rows }}
            onInput={handleInput}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            onKeyUp={saveSelection}
            onMouseUp={saveSelection}
            onFocus={handleFocus}
            onBlur={handleBlur}
            dangerouslySetInnerHTML={{ __html: initialHtml }}
        />
    )
}

export { TELEGRAM_FORMATS, telegramMarkupToEditorHtml, editorHtmlToTelegramMarkup }
export default forwardRef(RichTelegramEditor)

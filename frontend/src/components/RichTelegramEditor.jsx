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
const EMPTY_PLACEHOLDER_TOKENS = []

const escapeAttr = (value) => escapeTelegramHtml(value).replace(/"/g, '&quot;')
const escapeRegExp = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const buildPlaceholderMap = (tokens = []) => new Map(
    tokens
        .filter(item => item?.token && item?.label)
        .map(item => [String(item.token), String(item.label)])
)

const placeholderHtml = (token, label) => (
    `<span class="telegram-placeholder-token" data-template-placeholder="${escapeAttr(token)}" contenteditable="false" title="${escapeAttr(token)}">${escapeTelegramHtml(label)}</span>`
)

const decoratePlaceholders = (html, placeholderMap) => {
    if (!placeholderMap?.size) return html
    const pattern = Array.from(placeholderMap.keys())
        .sort((a, b) => b.length - a.length)
        .map(escapeRegExp)
        .join('|')
    if (!pattern) return html
    return html.replace(new RegExp(pattern, 'g'), token => placeholderHtml(token, placeholderMap.get(token)))
}

const markdownToEditorHtml = (value, { preserveNewlines = true, placeholderMap = null } = {}) => {
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

    html = decoratePlaceholders(html, placeholderMap)
    return preserveNewlines ? html.replace(/\n/g, '<br>') : html
}

const sanitizeEditorNode = (node, { inCode = false, placeholderMap = null } = {}) => {
    if (node.nodeType === Node.TEXT_NODE) {
        const text = node.nodeValue || ''
        return inCode
            ? decoratePlaceholders(escapeTelegramHtml(text).replace(/\r\n/g, '\n').replace(/\n/g, '<br>'), placeholderMap)
            : markdownToEditorHtml(text, { placeholderMap })
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const tag = node.tagName.toLowerCase()
    if (tag === 'br') return '<br>'

    const childHtml = Array.from(node.childNodes)
        .map(child => sanitizeEditorNode(child, { inCode: inCode || tag === 'code' || tag === 'pre', placeholderMap }))
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

const telegramMarkupToEditorHtml = (value, placeholderMap = null) => {
    const raw = String(value || '')
    if (!raw) return ''

    if (!SUPPORTED_HTML_RE.test(raw)) {
        return markdownToEditorHtml(raw, { placeholderMap })
    }

    const doc = new DOMParser().parseFromString(raw.replace(/\r\n/g, '\n').replace(/\n/g, '<br>'), 'text/html')
    return Array.from(doc.body.childNodes).map(child => sanitizeEditorNode(child, { placeholderMap })).join('')
}

const serializeEditorNode = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
        return escapeTelegramHtml((node.nodeValue || '').replace(/\u00a0/g, ' ').replace(/\u200b/g, ''))
    }

    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const tag = node.tagName.toLowerCase()
    if (tag === 'br') return '\n'
    if (node.dataset?.templatePlaceholder) return node.dataset.templatePlaceholder

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

const appendTextWithPlaceholders = (fragment, text, placeholderMap) => {
    if (!placeholderMap?.size || !text) {
        const node = document.createTextNode(text)
        fragment.appendChild(node)
        return node
    }

    const pattern = Array.from(placeholderMap.keys())
        .sort((a, b) => b.length - a.length)
        .map(escapeRegExp)
        .join('|')
    if (!pattern) {
        const node = document.createTextNode(text)
        fragment.appendChild(node)
        return node
    }

    const regex = new RegExp(pattern, 'g')
    let cursor = 0
    let lastNode = null
    let match = regex.exec(text)

    while (match) {
        if (match.index > cursor) {
            lastNode = document.createTextNode(text.slice(cursor, match.index))
            fragment.appendChild(lastNode)
        }

        const token = match[0]
        const chip = document.createElement('span')
        chip.className = 'telegram-placeholder-token'
        chip.dataset.templatePlaceholder = token
        chip.contentEditable = 'false'
        chip.title = token
        chip.textContent = placeholderMap.get(token)
        fragment.appendChild(chip)
        lastNode = chip
        cursor = match.index + token.length
        match = regex.exec(text)
    }

    if (cursor < text.length) {
        lastNode = document.createTextNode(text.slice(cursor))
        fragment.appendChild(lastNode)
    }

    return lastNode
}

const elementMatchesFormat = (element, formatId) => {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return false

    const tag = element.tagName.toLowerCase()
    if (formatId === 'bold') return tag === 'b' || tag === 'strong'
    if (formatId === 'italic') return tag === 'i' || tag === 'em'
    if (formatId === 'underline') return tag === 'u'
    if (formatId === 'strike') return tag === 's' || tag === 'del' || tag === 'strike'
    if (formatId === 'quote') return tag === 'blockquote'
    if (formatId === 'monospace') return tag === 'code' || tag === 'pre'
    if (formatId === 'spoiler') return tag === 'spoiler' || element.dataset?.telegramFormat === 'spoiler'
    if (formatId === 'link') return tag === 'a'
    return false
}

const closestFormatAncestor = (root, node, formatId) => {
    let current = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement
    while (current && current !== root) {
        if (elementMatchesFormat(current, formatId)) return current
        current = current.parentElement
    }
    return null
}

const fragmentHasFormat = (node, formatId) => {
    if (elementMatchesFormat(node, formatId)) return true
    return Array.from(node.childNodes || []).some(child => fragmentHasFormat(child, formatId))
}

const unwrapNode = (node) => {
    const parent = node.parentNode
    if (!parent) return
    while (node.firstChild) {
        parent.insertBefore(node.firstChild, node)
    }
    parent.removeChild(node)
}

const removeFormatFromFragment = (node, formatId) => {
    Array.from(node.childNodes || []).forEach(child => removeFormatFromFragment(child, formatId))
    if (elementMatchesFormat(node, formatId)) {
        unwrapNode(node)
    }
}

const selectInsertedNodes = (firstNode, lastNode) => {
    if (!firstNode || !lastNode || !firstNode.parentNode || !lastNode.parentNode) return null
    const nextRange = document.createRange()
    nextRange.setStartBefore(firstNode)
    nextRange.setEndAfter(lastNode)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(nextRange)
    return nextRange
}

const buildTextFragment = (text, placeholderMap = null) => {
    const fragment = document.createDocumentFragment()
    const parts = String(text || '').replace(/\r\n/g, '\n').split('\n')
    let lastNode = null

    parts.forEach((part, index) => {
        if (index > 0) {
            lastNode = document.createElement('br')
            fragment.appendChild(lastNode)
        }
        if (part) {
            lastNode = appendTextWithPlaceholders(fragment, part, placeholderMap)
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
    onContextMenu,
    placeholder = '',
    rows = 5,
    className = 'form-textarea',
    style = {},
    placeholderTokens = EMPTY_PLACEHOLDER_TOKENS
}, ref) {
    const editorRef = useRef(null)
    const savedRangeRef = useRef(null)
    const lastValueRef = useRef(String(value || ''))
    const historyRef = useRef({ past: [], future: [] })
    const placeholderMap = useMemo(() => buildPlaceholderMap(placeholderTokens), [placeholderTokens])
    const initialHtml = useMemo(() => telegramMarkupToEditorHtml(value, placeholderMap), [])
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

    const pushHistory = (previousValue) => {
        const history = historyRef.current
        if (history.past[history.past.length - 1] !== previousValue) {
            history.past.push(previousValue)
            if (history.past.length > 100) history.past.shift()
        }
        history.future = []
    }

    const moveCaretToEnd = () => {
        const editor = editorRef.current
        if (!editor) return
        const range = document.createRange()
        range.selectNodeContents(editor)
        range.collapse(false)
        const selection = window.getSelection()
        selection.removeAllRanges()
        selection.addRange(range)
        savedRangeRef.current = range.cloneRange()
    }

    const restoreValue = (nextValue) => {
        const editor = editorRef.current
        if (!editor) return false
        editor.innerHTML = telegramMarkupToEditorHtml(nextValue, placeholderMap)
        lastValueRef.current = String(nextValue || '')
        updateEmptyState()
        moveCaretToEnd()
        onChange?.({ target: { value: lastValueRef.current } })
        return true
    }

    const undoChange = () => {
        const history = historyRef.current
        if (!history.past.length) return false
        const currentValue = lastValueRef.current
        const previousValue = history.past.pop()
        history.future.push(currentValue)
        return restoreValue(previousValue)
    }

    const redoChange = () => {
        const history = historyRef.current
        if (!history.future.length) return false
        const currentValue = lastValueRef.current
        const nextValue = history.future.pop()
        history.past.push(currentValue)
        return restoreValue(nextValue)
    }

    const emitChange = ({ recordHistory = true } = {}) => {
        const editor = editorRef.current
        const nextValue = editorHtmlToTelegramMarkup(editor)
        const previousValue = lastValueRef.current
        if (recordHistory && nextValue !== previousValue) {
            pushHistory(previousValue)
        }
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
        const { fragment, lastNode } = buildTextFragment(text, placeholderMap)
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

        const canToggleFormat = !['clear', 'date'].includes(formatId)
        const startAncestor = closestFormatAncestor(editor, range.startContainer, formatId)
        const endAncestor = closestFormatAncestor(editor, range.endContainer, formatId)
        const clone = range.cloneContents()
        const hasMatchingAncestor = !!(
            startAncestor
            && endAncestor
            && (
                startAncestor === endAncestor
                || startAncestor.contains(endAncestor)
                || endAncestor.contains(startAncestor)
            )
        )
        const shouldRemoveFormat = canToggleFormat && (hasMatchingAncestor || fragmentHasFormat(clone, formatId))

        if (shouldRemoveFormat) {
            const content = range.extractContents()
            removeFormatFromFragment(content, formatId)
            const insertedNodes = Array.from(content.childNodes)
            range.insertNode(content)
            const nextRange = selectInsertedNodes(insertedNodes[0], insertedNodes[insertedNodes.length - 1])
            if (nextRange) {
                savedRangeRef.current = nextRange.cloneRange()
            } else {
                saveSelection()
            }
            emitChange()
            return true
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

        if (!shift && (key === 'z' || code === 'KeyZ')) {
            if (undoChange()) {
                event.preventDefault()
            }
            return
        }

        if ((!shift && (key === 'y' || code === 'KeyY')) || (shift && (key === 'z' || code === 'KeyZ'))) {
            if (redoChange()) {
                event.preventDefault()
            }
            return
        }

        if (!shift && (key === 'a' || code === 'KeyA')) {
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

        if (!shift && (key === 'b' || code === 'KeyB')) formatId = 'bold'
        else if (!shift && (key === 'i' || code === 'KeyI')) formatId = 'italic'
        else if (!shift && (key === 'u' || code === 'KeyU')) formatId = 'underline'
        else if (!shift && (key === 'k' || code === 'KeyK')) formatId = 'link'
        else if (shift && (key === 'x' || code === 'KeyX')) formatId = 'strike'
        else if (shift && (key === 'm' || code === 'KeyM')) formatId = 'monospace'
        else if (shift && (key === 'p' || code === 'KeyP')) formatId = 'spoiler'
        else if (shift && (key === 'd' || code === 'KeyD')) formatId = 'date'
        else if (shift && (key === 'n' || code === 'KeyN')) formatId = 'clear'
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

        editor.innerHTML = telegramMarkupToEditorHtml(nextValue, placeholderMap)
        lastValueRef.current = nextValue
        updateEmptyState()
    }, [value, placeholderMap])

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
            onContextMenu={onContextMenu}
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

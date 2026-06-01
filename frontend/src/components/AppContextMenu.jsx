import { useEffect, useMemo, useRef, useState } from 'react'
import {
    TELEGRAM_FORMATS,
    applyTelegramFormatToElement,
    getEditableSelectionText,
    isTelegramFormatElement
} from '../utils/telegramFormatting'

const EDITABLE_INPUT_TYPES = new Set([
    'text',
    'search',
    'url',
    'tel',
    'email',
    'password',
    'number',
    'time',
    'date',
    'datetime-local',
])

const isEditableElement = (element) => {
    if (!element) return false
    if (element.isContentEditable) return true
    if (element instanceof HTMLTextAreaElement) return !element.disabled && !element.readOnly
    if (element instanceof HTMLInputElement) {
        const type = (element.type || 'text').toLowerCase()
        return EDITABLE_INPUT_TYPES.has(type) && !element.disabled && !element.readOnly
    }
    return false
}

const getSelectedText = (element = null) => {
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
        return getEditableSelectionText(element)
    }
    return window.getSelection()?.toString() || ''
}

const findEditableTarget = (target) => {
    if (!target) return null
    if (isEditableElement(target)) return target
    if (!(target instanceof Element)) return null

    const element = target.closest('textarea, input, [contenteditable="true"]')
    return isEditableElement(element) ? element : null
}

const dispatchInputEvent = (element) => {
    element.dispatchEvent(new Event('input', { bubbles: true }))
}

const insertTextIntoEditable = (element, text) => {
    if (!element || !text) return

    if (element.__telegramEditorApi?.insertText) {
        element.__telegramEditorApi.insertText(text)
        return
    }

    if (element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement) {
        element.focus()
        try {
            const start = element.selectionStart ?? element.value.length
            const end = element.selectionEnd ?? element.value.length
            element.setRangeText(text, start, end, 'end')
        } catch (_) {
            element.value = `${element.value || ''}${text}`
        }
        dispatchInputEvent(element)
        return
    }

    element.focus()
    document.execCommand('insertText', false, text)
}

function AppContextMenu() {
    const [menu, setMenu] = useState(null)
    const targetRef = useRef(null)

    useEffect(() => {
        const close = () => setMenu(null)
        const onContextMenu = (event) => {
            if (event.defaultPrevented) return

            event.preventDefault()
            const target = event.target
            const editableTarget = findEditableTarget(target)
            targetRef.current = editableTarget || target

            const editable = isEditableElement(editableTarget)
            const selectedText = getSelectedText(editableTarget)
            const canFormat = isTelegramFormatElement(editableTarget)
            const menuWidth = 238
            const menuHeight = editable
                ? (canFormat && selectedText.trim() ? 620 : 286)
                : selectedText ? 166 : 132
            const x = Math.min(event.clientX, window.innerWidth - menuWidth - 8)
            const y = Math.min(event.clientY, window.innerHeight - menuHeight - 8)

            setMenu({
                x: Math.max(8, x),
                y: Math.max(8, y),
                editable,
                canFormat,
                hasSelection: selectedText.trim().length > 0,
                selectedText,
            })
        }
        const onKeyDown = (event) => {
            if (event.key === 'Escape') close()
        }

        window.addEventListener('contextmenu', onContextMenu)
        window.addEventListener('click', close)
        window.addEventListener('scroll', close, true)
        window.addEventListener('resize', close)
        window.addEventListener('keydown', onKeyDown)

        return () => {
            window.removeEventListener('contextmenu', onContextMenu)
            window.removeEventListener('click', close)
            window.removeEventListener('scroll', close, true)
            window.removeEventListener('resize', close)
            window.removeEventListener('keydown', onKeyDown)
        }
    }, [])

    const actions = useMemo(() => {
        if (!menu) return []

        const editableTarget = isEditableElement(targetRef.current) ? targetRef.current : null
        const focusTarget = () => editableTarget?.focus()

        const runCommand = (command) => {
            focusTarget()
            document.execCommand(command)
            setMenu(null)
        }

        const copySelection = async () => {
            const text = getSelectedText(editableTarget) || menu.selectedText
            if (text && navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text)
            } else {
                document.execCommand('copy')
            }
            setMenu(null)
        }

        const pasteClipboard = async () => {
            focusTarget()
            if (editableTarget?.__telegramEditorApi?.menuPaste) {
                const handled = await editableTarget.__telegramEditorApi.menuPaste()
                if (handled !== false) {
                    setMenu(null)
                    return
                }
            }

            if (navigator.clipboard?.readText) {
                const text = await navigator.clipboard.readText()
                insertTextIntoEditable(editableTarget, text)
            } else {
                document.execCommand('paste')
            }
            setMenu(null)
        }

        const selectAll = () => {
            if (editableTarget instanceof HTMLInputElement || editableTarget instanceof HTMLTextAreaElement) {
                editableTarget.focus()
                editableTarget.select()
            } else if (editableTarget?.isContentEditable) {
                editableTarget.focus()
                document.execCommand('selectAll')
            }
            setMenu(null)
        }

        const items = []

        if (menu.editable) {
            items.push(
                { label: 'Скасувати', shortcut: 'Ctrl+Z', action: () => runCommand('undo') },
                { label: 'Повторити', shortcut: 'Ctrl+Y', action: () => runCommand('redo') },
                { separator: true },
                { label: 'Вирізати', shortcut: 'Ctrl+X', action: () => runCommand('cut') },
                { label: 'Копіювати', shortcut: 'Ctrl+C', action: () => runCommand('copy') },
                { label: 'Вставити', shortcut: 'Ctrl+V', action: pasteClipboard },
                { label: 'Вибрати все', shortcut: 'Ctrl+A', action: selectAll },
            )
        } else if (menu.hasSelection) {
            items.push(
                { label: 'Копіювати', shortcut: 'Ctrl+C', action: copySelection },
                { label: 'Вибрати все', shortcut: 'Ctrl+A', action: () => runCommand('selectAll') },
            )
        }

        if (items.length > 0) {
            items.push({ separator: true })
        }

        if (menu.canFormat && menu.hasSelection && editableTarget) {
            TELEGRAM_FORMATS.forEach(format => {
                items.push({
                    label: format.menuLabel,
                    shortcut: format.shortcut,
                    action: () => {
                        applyTelegramFormatToElement(editableTarget, format.id)
                        setMenu(null)
                    }
                })
            })
            items.push({ separator: true })
        }

        items.push(
            { label: 'Назад', shortcut: 'Alt+←', action: () => { window.history.back(); setMenu(null) } },
            { label: 'Вперед', shortcut: 'Alt+→', action: () => { window.history.forward(); setMenu(null) } },
            { label: 'Оновити вікно', shortcut: 'F5', action: () => window.location.reload() },
        )

        return items
    }, [menu])

    if (!menu) return null

    return (
        <div
            className="app-context-menu"
            style={{ left: menu.x, top: menu.y }}
            onClick={(event) => event.stopPropagation()}
            onContextMenu={(event) => event.preventDefault()}
        >
            {actions.map((item, index) => item.separator ? (
                <div key={`sep-${index}`} className="app-context-menu-separator" />
            ) : (
                <button
                    key={`${item.label}-${index}`}
                    type="button"
                    className="app-context-menu-item"
                    onClick={async () => {
                        try {
                            await item.action()
                        } catch (_) {
                            setMenu(null)
                        }
                    }}
                >
                    <span>{item.label}</span>
                    {item.shortcut && <kbd>{item.shortcut}</kbd>}
                </button>
            ))}
        </div>
    )
}

export default AppContextMenu

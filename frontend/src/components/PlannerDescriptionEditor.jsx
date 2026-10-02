import { useRef } from 'react'

export default function PlannerDescriptionEditor({ value, onChange, disabled }) {
    const input = useRef(null)

    const replaceSelection = (replacement, selectStart, selectEnd) => {
        const field = input.current
        if (!field) return
        const start = field.selectionStart
        const end = field.selectionEnd
        onChange(value.slice(0, start) + replacement + value.slice(end))
        requestAnimationFrame(() => {
            field.focus()
            field.setSelectionRange(start + selectStart, start + selectEnd)
        })
    }
    const wrap = (before, after, fallback = 'текст') => {
        const field = input.current
        const selected = value.slice(field.selectionStart, field.selectionEnd) || fallback
        replaceSelection(`${before}${selected}${after}`, before.length, before.length + selected.length)
    }
    const list = ordered => {
        const field = input.current
        const selected = value.slice(field.selectionStart, field.selectionEnd) || 'Пункт списку'
        const lines = selected.split('\n').map((line, index) => `${ordered ? `${index + 1}.` : '•'} ${line}`)
        replaceSelection(lines.join('\n'), 0, lines.join('\n').length)
    }
    const clearFormatting = () => {
        const field = input.current
        const selected = value.slice(field.selectionStart, field.selectionEnd)
        if (!selected) return
        const plain = selected.replace(/<\/?u>/g, '').replace(/\*\*|\*/g, '').replace(/\[([^\]]+)\]\(([^)]+)\)/g, '$1').replace(/^\s*(?:\d+\.|•)\s+/gm, '')
        replaceSelection(plain, 0, plain.length)
    }

    return <div className="planner-description-editor">
        <div className="planner-description-editor__heading">
            <span>Опис</span>
            <div className="planner-description-editor__tools" role="toolbar" aria-label="Форматування опису" onMouseDown={event => event.preventDefault()}>
                <button type="button" title="Жирний" aria-label="Жирний" disabled={disabled} onClick={() => wrap('**', '**')}><strong>B</strong></button>
                <button type="button" title="Курсив" aria-label="Курсив" disabled={disabled} onClick={() => wrap('*', '*')}><em>I</em></button>
                <button type="button" title="Підкреслити" aria-label="Підкреслити" disabled={disabled} onClick={() => wrap('<u>', '</u>')}><u>U</u></button>
                <button type="button" title="Нумерований список" aria-label="Нумерований список" disabled={disabled} onClick={() => list(true)}>1≡</button>
                <button type="button" title="Маркований список" aria-label="Маркований список" disabled={disabled} onClick={() => list(false)}>•≡</button>
                <button type="button" title="Посилання" aria-label="Посилання" disabled={disabled} onClick={() => wrap('[', '](https://)', 'назва')}>↗</button>
                <button type="button" title="Прибрати форматування" aria-label="Прибрати форматування" disabled={disabled} onClick={clearFormatting}>T̸</button>
            </div>
        </div>
        <textarea ref={input} aria-label="Опис" rows={2} maxLength={20000} value={value} onChange={event => onChange(event.target.value)} disabled={disabled} placeholder="Додайте опис" />
    </div>
}

import { Fragment } from 'react'

const inlineParts = /(\*\*[^*\n]+\*\*|\*[^*\n]+\*|<u>[^<\n]+<\/u>|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\))/g

function renderInline(line) {
    return line.split(inlineParts).map((part, index) => {
        if (part.startsWith('**') && part.endsWith('**')) return <strong key={index}>{part.slice(2, -2)}</strong>
        if (part.startsWith('*') && part.endsWith('*')) return <em key={index}>{part.slice(1, -1)}</em>
        if (part.startsWith('<u>') && part.endsWith('</u>')) return <u key={index}>{part.slice(3, -4)}</u>
        const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part)
        if (link) return <a key={index} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</a>
        return <Fragment key={index}>{part}</Fragment>
    })
}

export default function PlannerDescriptionView({ value }) {
    const lines = String(value || '').split('\n')
    const content = []
    for (let index = 0; index < lines.length;) {
        const numbered = /^\d+\.\s+/.test(lines[index])
        const bulleted = /^•\s+/.test(lines[index])
        if (numbered || bulleted) {
            const list = []
            while (index < lines.length && (numbered ? /^\d+\.\s+/ : /^•\s+/).test(lines[index])) {
                list.push(<li key={index}>{renderInline(lines[index].replace(numbered ? /^\d+\.\s+/ : /^•\s+/, ''))}</li>)
                index += 1
            }
            content.push(numbered ? <ol key={`list-${index}`}>{list}</ol> : <ul key={`list-${index}`}>{list}</ul>)
        } else {
            content.push(<div key={index}>{lines[index] ? renderInline(lines[index]) : '\u00a0'}</div>)
            index += 1
        }
    }
    return <div className="planner-description-view">{content}</div>
}

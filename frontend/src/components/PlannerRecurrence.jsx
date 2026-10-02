import { useState } from 'react'
import { DateTime } from 'luxon'
import { AppSelect } from './FormControls'

const days = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
const dayLabels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']

export default function PlannerRecurrence({ form, onChange, selectProps }) {
    const date = DateTime.fromISO(form.date || DateTime.now().toISODate()).setLocale('uk')
    const weekday = days[date.weekday - 1]
    const ordinal = date.plus({ days: 7 }).month !== date.month ? -1 : Math.ceil(date.day / 7)
    const rules = form.recurrence || []
    const options = [
        { value: '', label: 'Не повторювати' },
        { value: 'RRULE:FREQ=DAILY', label: 'Щодня' },
        { value: `RRULE:FREQ=WEEKLY;BYDAY=${weekday}`, label: `Щотижня — ${date.toFormat('cccc')}` },
        { value: `RRULE:FREQ=MONTHLY;BYDAY=${ordinal}${weekday}`, label: `Щомісяця — ${ordinal === -1 ? 'останній' : ordinal + '-й'} ${date.toFormat('cccc')}` },
        { value: `RRULE:FREQ=YEARLY;BYMONTH=${date.month};BYMONTHDAY=${date.day}`, label: `Щороку — ${date.toFormat('d MMMM')}` },
        { value: 'RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', label: 'Кожного робочого дня (пн–пт)' },
        { value: 'custom', label: 'Налаштувати…' },
    ]
    const [custom, setCustom] = useState(false)
    const tokens = Object.fromEntries((rules.find(rule => rule.startsWith('RRULE:')) || 'RRULE:FREQ=WEEKLY').slice(6).split(';').map(value => value.split('=')))
    const [draft, setDraft] = useState({ frequency: tokens.FREQ || 'WEEKLY', interval: Number(tokens.INTERVAL || 1), weekdays: tokens.BYDAY?.split(',').filter(day => days.includes(day)) || [weekday], ending: tokens.COUNT ? 'count' : tokens.UNTIL ? 'until' : 'never', count: Number(tokens.COUNT || 10), until: tokens.UNTIL ? DateTime.fromFormat(tokens.UNTIL.slice(0, 8), 'yyyyMMdd').toISODate() : date.plus({ months: 3 }).toISODate() })
    const selected = !rules.length ? '' : rules.length === 1 && options.some(option => option.value === rules[0]) ? rules[0] : 'custom'
    const update = (key, value) => {
        const next = { ...draft, [key]: value }
        setDraft(next)
        let rule = `RRULE:FREQ=${next.frequency};INTERVAL=${Math.max(1, Math.min(365, Number(next.interval) || 1))}`
        if (next.frequency === 'WEEKLY') rule += `;BYDAY=${(next.weekdays.length ? next.weekdays : [weekday]).join(',')}`
        if (next.ending === 'count') rule += `;COUNT=${Math.max(1, Math.min(1000, Number(next.count) || 1))}`
        if (next.ending === 'until' && next.until) {
            const until = DateTime.fromISO(next.until, { zone: form.timezone }).endOf('day')
            rule += `;UNTIL=${form.time ? until.toUTC().toFormat("yyyyMMdd'T'HHmmss'Z'") : until.toFormat('yyyyMMdd')}`
        }
        onChange([rule])
    }
    return <div className="planner-repeat">
        <AppSelect {...selectProps} ariaLabel="Повторення" value={custom ? 'custom' : selected} options={options} onChange={value => { setCustom(value === 'custom'); if (value !== 'custom') onChange(value ? [value] : []); else if (!rules.length) update('frequency', draft.frequency) }} />
        {custom && <div className="planner-repeat__custom">
            <div className="planner-fields"><label>Кожні<input type="number" min="1" max="365" value={draft.interval} onChange={event => update('interval', event.target.value)} /></label><AppSelect {...selectProps} ariaLabel="Період повторення" value={draft.frequency} onChange={value => update('frequency', value)} options={[{ value: 'DAILY', label: 'Дні' }, { value: 'WEEKLY', label: 'Тижні' }, { value: 'MONTHLY', label: 'Місяці' }, { value: 'YEARLY', label: 'Роки' }]} /></div>
            {draft.frequency === 'WEEKLY' && <div className="planner-repeat__weekdays">{days.map((day, index) => <button type="button" key={day} aria-pressed={draft.weekdays.includes(day)} onClick={() => update('weekdays', draft.weekdays.includes(day) ? draft.weekdays.filter(value => value !== day) : [...draft.weekdays, day])}>{dayLabels[index]}</button>)}</div>}
            <AppSelect {...selectProps} ariaLabel="Завершення повторень" value={draft.ending} onChange={value => update('ending', value)} options={[{ value: 'never', label: 'Не завершується' }, { value: 'until', label: 'До дати включно' }, { value: 'count', label: 'Після кількох повторень' }]} />
            {draft.ending === 'until' && <input aria-label="Останній день повторень" required type="date" min={form.date} value={draft.until} onChange={event => update('until', event.target.value)} />}
            {draft.ending === 'count' && <input aria-label="Кількість повторень" type="number" min="1" max="1000" required value={draft.count} onChange={event => update('count', event.target.value)} />}
            <small>Зміни застосовуються до всієї серії.</small>
        </div>}
        {!custom && selected === 'custom' && <small>Власне правило збережено. Натисніть «Налаштувати…», щоб змінити.</small>}
    </div>
}

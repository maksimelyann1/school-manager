import test from 'node:test'
import assert from 'node:assert/strict'
import { plannerEditorValues, plannerGoogleDefaults } from '../frontend/src/utils/plannerValues.js'

const connectedGoogle = { connection: { state: 'connected' }, calendars: [
    { id: 1, visible: true, writable: true },
    { id: 2, visible: true, writable: true, managed: true },
] }

test('new dated tasks and events default to the managed Google calendar', () => {
    for (const kind of ['task', 'event']) {
        const form = { kind, date: '2026-10-17', google_enabled: false }
        const result = plannerGoogleDefaults(form, {}, connectedGoogle)
        assert.equal(result.google_enabled, true)
        assert.equal(result.google_calendar_id, 2)
        assert.equal(form.google_enabled, false)
    }
    const offline = { ...connectedGoogle, connection: { state: 'error' } }
    assert.equal(plannerGoogleDefaults({ date: '2026-10-17' }, {}, offline).google_enabled, true)
})

test('Google defaults preserve existing records and an explicit local choice', () => {
    const form = { date: '2026-10-17', google_enabled: false }
    assert.equal(plannerGoogleDefaults(form, { id: 'local' }, connectedGoogle), form)
    assert.equal(plannerGoogleDefaults(form, {}, connectedGoogle, false), form)
    const enabled = { ...form, google_enabled: true, google_calendar_id: 1 }
    assert.equal(plannerGoogleDefaults(enabled, {}, connectedGoogle), enabled)
})

test('undated, disconnected, and inaccessible calendars stay local', () => {
    const undated = { date: '', google_enabled: false }
    assert.equal(plannerGoogleDefaults(undated, {}, connectedGoogle), undated)
    const form = { date: '2026-10-17', google_enabled: false }
    for (const google of [null, { connection: null },
        { ...connectedGoogle, connection: { state: 'reauth' } },
        { ...connectedGoogle, calendars: [{ id: 1, writable: false, visible: true },
            { id: 2, writable: true, visible: false }] }]) {
        assert.equal(plannerGoogleDefaults(form, {}, google), form)
    }
})

test('Google defaults honor the selected calendar or fall back to a writable visible calendar', () => {
    const form = { date: '2026-10-17', google_enabled: false, google_calendar_id: 1 }
    assert.equal(plannerGoogleDefaults(form, {}, connectedGoogle).google_calendar_id, 1)
    assert.equal(plannerGoogleDefaults({ ...form, google_calendar_id: null }, {},
        { ...connectedGoogle, calendars: connectedGoogle.calendars.slice(0, 1) }).google_calendar_id, 1)
})

test('editing preserves hidden legacy metadata by leaving it out of PATCH', () => {
    const current = { id: 'existing', status: 'done' }
    const form = { title: 'Нова назва', kind: 'task', category: 'lesson', group_id: 42, status: 'done',
        date: '2026-10-25', time: '03:30', timezone: 'Europe/Kyiv', fold: 1 }
    const values = plannerEditorValues(form, current, [])
    for (const key of ['category', 'group_id', 'status']) assert.equal(Object.hasOwn(values, key), false)
    assert.equal(values.fold, 1)
    assert.equal(values.timezone, 'Europe/Kyiv')
    assert.equal(values.time, '03:30')
})

test('new event chooses a deterministic clock occurrence without a DST selector', () => {
    const values = plannerEditorValues({ kind: 'event', date: '2026-10-25', time: '03:30', timezone: 'Europe/Kyiv' }, {}, [])
    assert.equal(values.fold, 0)
    assert.equal(values.category, 'event')
    assert.equal(Object.hasOwn(values, 'group_id'), false)
    assert.equal(Object.hasOwn(values, 'status'), false)
})

test('Google event fields remain available after removing local editor options', () => {
    const form = { title: 'Подія', kind: 'event', date: '2026-10-13', time: '14:00', end_time: '15:00',
        timezone: 'America/New_York', fold: 0, google_enabled: true, google_calendar_id: 7,
        recurrence: ['RRULE:FREQ=WEEKLY;COUNT=3'], location: 'Кабінет 2', description: 'Опис', meet_requested: true }
    const attendees = [{ email: 'guest@example.test' }]
    const values = plannerEditorValues(form, { id: 'google' }, attendees)
    assert.equal(values.timezone, 'America/New_York')
    assert.equal(values.google_calendar_id, 7)
    assert.equal(values.meet_requested, true)
    assert.deepEqual(values.recurrence, form.recurrence)
    assert.deepEqual(values.attendees, attendees)
    assert.equal(values.location, 'Кабінет 2')
})

test('changing a completed task into an event clears completion for valid Google event status', () => {
    const values = plannerEditorValues({ kind: 'event', date: '2026-10-13', time: '14:00' }, { id: 'done', status: 'done' }, [])
    assert.equal(values.status, 'open')
})

test('undated and all-day tasks discard hidden stale time fields', () => {
    const undated = plannerEditorValues({ kind: 'task', date: '', time: '14:00', end_date: '2026-10-13', end_time: '15:00' }, {}, [])
    assert.equal(undated.time, null)
    assert.equal(undated.end_date, null)
    assert.equal(undated.end_time, null)
    const allDay = plannerEditorValues({ kind: 'event', date: '2026-10-13', time: '', end_time: '15:00' }, {}, [])
    assert.equal(allDay.time, null)
    assert.equal(allDay.end_time, null)
})

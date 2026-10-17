export function plannerGoogleDefaults(form, current, google, syncPreference) {
    if (current.id || !form.date || form.google_enabled || syncPreference === false ||
        !['connected', 'error'].includes(google?.connection?.state)) return form
    const calendars = (google.calendars || []).filter(calendar => calendar.visible && calendar.writable)
    const calendar = calendars.find(calendar => calendar.id === form.google_calendar_id) ||
        calendars.find(calendar => calendar.managed) || calendars[0]
    return calendar ? { ...form, google_enabled: true, google_calendar_id: calendar.id } : form
}

// Keep legacy metadata on existing records; the editor only changes calendar fields.
export function plannerEditorValues(form, current, attendees) {
    const keys = ['title', 'description', 'location', 'recurrence', 'attendees', 'meet_requested',
        'kind', 'date', 'time', 'end_date', 'end_time', 'timezone', 'fold', 'parent_id',
        'google_enabled', 'google_calendar_id']
    const values = Object.fromEntries(keys.filter(key => form[key] !== undefined).map(key => [
        key, form[key] === '' && !['title', 'description', 'location'].includes(key) ? null : form[key],
    ]))
    values.fold = form.fold ?? 0
    if (!current.id) values.category = form.kind === 'event' ? 'event' : 'other'
    if (form.kind === 'event') {
        values.attendees = attendees
        if (current.status === 'done') values.status = 'open'
    }
    if (!values.date) Object.assign(values, { time: null, end_date: null, end_time: null })
    if (!values.time) values.end_time = null
    return values
}

import { useEffect, useRef, useState } from 'react'
import { api, reportClientError } from '../api/client'

export default function ReportResendDialog({ run, onClose, onSent }) {
    const dialogRef = useRef(null)
    const sendLockRef = useRef(false)
    const requestIdRef = useRef(crypto.randomUUID())
    const [preview, setPreview] = useState(null)
    const [absents, setAbsents] = useState('')
    const [useLogikaAbsents, setUseLogikaAbsents] = useState(false)
    const [sending, setSending] = useState(false)
    const [error, setError] = useState('')

    useEffect(() => {
        const dialog = dialogRef.current
        const previousFocus = document.activeElement
        dialog.showModal()
        const controller = new AbortController()
        api.get(`/parents-report/runs/${run.id}/resend-preview`, { signal: controller.signal })
            .then(data => {
                if (controller.signal.aborted) return
                setPreview(data)
                setAbsents(data.absents)
                setUseLogikaAbsents(data.use_logika_absents)
            })
            .catch(error => {
                if (error.name !== 'AbortError') setError(error.message)
            })
        return () => {
            controller.abort()
            if (dialog.open) dialog.close()
            previousFocus?.focus()
        }
    }, [run.id])

    const send = async event => {
        event.preventDefault()
        if (sendLockRef.current || !preview) return
        sendLockRef.current = true
        setSending(true)
        setError('')
        try {
            const result = await api.post(`/parents-report/runs/${run.id}/resend`, {
                request_id: requestIdRef.current,
                absents,
                use_logika_absents: useLogikaAbsents,
            })
            onSent(result)
        } catch (error) {
            setError(error.message)
            reportClientError('ParentsReport', `Повторна відправка звіту #${run.id}: ${error.message}`)
        } finally {
            sendLockRef.current = false
            setSending(false)
        }
    }

    return (
        <dialog ref={dialogRef} className="modal parents-resend-dialog" aria-labelledby="resend-report-title"
            onCancel={event => { event.preventDefault(); if (!sendLockRef.current) onClose() }}>
            <form onSubmit={send}>
                <div className="modal-header">
                    <h3 id="resend-report-title" className="modal-title">Повторно відправити звіт</h3>
                    <button type="button" className="modal-close" aria-label="Закрити" disabled={sending} onClick={onClose}>×</button>
                </div>
                {!preview && !error && <p className="parents-muted" role="status">Перевіряю початковий урок…</p>}
                {preview && <>
                    <div className="parents-postpone-summary">
                        <strong>{preview.lesson_group_name}</strong>
                        <span>Урок за {preview.lesson_date.split('-').reverse().join('.')} · {preview.course} · {preview.lesson_code}</span>
                        <span>{preview.lesson_title}</span>
                        <span>Telegram: {preview.telegram_group_name}</span>
                    </div>
                    <label className="form-group">
                        <span className="form-label">Відсутні на цьому уроці</span>
                        <input className="form-input" value={absents} disabled={sending} placeholder="Немає відсутніх"
                            onChange={event => { setAbsents(event.target.value); setUseLogikaAbsents(false) }} />
                    </label>
                    {preview.use_logika_absents && <label className="parents-inline-toggle">
                        <input type="checkbox" checked={useLogikaAbsents} disabled={sending}
                            onChange={event => { setUseLogikaAbsents(event.target.checked); if (event.target.checked) setAbsents(preview.absents) }} />
                        <span className="parents-inline-toggle-track"><span className="parents-inline-toggle-thumb" /></span>
                        <span>Оновити відсутніх з Logika перед відправкою</span>
                    </label>}
                    <p className="parents-muted">Буде створено новий звіт за початкову дату уроку{preview.is_test ? ' з позначкою «ТЕСТ»' : ''}. Попереднє повідомлення в Telegram залишиться.</p>
                </>}
                {error && <p className="parents-resend-error" role="alert">{error}</p>}
                <div className="modal-actions">
                    <button type="button" className="btn btn-secondary" disabled={sending} onClick={onClose}>Скасувати</button>
                    <button type="submit" className="btn btn-primary" disabled={!preview || sending}>
                        {sending ? 'Генерую й надсилаю…' : 'Відправити повторно'}
                    </button>
                </div>
            </form>
        </dialog>
    )
}

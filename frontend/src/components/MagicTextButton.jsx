import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { useToast } from './ToastProvider'

function MagicTextButton({
    value,
    setValue,
    context = 'message',
    onAlert,
    disabled = false
}) {
    const [isPolishing, setIsPolishing] = useState(false)
    const [undoText, setUndoText] = useState(null)
    const { showToast } = useToast()

    useEffect(() => {
        if (!String(value || '').trim()) {
            setUndoText(null)
        }
    }, [value])

    const showAlert = (type, text) => {
        if (typeof onAlert === 'function') {
            onAlert({ type, text })
        } else {
            showToast({ type, text })
        }
    }

    const polishText = async () => {
        if (isPolishing || disabled) return

        const currentText = String(value || '')
        if (!currentText.trim()) {
            showAlert('info', 'Спочатку введіть текст')
            return
        }

        setIsPolishing(true)
        try {
            const data = await api.post('/ai/polish-text', { text: currentText, context })
            const nextText = String(data.text || '').trim()
            if (!nextText) {
                throw new Error('Google AI не повернув текст')
            }

            setUndoText(currentText)
            setValue(nextText)
        } catch (error) {
            showAlert('error', error.message || 'Не вдалося покращити текст')
        } finally {
            setIsPolishing(false)
        }
    }

    const undoPolish = () => {
        if (undoText === null || isPolishing) return
        setValue(undoText)
        setUndoText(null)
    }

    return (
        <div className="magic-text-wrap">
            <button
                type="button"
                className={`magic-text-btn ${isPolishing ? 'loading' : ''}`}
                onClick={polishText}
                disabled={disabled || isPolishing}
                title="Покращити текст через Google AI"
                aria-label="Покращити текст через Google AI"
            >
                {isPolishing ? (
                    <>
                        <span className="magic-text-icon" aria-hidden="true">🔮</span>
                        <span className="magic-text-label">Magic...</span>
                    </>
                ) : (
                    <>
                        <span className="magic-text-label">Magic</span>
                        <span className="magic-text-icon" aria-hidden="true">🪄</span>
                    </>
                )}
            </button>
            {undoText !== null && (
                <button
                    type="button"
                    className="magic-undo-btn"
                    onClick={undoPolish}
                    disabled={isPolishing}
                    title="Повернути попередній текст"
                >
                    <span className="magic-undo-icon" aria-hidden="true">
                        <svg viewBox="0 0 20 20" focusable="false">
                            <path d="M7.8 4.4 4 8.2l3.8 3.8" />
                            <path d="M4.4 8.2h7.4a4.2 4.2 0 1 1-3.1 7" />
                        </svg>
                    </span>
                    <span>Скасувати</span>
                </button>
            )}
        </div>
    )
}

export default MagicTextButton

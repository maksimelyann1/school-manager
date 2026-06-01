import {
    TELEGRAM_QUICK_FORMATS,
    applyTelegramFormatToElement,
    applyTelegramFormatToControlledInput
} from '../utils/telegramFormatting'

function TelegramTextToolbar({ textareaRef, value, setValue }) {
    const applyFormat = (formatId) => {
        const element = textareaRef.current
        if (element?.applyFormat) {
            element.applyFormat(formatId)
            return
        }

        if (element && applyTelegramFormatToElement(element, formatId)) {
            return
        }

        applyTelegramFormatToControlledInput({
            textareaRef,
            value,
            setValue,
            formatId
        })
    }

    return (
        <div className="telegram-format-toolbar" aria-label="Форматування Telegram">
            {TELEGRAM_QUICK_FORMATS.map(format => (
                <button
                    key={format.id}
                    type="button"
                    className={`telegram-format-btn telegram-format-${format.id}`}
                    onClick={() => applyFormat(format.id)}
                    title={`${format.title}${format.shortcut ? ` (${format.shortcut})` : ''}`}
                    aria-label={format.title}
                >
                    {format.label}
                </button>
            ))}
        </div>
    )
}

export default TelegramTextToolbar

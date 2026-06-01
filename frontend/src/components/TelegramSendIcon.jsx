function TelegramSendIcon({ className = '' }) {
    return (
        <svg
            className={`telegram-send-icon ${className}`}
            viewBox="0 0 24 24"
            aria-hidden="true"
            focusable="false"
        >
            <path d="M21.7 3.35 2.9 10.6c-1.28.5-1.27 1.2-.23 1.52l4.82 1.5 1.85 5.67c.24.67.12.94.82.94.54 0 .78-.25 1.08-.54l2.6-2.53 5.4 3.99c.99.55 1.7.27 1.95-.92l3.53-16.62c.36-1.44-.55-2.1-1.52-1.69ZM8.24 13.27l10.56-6.66c.53-.32 1.02-.15.62.2l-9.04 8.17-.35 3.76-1.79-5.47Z" />
        </svg>
    )
}

export default TelegramSendIcon

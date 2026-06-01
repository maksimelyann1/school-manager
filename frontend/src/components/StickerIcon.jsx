import { useId } from 'react'

function StickerIcon() {
    const gradientId = useId().replace(/:/g, '')

    return (
        <svg className="sticker-trigger-icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <defs>
                <linearGradient id={gradientId} x1="3" y1="3" x2="21" y2="21" gradientUnits="userSpaceOnUse">
                    <stop offset="0%" stopColor="#ffffff" />
                    <stop offset="38%" stopColor="#9ee7ff" />
                    <stop offset="72%" stopColor="#a78bfa" />
                    <stop offset="100%" stopColor="#fb7185" />
                </linearGradient>
            </defs>
            <path
                d="M7.4 3.5h7.2c3.3 0 5.9 2.6 5.9 5.9v4.3c0 1.2-.5 2.4-1.4 3.2l-2.2 2.2c-.9.9-2 1.4-3.2 1.4H7.4a3.9 3.9 0 0 1-3.9-3.9V7.4a3.9 3.9 0 0 1 3.9-3.9Z"
                fill="rgba(255,255,255,0.04)"
                stroke={`url(#${gradientId})`}
                strokeWidth="1.8"
                strokeLinejoin="round"
            />
            <path
                d="M13.5 20.5v-3.2a3.8 3.8 0 0 1 3.8-3.8h3.2"
                stroke={`url(#${gradientId})`}
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
            />
            <path
                d="M8.1 13.7c.8 1 2 1.5 3.4 1.5s2.6-.5 3.4-1.5"
                stroke={`url(#${gradientId})`}
                strokeWidth="1.7"
                strokeLinecap="round"
            />
            <path
                d="M8.2 9.4h.01M13.6 9.4h.01"
                stroke={`url(#${gradientId})`}
                strokeWidth="2.5"
                strokeLinecap="round"
            />
            <path
                d="M17.1 5.6l.5 1.1 1.1.5-1.1.5-.5 1.1-.5-1.1-1.1-.5 1.1-.5.5-1.1Z"
                fill="#ffffff"
                opacity="0.95"
            />
        </svg>
    )
}

export default StickerIcon

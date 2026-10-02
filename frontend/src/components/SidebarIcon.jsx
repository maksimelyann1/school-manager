import './SidebarIcon.css'

const drawings = {
    edit: <>
        <path className="menu-icon-surface" d="M5 4h9a3 3 0 0 1 3 3v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a3 3 0 0 1 2-3Z" />
        <path d="M12 4H6a3 3 0 0 0-3 3v11a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-6" />
        <path d="m9 14.8 7.6-7.6a2 2 0 0 1 2.8 2.8l-7.6 7.6-3.3.5Z" />
    </>,
    delete: <>
        <path className="menu-icon-surface" d="M6 6h12l-.8 13a2 2 0 0 1-2 2H8.8a2 2 0 0 1-2-2Z" />
        <path d="M4 6h16M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 6l.8 13a2 2 0 0 0 2 2h6.4a2 2 0 0 0 2-2L18 6M10 10v7m4-7v7" />
    </>,
    more: <>
        <circle className="menu-icon-surface" cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="9" />
        <g fill="currentColor" stroke="none">
            <circle cx="12" cy="7.5" r="1" />
            <circle cx="12" cy="12" r="1" />
            <circle cx="12" cy="16.5" r="1" />
        </g>
    </>,
    close: <>
        <circle className="menu-icon-surface" cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="9" />
        <path d="m9 9 6 6m0-6-6 6" />
    </>,
    refresh: <>
        <path d="M20.5 10a8.7 8.7 0 1 0-.8 6M20.5 4.5V10H15" />
    </>,
    home: <g className="menu-icon-drawing">
        <path className="menu-icon-surface" d="m3.5 10 6.9-5.8a2.5 2.5 0 0 1 3.2 0l6.9 5.8v8a3 3 0 0 1-3 3h-11a3 3 0 0 1-3-3Z" />
        <path d="m3.5 10 6.9-5.8a2.5 2.5 0 0 1 3.2 0l6.9 5.8v8a3 3 0 0 1-3 3h-11a3 3 0 0 1-3-3Z" />
        <path d="M9.5 21v-5.5a2.5 2.5 0 0 1 5 0V21" />
    </g>,
    report: <>
        <rect className="menu-icon-surface" x="2.5" y="5" width="19" height="14" rx="3" />
        <rect x="2.5" y="5" width="19" height="14" rx="3" />
        <path d="m3.5 7 3.5 2.5m10-.3 3.5-2.2" />
        <path className="menu-icon-plane" fill="currentColor" stroke="none" d="m7.2 11.6 9.1-3.5c.6-.2.9.1.7.7l-1.5 7c-.1.5-.4.7-.8.4l-2.4-1.8-1.3 1.2c-.2.2-.4.2-.4-.2l.2-2.4 4.2-3.7-5.3 3.3-2.3-.7c-.5-.1-.5-.3-.2-.3Z" />
    </>,
    planner: <>
        <rect className="menu-icon-surface" x="3" y="5" width="18" height="16" rx="3" />
        <rect x="3" y="5" width="18" height="16" rx="3" />
        <path d="M8 3v4m8-4v4M3 10h18" />
        <path className="menu-icon-check" d="m8.4 15.2 2.3 2.3 4.9-4.7" />
    </>,
    message: <>
        <path className="menu-icon-surface" d="M7 4h10a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4H9l-4.5 2.8A.9.9 0 0 1 3 20V8a4 4 0 0 1 4-4Z" />
        <path d="M7 4h10a4 4 0 0 1 4 4v6a4 4 0 0 1-4 4H9l-4.5 2.8A.9.9 0 0 1 3 20V8a4 4 0 0 1 4-4Z" />
        <g fill="currentColor" stroke="none">
            <circle className="menu-icon-dot menu-icon-step-1" cx="8" cy="11" r="1" />
            <circle className="menu-icon-dot menu-icon-step-2" cx="12" cy="11" r="1" />
            <circle className="menu-icon-dot menu-icon-step-3" cx="16" cy="11" r="1" />
        </g>
    </>,
    scheduled: <>
        <path className="menu-icon-surface" d="M18.5 9V7a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v12.3a.7.7 0 0 0 1.1.6L8 17.5h1.2V12Z" />
        <path d="M18.5 8.5V7a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v12.3a.7.7 0 0 0 1.1.6L8 17.5h.8M7 8.5h6" />
        <circle className="menu-icon-surface" cx="16" cy="16" r="5.5" />
        <circle cx="16" cy="16" r="5.5" />
        <path className="menu-icon-hands" d="M16 13v3l2 1.2" />
    </>,
    template: <>
        <path className="menu-icon-back-sheet" d="M8 3h10a3 3 0 0 1 3 3v10" />
        <g className="menu-icon-front-sheet">
            <rect className="menu-icon-surface" x="3" y="6" width="14.5" height="15" rx="2.5" />
            <rect x="3" y="6" width="14.5" height="15" rx="2.5" />
            <path d="M7 10h6.5" />
            <rect x="6.5" y="13.5" width="3" height="4" rx=".7" strokeWidth="1.5" />
            <path d="M12.5 14h1.5m-1.5 3h1.5" strokeWidth="1.5" />
        </g>
    </>,
    journal: <>
        <rect className="menu-icon-surface" x="5" y="3" width="15" height="18" rx="2.8" />
        <rect x="5" y="3" width="15" height="18" rx="2.8" />
        <path d="M3 7h3M3 12h3M3 17h3" />
        <g className="menu-icon-entry menu-icon-step-1"><circle cx="10" cy="8" r=".75" fill="currentColor" stroke="none" /><path d="M13 8h3.5" /></g>
        <g className="menu-icon-entry menu-icon-step-2"><circle cx="10" cy="12" r=".75" fill="currentColor" stroke="none" /><path d="M13 12h3.5" /></g>
        <g className="menu-icon-entry menu-icon-step-3"><circle cx="10" cy="16" r=".75" fill="currentColor" stroke="none" /><path d="M13 16h2" /></g>
    </>,
    settings: <g className="menu-icon-gear">
        <path d="m9.9 3 .5-1h3.2l.5 1 .4 1.7 1.4.8 1.7-.5 1.1.1 1.6 2.8-.5 1-1.3 1.2v1.8l1.3 1.2.5 1-1.6 2.8-1.1.1-1.7-.5-1.4.8-.4 1.7-.5 1h-3.2l-.5-1-.4-1.7-1.4-.8-1.7.5-1.1-.1-1.6-2.8.5-1 1.3-1.2v-1.8L4.3 9l-.5-1 1.6-2.8 1.1-.1 1.7.5 1.4-.8Z" transform="translate(0 1)" />
        <circle className="menu-icon-surface" cx="12" cy="12" r="3.2" />
        <circle cx="12" cy="12" r="3.2" />
    </g>,
    help: <>
        <circle className="menu-icon-surface" cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="9" />
        <g className="menu-icon-question">
            <path d="M9.2 9.2a2.8 2.8 0 0 1 5.6 0c0 2-2.8 2.1-2.8 4.3" />
            <circle cx="12" cy="17" r=".9" fill="currentColor" stroke="none" />
        </g>
    </>,
}

export default function SidebarIcon({ name }) {
    return <svg className={`menu-icon menu-icon--${name}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
        {drawings[name]}
    </svg>
}

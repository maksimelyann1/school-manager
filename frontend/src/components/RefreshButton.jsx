import SidebarIcon from './SidebarIcon'
import './RefreshButton.css'

export default function RefreshButton({ onClick, busy = false, disabled = false }) {
    return (
        <button type="button" className="refresh-button" onClick={onClick}
            disabled={disabled || busy} aria-busy={busy}>
            <SidebarIcon name="refresh" />
            <span>{busy ? 'Оновлення…' : 'Оновити'}</span>
        </button>
    )
}

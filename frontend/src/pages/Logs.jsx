import React, { useState, useEffect, useMemo } from 'react';
import ResizableTable from '../components/ResizableTable';
import { useApi } from '../hooks/useApi';

const LOG_COLUMN_WIDTHS_KEY = 'school_manager.logs.column_widths.v1';
const LOG_COLUMNS = [
    { id: 'timestamp', label: '\u0427\u0430\u0441', width: 190, minWidth: 150, sortKey: 'timestamp' },
    { id: 'level', label: '\u0420\u0456\u0432\u0435\u043d\u044c', width: 130, minWidth: 110, sortKey: 'level' },
    { id: 'module', label: '\u041c\u043e\u0434\u0443\u043b\u044c', width: 180, minWidth: 130, sortKey: 'module' },
    { id: 'message', label: '\u041f\u043e\u0432\u0456\u0434\u043e\u043c\u043b\u0435\u043d\u043d\u044f', width: 720, minWidth: 260 }
]
const DEFAULT_LOG_COLUMN_WIDTHS = Object.fromEntries(LOG_COLUMNS.map(column => [column.id, column.width]));

function loadLogColumnWidths() {
    if (typeof window === 'undefined') return DEFAULT_LOG_COLUMN_WIDTHS;
    try {
        const saved = JSON.parse(window.localStorage.getItem(LOG_COLUMN_WIDTHS_KEY) || '{}');
        return Object.fromEntries(LOG_COLUMNS.map(column => {
            const width = Number(saved[column.id]);
            return [
                column.id,
                Number.isFinite(width) ? Math.max(column.minWidth || 0, width) : column.width
            ];
        }));
    } catch {
        return DEFAULT_LOG_COLUMN_WIDTHS;
    }
}

export default function Logs() {
    const api = useApi();
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [columnWidths, setColumnWidths] = useState(loadLogColumnWidths);
    const [sort, setSort] = useState({ key: 'timestamp', direction: 'desc' });

    const fetchLogs = async () => {
        setLoading(true);
        try {
            const data = await api.get('/logs', { toast: false });
            setLogs(data);
        } catch (error) {
            console.error("Помилка завантаження логів:", error);
        } finally {
            setLoading(false);
        }
    };

    const clearLogs = async () => {
        if (!window.confirm("Ви впевнені, що хочете очистити весь журнал?")) return;
        
        try {
            await api.delete('/logs', { toast: false });
            fetchLogs();
        } catch (error) {
            console.error("Помилка очищення логів:", error);
        }
    };

    useEffect(() => {
        fetchLogs();
    }, []);

    useEffect(() => {
        try {
            window.localStorage.setItem(LOG_COLUMN_WIDTHS_KEY, JSON.stringify(columnWidths));
        } catch {
            // Ignore restricted localStorage contexts.
        }
    }, [columnWidths]);

    const sortedLogs = useMemo(() => {
        const direction = sort.direction === 'desc' ? -1 : 1;
        return [...logs].sort((left, right) => {
            if (sort.key === 'timestamp') {
                return (new Date(left.timestamp).getTime() - new Date(right.timestamp).getTime()) * direction;
            }
            const leftValue = String(left[sort.key] || '').toLocaleLowerCase('uk');
            const rightValue = String(right[sort.key] || '').toLocaleLowerCase('uk');
            return leftValue.localeCompare(rightValue, 'uk', { numeric: true, sensitivity: 'base' }) * direction;
        });
    }, [logs, sort]);

    const getLevelBadge = (level) => {
        switch (level) {
            case 'INFO':
                return <span className="badge" style={{ background: 'rgba(59, 130, 246, 0.2)', color: '#3b82f6' }}>INFO</span>;
            case 'WARNING':
                return <span className="badge badge-warning">WARN</span>;
            case 'ERROR':
                return <span className="badge badge-danger">ERROR</span>;
            default:
                return <span className="badge">{level}</span>;
        }
    };

    const formatDate = (isoString) => {
        const date = new Date(isoString);
        return date.toLocaleString('uk-UA', { 
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit', second: '2-digit'
        });
    };

    const renderLogCell = (log, column) => {
        switch (column.id) {
            case 'timestamp':
                return (
                    <span style={{ whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                        {formatDate(log.timestamp)}
                    </span>
                );
            case 'level':
                return getLevelBadge(log.level);
            case 'module':
                return (
                    <span style={{ fontWeight: 600, color: 'var(--primary-light)' }}>
                        {log.module}
                    </span>
                );
            case 'message':
                return log.message;
            default:
                return log[column.id] || '';
        }
    };

    return (
        <div className="page">
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2>Журнал подій</h2>
                    <p>Історія роботи додатку та можливі помилки</p>
                </div>
                <div>
                    <button className="btn btn-secondary" onClick={fetchLogs} style={{ marginRight: '10px' }}>
                        Оновити
                    </button>
                    <button className="btn btn-danger" onClick={clearLogs}>
                        Очистити журнал
                    </button>
                </div>
            </div>

            <div className="card">
                {loading ? (
                    <div className="loader"><div className="spinner"></div></div>
                ) : logs.length === 0 ? (
                    <div className="empty-state">
                        <p>Журнал подій порожній</p>
                    </div>
                ) : (
                    <ResizableTable
                        columns={LOG_COLUMNS}
                        rows={sortedLogs}
                        columnWidths={columnWidths}
                        onColumnWidthsChange={setColumnWidths}
                        sort={sort}
                        onSortChange={setSort}
                        renderCell={renderLogCell}
                        getRowKey={(log) => log.id}
                        tableClassName="table logs-resizable-table"
                        wrapperClassName="table-container parents-grid-wrap logs-table-wrap"
                    />
                )}
            </div>
        </div>
    );
}

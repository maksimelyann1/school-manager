import React, { useState, useEffect } from 'react';

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api';

export default function Logs() {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);

    const fetchLogs = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${API_URL}/logs`);
            const data = await response.json();
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
            await fetch(`${API_URL}/logs`, {
                method: 'DELETE'
            });
            fetchLogs();
        } catch (error) {
            console.error("Помилка очищення логів:", error);
        }
    };

    useEffect(() => {
        fetchLogs();
    }, []);

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
                    <div className="table-container">
                        <table className="table" style={{ fontSize: '0.9rem' }}>
                            <thead>
                                <tr>
                                    <th>Час</th>
                                    <th>Рівень</th>
                                    <th>Модуль</th>
                                    <th>Повідомлення</th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.map(log => (
                                    <tr key={log.id}>
                                        <td style={{ whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>
                                            {formatDate(log.timestamp)}
                                        </td>
                                        <td>{getLevelBadge(log.level)}</td>
                                        <td>
                                            <span style={{ fontWeight: 600, color: 'var(--primary-light)' }}>
                                                {log.module}
                                            </span>
                                        </td>
                                        <td>{log.message}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
}

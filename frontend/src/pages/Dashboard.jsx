import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';

const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api';

export default function Dashboard() {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    // Стан системи оновлень
    const [versionInfo, setVersionInfo] = useState(null);
    const [updateStatus, setUpdateStatus] = useState(null); // {status, progress, error}
    const [isDownloading, setIsDownloading] = useState(false);
    const progressIntervalRef = useRef(null);
    const updateStatusRef = useRef(null);

    useEffect(() => {
        updateStatusRef.current = updateStatus;
    }, [updateStatus]);

    const fetchStats = async () => {
        try {
            const response = await fetch(`${API_URL}/dashboard/stats`);
            const data = await response.json();
            setStats(data);
        } catch (error) {
            console.error("Помилка завантаження статистики:", error);
        } finally {
            setLoading(false);
        }
    };

    const fetchVersion = async () => {
        try {
            const response = await fetch(`${API_URL}/system/version`);
            const data = await response.json();
            setVersionInfo(data);
        } catch (error) {
            console.error("Помилка перевірки версії:", error);
        }
    };

    // Починаємо завантаження оновлення
    const startUpdate = async () => {
        if (isDownloading) return;
        setIsDownloading(true);
        setUpdateStatus({ status: 'checking', progress: 0, error: null, downloaded_bytes: 0, total_bytes: 0 });

        try {
            if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
            progressIntervalRef.current = setInterval(pollProgress, 400);
            const response = await fetch(`${API_URL}/system/update/download`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ auto_install: true }),
            });
            const data = await response.json();
            if (!data.ok) {
                clearInterval(progressIntervalRef.current);
                setUpdateStatus({ status: 'error', progress: 0, error: data.error });
                setIsDownloading(false);
                return;
            }
        } catch (error) {
            if (updateStatusRef.current?.status !== 'installing') {
                setUpdateStatus({ status: 'error', progress: 0, error: String(error) });
                setIsDownloading(false);
                clearInterval(progressIntervalRef.current);
            }
        }
    };

    // Опитуємо прогрес завантаження
    const pollProgress = async () => {
        try {
            const response = await fetch(`${API_URL}/system/update/progress`);
            const data = await response.json();
            setUpdateStatus(data);

            if (data.status === 'done' || data.status === 'installing' || data.status === 'error') {
                clearInterval(progressIntervalRef.current);
                setIsDownloading(false);
            }
        } catch (error) {
            if (updateStatusRef.current?.status !== 'installing') {
                clearInterval(progressIntervalRef.current);
                setIsDownloading(false);
            }
        }
    };

    // Запускаємо встановлювач
    const launchInstaller = async () => {
        try {
            setUpdateStatus(prev => ({ ...(prev || {}), status: 'installing', progress: 100 }));
            await fetch(`${API_URL}/system/update/launch`, { method: 'POST' });
        } catch (_) {
            // З'єднання розірветься — це нормально, бо сервер закрився
        }
    };

    useEffect(() => {
        fetchStats();
        fetchVersion();
        const interval = setInterval(fetchStats, 30000);
        return () => {
            clearInterval(interval);
            if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
        };
    }, []);

    const formatDate = (isoString) => {
        const date = new Date(isoString);
        return date.toLocaleString('uk-UA', {
            day: '2-digit', month: '2-digit',
            hour: '2-digit', minute: '2-digit'
        });
    };

    const openSettingsFocus = (focus) => {
        navigate(`/settings?focus=${focus}`);
    };

    const openInfo = () => {
        navigate('/info');
    };

    const handleActionCardKeyDown = (event, focus) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openSettingsFocus(focus);
        }
    };

    const handleInfoCardKeyDown = (event) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            openInfo();
        }
    };

    const progress = Math.max(0, Math.min(100, Number(updateStatus?.progress || 0)));
    const totalBytes = updateStatus?.total_bytes || 0;
    const downloadedBytes = updateStatus?.downloaded_bytes || 0;
    const progressIsKnown = totalBytes > 0;
    const updateRequiresManualInstall = updateStatus?.requires_manual_install ?? versionInfo?.requires_manual_install;
    const progressLabel = updateStatus?.status === 'installing'
        ? '100%'
        : progressIsKnown
            ? `${progress}%`
            : '';
    const updateStatusText = updateStatus?.status === 'checking'
        ? 'Перевіряємо оновлення...'
        : updateStatus?.status === 'installing'
            ? updateRequiresManualInstall ? 'Відкриваємо файл оновлення...' : 'Встановлюємо оновлення...'
            : 'Завантаження...';
    const updateButtonText = updateRequiresManualInstall
        ? '⬇️ Завантажити та відкрити'
        : '⬇️ Завантажити та встановити';
    const installButtonText = updateRequiresManualInstall
        ? '✅ Відкрити оновлення'
        : '✅ Встановити оновлення';

    if (loading && !stats) {
        return (
            <div className="page">
                <div className="loader"><div className="spinner"></div></div>
            </div>
        );
    }

    return (
        <div className="page">
            {versionInfo?.just_updated && (
                <div className="update-success-banner">
                    <strong>✅ Програму оновлено</strong>
                    <span>Встановлена версія v{versionInfo.updated_version || versionInfo.current_version}.</span>
                </div>
            )}

            {/* ===== Банер оновлення ===== */}
            {versionInfo?.update_available && (
                <div style={{
                    background: 'linear-gradient(135deg, rgba(99,102,241,0.25) 0%, rgba(139,92,246,0.25) 100%)',
                    border: '1px solid rgba(99,102,241,0.5)',
                    borderRadius: '12px',
                    padding: '16px 24px',
                    marginBottom: '24px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '16px',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ fontSize: '1.5rem' }}>🎉</div>
                    <div style={{ flex: 1, minWidth: '200px' }}>
                        <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '2px' }}>
                            Доступна нова версія!
                        </div>
                    </div>

                    {/* Прогрес завантаження */}
                    {isDownloading || updateStatus?.status === 'checking' || updateStatus?.status === 'downloading' || updateStatus?.status === 'installing' ? (
                        <div style={{ minWidth: '200px', flex: 1 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '0.85rem' }}>
                                <span>{updateStatusText}</span>
                                {progressLabel && <span>{progressLabel}</span>}
                            </div>
                            <div style={{ height: '8px', background: 'var(--bg-input)', borderRadius: '4px', overflow: 'hidden' }}>
                                <div
                                    className={!progressIsKnown && ['checking', 'downloading'].includes(updateStatus?.status) ? 'update-progress-fill unknown' : 'update-progress-fill'}
                                    style={{ width: `${updateStatus?.status === 'installing' ? 100 : progress}%` }}
                                />
                            </div>
                            {progressIsKnown && updateStatus?.status === 'downloading' && downloadedBytes > 0 && (
                                <div style={{ marginTop: '5px', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                    Завантажено {progress}%
                                </div>
                            )}
                            {updateStatus?.status === 'installing' && (
                                <div style={{ marginTop: '5px', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                    {updateRequiresManualInstall
                                        ? 'Відкриється DMG-файл. Перетягніть SchoolManager.app у Applications.'
                                        : 'Зараз відкриється вікно встановлення оновлення. Після завершення програма запуститься автоматично.'}
                                </div>
                            )}
                        </div>
                    ) : updateStatus?.status === 'done' ? (
                        <button className="btn btn-primary" onClick={launchInstaller}>
                            {installButtonText}
                        </button>
                    ) : updateStatus?.status === 'error' ? (
                        <div style={{ color: 'var(--danger)', fontSize: '0.9rem' }}>
                            ❌ Помилка: {updateStatus.error}
                        </div>
                    ) : (
                        <button className="btn btn-primary" onClick={startUpdate}>
                            {updateButtonText}
                        </button>
                    )}
                </div>
            )}

            {/* ===== Заголовок ===== */}
            <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                    <h2>Головна панель</h2>
                    <p>Огляд роботи додатку та найближчі завдання</p>
                </div>
                <button className="btn btn-secondary" onClick={() => { fetchStats(); fetchVersion(); }}>
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: '8px' }}>
                        <polyline points="23 4 23 10 17 10"></polyline>
                        <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                    </svg>
                    Оновити
                </button>
            </div>

            {/* ===== Картки статистики ===== */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: '20px', marginBottom: '30px' }}>

                {/* Статус Telegram */}
                <div
                    className="card dashboard-action-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => openSettingsFocus('telegram')}
                    onKeyDown={(event) => handleActionCardKeyDown(event, 'telegram')}
                    style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: '16px', borderLeft: `4px solid ${stats?.is_connected ? 'var(--success)' : 'var(--danger)'}` }}
                >
                    <div style={{ padding: '12px', background: stats?.is_connected ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)', borderRadius: '12px', color: stats?.is_connected ? 'var(--success)' : 'var(--danger)' }}>
                        {stats?.is_connected ? (
                            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                                <polyline points="22 4 12 14.01 9 11.01"></polyline>
                            </svg>
                        ) : (
                            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <circle cx="12" cy="12" r="10"></circle>
                                <line x1="12" y1="8" x2="12" y2="12"></line>
                                <line x1="12" y1="16" x2="12.01" y2="16"></line>
                            </svg>
                        )}
                    </div>
                    <div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '4px' }}>Статус Telegram</p>
                        <h3 style={{ fontSize: '1.25rem', fontWeight: 600 }}>{stats?.is_connected ? 'Підключено' : 'Відключено'}</h3>
                    </div>
                </div>

                {/* Заплановано на сьогодні */}
                <div className="card" style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--primary)' }}>
                    <div style={{ padding: '12px', background: 'rgba(99,102,241,0.1)', borderRadius: '12px', color: 'var(--primary)' }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <polyline points="12 6 12 12 16 14"></polyline>
                        </svg>
                    </div>
                    <div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '4px' }}>Заплановано на сьогодні</p>
                        <h3 style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats?.today_scheduled_count || 0}</h3>
                    </div>
                </div>

                {/* Всього груп */}
                <div
                    className="card dashboard-action-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => openSettingsFocus('groups')}
                    onKeyDown={(event) => handleActionCardKeyDown(event, 'groups')}
                    style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--secondary)' }}
                >
                    <div style={{ padding: '12px', background: 'rgba(14,165,233,0.1)', borderRadius: '12px', color: 'var(--secondary)' }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                            <circle cx="9" cy="7" r="4"></circle>
                            <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                            <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
                        </svg>
                    </div>
                    <div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '4px' }}>Всього груп</p>
                        <h3 style={{ fontSize: '1.5rem', fontWeight: 700 }}>{stats?.total_groups || 0}</h3>
                    </div>
                </div>

                {/* Версія програми */}
                <div
                    className="card dashboard-action-card"
                    role="button"
                    tabIndex={0}
                    onClick={openInfo}
                    onKeyDown={handleInfoCardKeyDown}
                    style={{ marginBottom: 0, display: 'flex', alignItems: 'center', gap: '16px', borderLeft: '4px solid var(--accent)' }}
                >
                    <div style={{ padding: '12px', background: 'rgba(245,158,11,0.1)', borderRadius: '12px', color: 'var(--accent)' }}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10"></circle>
                            <line x1="12" y1="8" x2="12" y2="12"></line>
                            <line x1="12" y1="16" x2="12.01" y2="16"></line>
                        </svg>
                    </div>
                    <div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginBottom: '4px' }}>Версія програми</p>
                        <h3 style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                            v{versionInfo?.current_version || '...'}
                            {versionInfo?.update_available && (
                                <span style={{ fontSize: '0.7rem', background: 'rgba(99,102,241,0.2)', color: 'var(--primary-light)', padding: '2px 8px', borderRadius: '10px', marginLeft: '8px', verticalAlign: 'middle' }}>
                                    → v{versionInfo.latest_version}
                                </span>
                            )}
                        </h3>
                        {!versionInfo?.check_enabled && (
                            <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '2px' }}>Перевірка не налаштована</p>
                        )}
                        {versionInfo?.update_available === false && versionInfo?.check_enabled && (
                            <p style={{ fontSize: '0.75rem', color: 'var(--success)', marginTop: '2px' }}>✓ Актуальна версія</p>
                        )}
                    </div>
                </div>
            </div>

            {/* ===== Найближчі розсилки ===== */}
            <div className="card">
                <div className="card-header" style={{ borderBottom: '1px solid var(--border)', paddingBottom: '16px', marginBottom: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 className="card-title">Найближчі розсилки</h3>
                    <Link to="/auto-messages" className="btn btn-sm btn-secondary">Управління розкладом</Link>
                </div>

                {stats?.upcoming_messages && stats.upcoming_messages.length > 0 ? (
                    <div className="table-container">
                        <table className="table" style={{ fontSize: '0.95rem' }}>
                            <thead>
                                <tr>
                                    <th style={{ width: '160px' }}>Коли</th>
                                    <th>Залишилось</th>
                                    <th>Група</th>
                                    <th>Повідомлення</th>
                                </tr>
                            </thead>
                            <tbody>
                                {stats.upcoming_messages.map(msg => (
                                    <tr key={msg.id}>
                                        <td style={{ fontWeight: 500, color: 'var(--primary-light)' }}>
                                            {formatDate(msg.target_datetime)}
                                        </td>
                                        <td>
                                            <span className="badge" style={{ background: 'rgba(255,255,255,0.1)', color: 'var(--text-secondary)' }}>
                                                {msg.time_left}
                                            </span>
                                        </td>
                                        <td style={{ fontWeight: 600 }}>{msg.group_name}</td>
                                        <td>
                                            <div style={{
                                                maxWidth: '300px',
                                                whiteSpace: 'nowrap',
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                color: 'var(--text-secondary)'
                                            }}>
                                                {msg.message}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <div className="empty-state" style={{ padding: '40px 20px' }}>
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ width: '48px', height: '48px', marginBottom: '16px', opacity: 0.5 }}>
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                            <line x1="16" y1="2" x2="16" y2="6"></line>
                            <line x1="8" y1="2" x2="8" y2="6"></line>
                            <line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                        <p style={{ fontSize: '1.1rem', marginBottom: '8px' }}>Немає активних розсилок</p>
                        <p style={{ fontSize: '0.9rem' }}>Заплановані повідомлення з'являться тут</p>
                    </div>
                )}
            </div>
        </div>
    );
}

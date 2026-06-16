function ResizableTable({
    columns,
    rows,
    columnWidths,
    onColumnWidthsChange,
    sort,
    onSortChange,
    renderCell,
    getRowKey = (row) => row.id,
    emptyMessage = 'Немає даних',
    tableClassName = 'table',
    wrapperClassName = 'parents-grid-wrap'
}) {
    const getColumnWidth = (column) => columnWidths?.[column.id] || column.width
    const tableWidth = columns.reduce((sum, column) => sum + getColumnWidth(column), 0)

    const toggleSort = (key) => {
        if (!key || typeof onSortChange !== 'function') return
        onSortChange(prev => ({
            key,
            direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc'
        }))
    }

    const startColumnResize = (event, column) => {
        if (typeof onColumnWidthsChange !== 'function') return
        event.preventDefault()
        event.stopPropagation()

        const startX = event.clientX
        const startWidth = getColumnWidth(column)
        const minWidth = column.minWidth || 72

        const handleMove = (moveEvent) => {
            const delta = moveEvent.clientX - startX
            const nextWidth = Math.max(minWidth, Math.round(startWidth + delta))
            onColumnWidthsChange(prev => ({ ...prev, [column.id]: nextWidth }))
        }

        const handleUp = () => {
            window.removeEventListener('pointermove', handleMove)
            window.removeEventListener('pointerup', handleUp)
            window.removeEventListener('pointercancel', handleUp)
            document.body.classList.remove('is-resizing-table-column')
        }

        document.body.classList.add('is-resizing-table-column')
        window.addEventListener('pointermove', handleMove)
        window.addEventListener('pointerup', handleUp, { once: true })
        window.addEventListener('pointercancel', handleUp, { once: true })
    }

    const renderHeaderCell = (column) => {
        const isSorted = sort?.key === column.sortKey
        return (
            <th key={column.id}>
                <div className="parents-th-content">
                    {column.sortKey ? (
                        <button
                            type="button"
                            className={`parents-sort-btn ${isSorted ? 'active' : ''}`}
                            onClick={() => toggleSort(column.sortKey)}
                            title={`Сортувати: ${column.label}`}
                        >
                            <span>{column.label}</span>
                            <span className="parents-sort-mark">{isSorted ? (sort.direction === 'asc' ? '↑' : '↓') : ''}</span>
                        </button>
                    ) : (
                        <span className="parents-th-label">{column.label}</span>
                    )}
                    <span
                        className="parents-col-resizer"
                        onPointerDown={(event) => startColumnResize(event, column)}
                        title="Змінити ширину колонки"
                    />
                </div>
            </th>
        )
    }

    return (
        <div className={wrapperClassName}>
            <table className={tableClassName} style={{ width: tableWidth }}>
                <colgroup>
                    {columns.map(column => (
                        <col key={column.id} style={{ width: getColumnWidth(column) }} />
                    ))}
                </colgroup>
                <thead>
                    <tr>{columns.map(renderHeaderCell)}</tr>
                </thead>
                <tbody>
                    {rows.length === 0 ? (
                        <tr>
                            <td colSpan={columns.length}>{emptyMessage}</td>
                        </tr>
                    ) : rows.map(row => (
                        <tr key={getRowKey(row)}>
                            {columns.map(column => (
                                <td key={column.id} className={column.cellClassName || ''}>
                                    {renderCell(row, column)}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    )
}

export default ResizableTable

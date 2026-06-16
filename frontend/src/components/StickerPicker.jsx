import { useEffect, useMemo, useRef, useState } from 'react'
import StickerPreview from './StickerPreview'
import { clearStickerMediaMemoryCache } from '../utils/stickerMediaQueue'
import FloatingPanel from './FloatingPanel'
import { API_URL } from '../api/client'

const GRID_COLUMNS = 5
const ROW_HEIGHT = 80
const GRID_HEIGHT = 260
const OVERSCAN_ROWS = 3

const stickerMemoryCache = {
    packs: null,
    packsByName: new Map(),
    packCovers: new Map()
}

const stickerKey = (sticker) => String(sticker?.document_id || sticker?.id || sticker?.file_id || '')
const firstSticker = (stickers) => (Array.isArray(stickers) ? stickers[0] || null : null)
const packInitial = (pack) => Array.from(pack?.title || pack?.short_name || '?')[0] || '?'

const fetchPackStickers = async (shortName, signal) => {
    if (stickerMemoryCache.packsByName.has(shortName)) {
        return stickerMemoryCache.packsByName.get(shortName)
    }

    const response = await fetch(`${API_URL}/stickers/packs/${encodeURIComponent(shortName)}`, { signal })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Не вдалося завантажити набір наліпок')
    const nextStickers = data.stickers || []
    stickerMemoryCache.packsByName.set(shortName, nextStickers)
    return nextStickers
}

function StickerPicker({ onSelect, onClose, anchorRef }) {
    const pickerRef = useRef(null)
    const gridRef = useRef(null)
    const packTabsRef = useRef(null)
    const [packs, setPacks] = useState([])
    const [activePack, setActivePack] = useState('')
    const [stickers, setStickers] = useState([])
    const [loadingPacks, setLoadingPacks] = useState(true)
    const [loadingStickers, setLoadingStickers] = useState(false)
    const [error, setError] = useState('')
    const [reloadKey, setReloadKey] = useState(0)
    const [scrollTop, setScrollTop] = useState(0)
    const [gridHeight, setGridHeight] = useState(GRID_HEIGHT)
    const [activeStickerKey, setActiveStickerKey] = useState('')
    const [packCovers, setPackCovers] = useState({})

    const rememberPackCover = (shortName, cover) => {
        stickerMemoryCache.packCovers.set(shortName, cover)
        setPackCovers(prev => (prev[shortName] === cover ? prev : { ...prev, [shortName]: cover }))
    }

    const handlePackTabsWheel = (event) => {
        const node = packTabsRef.current
        if (!node) return

        const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
        if (!delta) return

        const previousScrollLeft = node.scrollLeft
        node.scrollLeft += delta
        if (node.scrollLeft !== previousScrollLeft) event.preventDefault()
    }

    useEffect(() => {
        const handleClickOutside = (event) => {
            const insidePicker = pickerRef.current && pickerRef.current.contains(event.target)
            const insideAnchor = anchorRef?.current && anchorRef.current.contains(event.target)
            if (!insidePicker && !insideAnchor) {
                onClose?.()
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [anchorRef, onClose])

    useEffect(() => {
        const node = gridRef.current
        if (!node) return undefined

        const updateHeight = () => setGridHeight(node.clientHeight || GRID_HEIGHT)
        updateHeight()

        if (!('ResizeObserver' in window)) return undefined
        const observer = new ResizeObserver(updateHeight)
        observer.observe(node)
        return () => observer.disconnect()
    }, [loadingStickers, activePack])

    useEffect(() => {
        setScrollTop(0)
        setActiveStickerKey('')
        if (gridRef.current) gridRef.current.scrollTop = 0
    }, [activePack])

    useEffect(() => {
        const controller = new AbortController()
        const loadPacks = async () => {
            const forceReload = reloadKey > 0
            if (!forceReload && stickerMemoryCache.packs) {
                setPacks(stickerMemoryCache.packs)
                setActivePack(prev => prev || stickerMemoryCache.packs[0]?.short_name || '')
                setLoadingPacks(false)
                setError('')
                return
            }

            setLoadingPacks(true)
            setError('')
            try {
                const response = await fetch(`${API_URL}/stickers/packs`, { signal: controller.signal })
                const data = await response.json()
                if (!response.ok) throw new Error(data.detail || 'Не вдалося завантажити наліпки')
                const nextPacks = data.packs || []
                stickerMemoryCache.packs = nextPacks
                setPacks(nextPacks)
                setActivePack(nextPacks[0]?.short_name || '')
            } catch (loadError) {
                if (loadError.name === 'AbortError') return
                setError(loadError.message || 'Не вдалося завантажити наліпки')
            } finally {
                if (!controller.signal.aborted) setLoadingPacks(false)
            }
        }
        loadPacks()
        return () => controller.abort()
    }, [reloadKey])

    useEffect(() => {
        if (!activePack) {
            setStickers([])
            return undefined
        }

        const controller = new AbortController()
        const loadStickers = async () => {
            const forceReload = reloadKey > 0
            if (!forceReload && stickerMemoryCache.packsByName.has(activePack)) {
                const cachedStickers = stickerMemoryCache.packsByName.get(activePack)
                setStickers(cachedStickers)
                rememberPackCover(activePack, firstSticker(cachedStickers))
                setLoadingStickers(false)
                setError('')
                return
            }

            setLoadingStickers(true)
            setError('')
            try {
                const nextStickers = await fetchPackStickers(activePack, controller.signal)
                setStickers(nextStickers)
                rememberPackCover(activePack, firstSticker(nextStickers))
            } catch (loadError) {
                if (loadError.name === 'AbortError') return
                setStickers([])
                setError(loadError.message || 'Не вдалося завантажити набір наліпок')
            } finally {
                if (!controller.signal.aborted) setLoadingStickers(false)
            }
        }
        loadStickers()
        return () => controller.abort()
    }, [activePack, reloadKey])

    useEffect(() => {
        if (loadingPacks || packs.length === 0) return undefined

        const controller = new AbortController()
        let cancelled = false

        const loadPackCovers = async () => {
            for (const pack of packs) {
                const shortName = pack.short_name
                if (!shortName || cancelled) break

                if (stickerMemoryCache.packCovers.has(shortName)) {
                    rememberPackCover(shortName, stickerMemoryCache.packCovers.get(shortName))
                    continue
                }

                try {
                    const nextStickers = await fetchPackStickers(shortName, controller.signal)
                    if (!cancelled) rememberPackCover(shortName, firstSticker(nextStickers))
                } catch (loadError) {
                    if (loadError.name !== 'AbortError' && !cancelled) rememberPackCover(shortName, null)
                }
            }
        }

        loadPackCovers()

        return () => {
            cancelled = true
            controller.abort()
        }
    }, [packs, loadingPacks, reloadKey])

    const virtualRows = useMemo(() => {
        const totalRows = Math.ceil(stickers.length / GRID_COLUMNS)
        const contentHeight = totalRows * ROW_HEIGHT + 20
        const viewportHeight = Math.max(ROW_HEIGHT + 20, gridHeight || GRID_HEIGHT)
        const startRow = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN_ROWS)
        const endRow = Math.min(totalRows, Math.ceil((scrollTop + gridHeight) / ROW_HEIGHT) + OVERSCAN_ROWS)
        const startIndex = startRow * GRID_COLUMNS
        const endIndex = Math.min(stickers.length, endRow * GRID_COLUMNS)

        return {
            totalRows,
            startRow,
            stickers: stickers.slice(startIndex, endIndex),
            viewportHeight,
            totalHeight: Math.max(viewportHeight, contentHeight)
        }
    }, [stickers, scrollTop, gridHeight])

    const reloadAll = () => {
        stickerMemoryCache.packs = null
        stickerMemoryCache.packsByName.clear()
        stickerMemoryCache.packCovers.clear()
        setPackCovers({})
        clearStickerMediaMemoryCache()
        setReloadKey(key => key + 1)
    }

    return (
        <FloatingPanel
            open
            anchorRef={anchorRef}
            panelRef={pickerRef}
            className="sticker-picker"
            align="right"
            width={380}
            maxHeight={360}
            zIndex={11000}
            stableHeight
        >
            {loadingPacks ? (
                <div className="sticker-picker-state">Завантаження наборів...</div>
            ) : error ? (
                <div className="sticker-picker-state error">
                    <div>{error}</div>
                    <button
                        type="button"
                        className="btn btn-secondary btn-sm sticker-retry-btn"
                        onClick={reloadAll}
                    >
                        Спробувати ще раз
                    </button>
                </div>
            ) : packs.length === 0 ? (
                <div className="sticker-picker-state">У цьому акаунті немає встановлених наборів наліпок.</div>
            ) : (
                <>
                    <div
                        className="sticker-pack-tabs"
                        ref={packTabsRef}
                        onWheel={handlePackTabsWheel}
                    >
                        {packs.map(pack => {
                            const cover = packCovers[pack.short_name]
                            return (
                                <button
                                    key={pack.short_name}
                                    type="button"
                                    className={`sticker-pack-tab ${activePack === pack.short_name ? 'active' : ''}`}
                                    title={pack.title}
                                    aria-label={pack.title}
                                    onClick={() => setActivePack(pack.short_name)}
                                >
                                    <span className="sticker-pack-thumb" aria-hidden="true">
                                        {cover ? (
                                            <StickerPreview sticker={cover} className="sticker-pack-preview" title={pack.title} />
                                        ) : (
                                            <span className="sticker-pack-fallback">{packInitial(pack)}</span>
                                        )}
                                    </span>
                                </button>
                            )
                        })}
                    </div>

                    {loadingStickers ? (
                        <div className="sticker-picker-state">Завантаження наліпок...</div>
                    ) : stickers.length === 0 ? (
                        <div className="sticker-picker-state">У цьому наборі немає наліпок.</div>
                    ) : (
                        <div
                            className="sticker-grid sticker-grid-virtual"
                            ref={gridRef}
                            onScroll={event => setScrollTop(event.currentTarget.scrollTop)}
                        >
                            <div className="sticker-grid-spacer" style={{ height: `${virtualRows.totalHeight}px` }}>
                                <div
                                    className="sticker-grid-window"
                                    style={{ transform: `translateY(${virtualRows.startRow * ROW_HEIGHT}px)` }}
                                >
                                    {virtualRows.stickers.map(sticker => {
                                        const key = stickerKey(sticker)
                                        return (
                                            <button
                                                key={key}
                                                type="button"
                                                className="sticker-btn"
                                                title={sticker.emoji || 'Наліпка'}
                                                onMouseEnter={() => setActiveStickerKey(key)}
                                                onMouseLeave={() => setActiveStickerKey('')}
                                                onFocus={() => setActiveStickerKey(key)}
                                                onBlur={() => setActiveStickerKey('')}
                                                onClick={() => onSelect?.(sticker)}
                                            >
                                                <StickerPreview sticker={sticker} animate={activeStickerKey === key} />
                                            </button>
                                        )
                                    })}
                                </div>
                            </div>
                        </div>
                    )}
                </>
            )}
        </FloatingPanel>
    )
}

export default StickerPicker

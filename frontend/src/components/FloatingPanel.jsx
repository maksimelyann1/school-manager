import { useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

const VIEWPORT_MARGIN = 12

function clamp(value, min, max) {
    return Math.min(Math.max(value, min), max)
}

function FloatingPanel({
    open,
    anchorRef,
    panelRef,
    className = '',
    children,
    align = 'left',
    matchWidth = false,
    width = 320,
    maxHeight = 320,
    zIndex = 10000,
    stableHeight = false
}) {
    const [style, setStyle] = useState(null)
    const [placement, setPlacement] = useState('bottom')
    const lockedHeightRef = useRef(null)

    useLayoutEffect(() => {
        if (!open) {
            setStyle(null)
            setPlacement('bottom')
            lockedHeightRef.current = null
            return undefined
        }
        lockedHeightRef.current = null
        let resizeFrame = 0

        const updatePosition = () => {
            const anchor = anchorRef?.current
            if (!anchor) return

            const rect = anchor.getBoundingClientRect()
            const viewportWidth = window.innerWidth
            const viewportHeight = window.innerHeight
            const resolvedWidth = matchWidth
                ? rect.width
                : Math.min(width, viewportWidth - VIEWPORT_MARGIN * 2)
            const maxViewportHeight = Math.max(120, viewportHeight - VIEWPORT_MARGIN * 2)
            const contentHeight = panelRef?.current?.scrollHeight || maxHeight
            const desiredHeight = Math.min(
                contentHeight,
                maxHeight,
                maxViewportHeight
            )
            const stablePanelHeight = Math.min(maxHeight, maxViewportHeight)
            if (stableHeight && lockedHeightRef.current === null) {
                lockedHeightRef.current = stablePanelHeight
            }
            const stableLockedHeight = Math.max(120, Math.min(lockedHeightRef.current || stablePanelHeight, maxViewportHeight))

            const spaceBelow = viewportHeight - rect.bottom - VIEWPORT_MARGIN
            const spaceAbove = rect.top - VIEWPORT_MARGIN
            const openAbove = spaceBelow < (stableHeight ? stableLockedHeight : desiredHeight) && spaceAbove > spaceBelow
            const preferredSpace = openAbove ? spaceAbove : spaceBelow
            const availableHeight = stableHeight
                ? stableLockedHeight
                : Math.max(120, Math.min(preferredSpace, maxHeight, desiredHeight))
            const leftBase = align === 'right' ? rect.right - resolvedWidth : rect.left
            const left = clamp(leftBase, VIEWPORT_MARGIN, viewportWidth - resolvedWidth - VIEWPORT_MARGIN)
            const preferredTop = openAbove ? rect.top - availableHeight - 8 : rect.bottom + 8
            const top = stableHeight
                ? clamp(preferredTop, VIEWPORT_MARGIN, viewportHeight - availableHeight - VIEWPORT_MARGIN)
                : (openAbove
                    ? Math.max(VIEWPORT_MARGIN, rect.top - availableHeight - 8)
                    : Math.min(rect.bottom + 8, viewportHeight - availableHeight - VIEWPORT_MARGIN))
            const anchorCenter = rect.left + rect.width / 2
            const arrowX = clamp(anchorCenter - left, 18, resolvedWidth - 18)
            const nextPlacement = openAbove ? 'top' : 'bottom'

            const nextStyle = {
                position: 'fixed',
                left: `${left}px`,
                top: `${top}px`,
                width: `${resolvedWidth}px`,
                ...(stableHeight ? { height: `${availableHeight}px` } : {}),
                maxHeight: `${availableHeight}px`,
                zIndex,
                '--floating-max-height': `${availableHeight}px`,
                '--floating-arrow-x': `${arrowX}px`
            }

            setPlacement(current => current === nextPlacement ? current : nextPlacement)
            setStyle(current => {
                if (
                    current &&
                    Object.keys(current).length === Object.keys(nextStyle).length &&
                    Object.keys(nextStyle).every(key => current[key] === nextStyle[key])
                ) {
                    return current
                }
                return nextStyle
            })
        }

        const scheduleUpdate = () => {
            if (resizeFrame) window.cancelAnimationFrame(resizeFrame)
            resizeFrame = window.requestAnimationFrame(() => {
                resizeFrame = 0
                updatePosition()
            })
        }

        const handleScroll = (event) => {
            if (panelRef?.current?.contains(event.target)) {
                return
            }
            updatePosition()
        }

        updatePosition()
        const resizeObserver = typeof ResizeObserver !== 'undefined' && panelRef?.current
            ? new ResizeObserver(scheduleUpdate)
            : null
        if (resizeObserver && panelRef.current) {
            resizeObserver.observe(panelRef.current)
        }
        window.addEventListener('resize', updatePosition)
        window.addEventListener('scroll', handleScroll, true)
        return () => {
            if (resizeFrame) window.cancelAnimationFrame(resizeFrame)
            if (resizeObserver) resizeObserver.disconnect()
            window.removeEventListener('resize', updatePosition)
            window.removeEventListener('scroll', handleScroll, true)
        }
    }, [align, anchorRef, matchWidth, maxHeight, open, panelRef, stableHeight, width, zIndex])

    if (!open) return null

    const initialWidth = (() => {
        if (typeof window === 'undefined') return width
        const viewportWidth = window.innerWidth
        const anchor = anchorRef?.current
        if (matchWidth && anchor) return anchor.getBoundingClientRect().width
        return Math.min(width, Math.max(120, viewportWidth - VIEWPORT_MARGIN * 2))
    })()
    const initialMaxHeight = typeof window === 'undefined'
        ? maxHeight
        : Math.min(maxHeight, Math.max(120, window.innerHeight - VIEWPORT_MARGIN * 2))
    const panelStyle = style || {
        position: 'fixed',
        left: '0px',
        top: '0px',
        width: `${initialWidth}px`,
        ...(stableHeight ? { height: `${initialMaxHeight}px` } : {}),
        maxHeight: `${initialMaxHeight}px`,
        visibility: 'hidden',
        pointerEvents: 'none',
        zIndex,
        '--floating-max-height': `${initialMaxHeight}px`,
        '--floating-arrow-x': '50%'
    }

    return createPortal(
        <div
            ref={panelRef}
            className={`${className} floating-panel`}
            style={panelStyle}
            data-placement={placement}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onWheel={(event) => event.stopPropagation()}
        >
            {children}
        </div>,
        document.body
    )
}

export default FloatingPanel

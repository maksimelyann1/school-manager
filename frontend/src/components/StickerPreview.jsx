import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { loadStickerMedia } from '../utils/stickerMediaQueue'

const API_ORIGIN = import.meta.env.PROD ? '' : 'http://localhost:8001'

const resolveStickerUrl = (sticker, field) => {
    const url = sticker?.[field] || ''
    if (!url) return ''
    if (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('blob:') || url.startsWith('data:')) return url
    return `${API_ORIGIN}${url}`
}

function LottieSticker({ src, label, onFailed }) {
    const containerRef = useRef(null)

    useEffect(() => {
        if (!containerRef.current || !src) return undefined
        let animation = null
        let cancelled = false

        import('lottie-web').then((module) => {
            if (cancelled || !containerRef.current) return
            const lottie = module.default || module
            animation = lottie.loadAnimation({
                container: containerRef.current,
                renderer: 'svg',
                loop: true,
                autoplay: true,
                path: src,
                rendererSettings: {
                    preserveAspectRatio: 'xMidYMid meet'
                }
            })
            animation.addEventListener('data_failed', onFailed)
            animation.addEventListener('error', onFailed)
        }).catch(onFailed)

        return () => {
            cancelled = true
            if (animation) animation.destroy()
        }
    }, [src, onFailed])

    return <div ref={containerRef} className="sticker-lottie" aria-label={label} />
}

function StickerPreview({ sticker, className = '', animate = false }) {
    const previewRef = useRef(null)
    const [isVisible, setIsVisible] = useState(false)
    const [thumbObjectUrl, setThumbObjectUrl] = useState('')
    const [animationObjectUrl, setAnimationObjectUrl] = useState('')
    const [thumbFailed, setThumbFailed] = useState(false)
    const [animationFailed, setAnimationFailed] = useState(false)
    const [thumbLoading, setThumbLoading] = useState(false)

    const label = sticker?.emoji || 'Наліпка'
    const placeholderLabel = Array.from(sticker?.emoji || '').slice(0, 3).join('') || '…'
    const thumbSrc = useMemo(
        () => resolveStickerUrl(sticker, 'thumb_url') || resolveStickerUrl(sticker, 'preview_url'),
        [sticker]
    )
    const animationSrc = useMemo(
        () => resolveStickerUrl(sticker, 'animation_url') || resolveStickerUrl(sticker, 'preview_url'),
        [sticker]
    )
    const hasAnimatedMedia = !!animationSrc && (
        sticker?.is_animated ||
        sticker?.is_video ||
        sticker?.mime_type === 'application/x-tgsticker' ||
        sticker?.mime_type === 'video/webm'
    )
    const thumbnailRequestUrl = thumbSrc || (!hasAnimatedMedia ? animationSrc : '')
    const thumbnailKind = thumbSrc ? 'thumb' : 'animation'
    const wantsAnimation = animate && isVisible && hasAnimatedMedia && !!animationSrc && !animationFailed
    const handleAnimationFailed = useCallback(() => setAnimationFailed(true), [])

    useEffect(() => {
        setIsVisible(false)
        setThumbObjectUrl('')
        setAnimationObjectUrl('')
        setThumbFailed(false)
        setAnimationFailed(false)
        setThumbLoading(false)
    }, [thumbnailRequestUrl, animationSrc])

    useEffect(() => {
        const node = previewRef.current
        if (!node) return undefined

        if (!('IntersectionObserver' in window)) {
            setIsVisible(true)
            return undefined
        }

        const observer = new IntersectionObserver((entries) => {
            setIsVisible(entries.some(entry => entry.isIntersecting))
        }, { root: null, rootMargin: '120px' })

        observer.observe(node)
        return () => observer.disconnect()
    }, [thumbnailRequestUrl, animationSrc])

    useEffect(() => {
        if (!isVisible || !thumbnailRequestUrl || thumbFailed) return undefined

        const controller = new AbortController()
        setThumbLoading(true)
        loadStickerMedia(thumbnailRequestUrl, thumbnailKind, controller.signal)
            .then((objectUrl) => {
                if (!controller.signal.aborted) setThumbObjectUrl(objectUrl)
            })
            .catch((error) => {
                if (error?.name !== 'AbortError' && !controller.signal.aborted) setThumbFailed(true)
            })
            .finally(() => {
                if (!controller.signal.aborted) setThumbLoading(false)
            })

        return () => controller.abort()
    }, [isVisible, thumbnailRequestUrl, thumbnailKind, thumbFailed])

    useEffect(() => {
        setAnimationObjectUrl('')
        if (!wantsAnimation) return undefined

        const controller = new AbortController()
        loadStickerMedia(animationSrc, 'animation', controller.signal)
            .then((objectUrl) => {
                if (!controller.signal.aborted) setAnimationObjectUrl(objectUrl)
            })
            .catch((error) => {
                if (error?.name !== 'AbortError' && !controller.signal.aborted) setAnimationFailed(true)
            })

        return () => controller.abort()
    }, [wantsAnimation, animationSrc])

    const content = (() => {
        if (wantsAnimation && animationObjectUrl) {
            if (sticker?.is_animated || sticker?.mime_type === 'application/x-tgsticker') {
                return <LottieSticker src={animationObjectUrl} label={label} onFailed={handleAnimationFailed} />
            }

            if (sticker?.is_video || sticker?.mime_type === 'video/webm') {
                return (
                    <video
                        className="sticker-preview-media"
                        src={animationObjectUrl}
                        autoPlay
                        muted
                        loop
                        playsInline
                        preload="metadata"
                        title={label}
                        onError={handleAnimationFailed}
                    />
                )
            }
        }

        if (thumbObjectUrl && !thumbFailed) {
            return (
                <img
                    className="sticker-preview-media"
                    src={thumbObjectUrl}
                    alt={label}
                    draggable={false}
                    onError={() => setThumbFailed(true)}
                />
            )
        }

        return (
            <span className={`sticker-preview-placeholder ${thumbLoading ? 'loading' : ''}`}>
                {placeholderLabel}
            </span>
        )
    })()

    return (
        <span ref={previewRef} className={`sticker-preview ${className}`} title={label}>
            {content}
        </span>
    )
}

export default StickerPreview

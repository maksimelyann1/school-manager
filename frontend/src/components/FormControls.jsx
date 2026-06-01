import { useEffect, useMemo, useRef, useState } from 'react'
import FloatingPanel from './FloatingPanel'

const pad2 = (value) => String(value).padStart(2, '0')

const clampNumber = (value, min, max) => Math.min(max, Math.max(min, Number(value) || 0))

const formatTime = (hour, minute) => `${pad2(clampNumber(hour, 0, 23))}:${pad2(clampNumber(minute, 0, 59))}`

const timeFromInput = (rawValue, fallback = '00:00') => {
    const raw = String(rawValue || '').trim()
    const fallbackMatch = /^(\d{1,2}):(\d{1,2})$/.exec(String(fallback || '00:00'))
    const fallbackMinute = fallbackMatch ? Number(fallbackMatch[2]) : 0
    const colonMatch = /^(\d{1,2})(?::(\d{0,2}))?$/.exec(raw)

    if (colonMatch) {
        const hour = colonMatch[1] || '0'
        const minute = colonMatch[2] === undefined || colonMatch[2] === '' ? fallbackMinute : colonMatch[2]
        return formatTime(hour, minute)
    }

    const digits = raw.replace(/\D/g, '').slice(0, 4)
    if (!digits) return formatTime(0, fallbackMinute)
    if (digits.length <= 2) return formatTime(digits, fallbackMinute)
    if (digits.length === 3) return formatTime(digits.slice(0, 1), digits.slice(1))
    return formatTime(digits.slice(0, 2), digits.slice(2))
}

const draftTimeValue = (rawValue) => {
    const raw = String(rawValue || '')
    const cleaned = raw.replace(/[^\d:]/g, '')
    if (cleaned.includes(':')) {
        const [rawHour = '', rawMinute = ''] = cleaned.split(':')
        const hour = rawHour.replace(/\D/g, '').slice(0, 2)
        const minute = rawMinute.replace(/\D/g, '').slice(0, 2)
        return `${hour}:${minute}`
    }

    const digits = raw.replace(/\D/g, '').slice(0, 4)
    if (!digits) return ''
    if (digits.length <= 2) return digits
    return `${digits.slice(0, 2)}:${digits.slice(2)}`
}

export function AppSelect({
    value,
    options,
    onChange,
    placeholder = 'Оберіть...',
    disabled = false,
    className = '',
    ariaLabel
}) {
    const [isOpen, setIsOpen] = useState(false)
    const rootRef = useRef(null)
    const buttonRef = useRef(null)
    const menuRef = useRef(null)
    const selectedOption = options.find(option => String(option.value) === String(value))

    useEffect(() => {
        if (!isOpen) return undefined

        const handlePointerDown = (event) => {
            const insideRoot = rootRef.current && rootRef.current.contains(event.target)
            const insideMenu = menuRef.current && menuRef.current.contains(event.target)
            if (!insideRoot && !insideMenu) {
                setIsOpen(false)
            }
        }

        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                setIsOpen(false)
                buttonRef.current?.focus()
            }
        }

        document.addEventListener('mousedown', handlePointerDown)
        document.addEventListener('keydown', handleKeyDown)
        return () => {
            document.removeEventListener('mousedown', handlePointerDown)
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [isOpen])

    const chooseOption = (option) => {
        onChange?.(option.value)
        setIsOpen(false)
        buttonRef.current?.focus()
    }

    return (
        <div className={`app-select ${className}`} ref={rootRef}>
            <button
                ref={buttonRef}
                type="button"
                className={`app-select-button ${isOpen ? 'open' : ''}`}
                onClick={() => !disabled && setIsOpen(prev => !prev)}
                disabled={disabled}
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                aria-label={ariaLabel}
            >
                <span>{selectedOption?.label || placeholder}</span>
                <span className="app-select-chevron" aria-hidden="true">▾</span>
            </button>

            <FloatingPanel
                open={isOpen}
                anchorRef={buttonRef}
                panelRef={menuRef}
                className="app-select-menu"
                matchWidth
                maxHeight={280}
                zIndex={11000}
            >
                    {options.map(option => {
                        const selected = String(option.value) === String(value)
                        return (
                            <button
                                key={String(option.value)}
                                type="button"
                                className={`app-select-option ${selected ? 'selected' : ''}`}
                                onClick={() => chooseOption(option)}
                                role="option"
                                aria-selected={selected}
                            >
                                {option.label}
                            </button>
                        )
                    })}
            </FloatingPanel>
        </div>
    )
}

export function TimePicker({
    value = '00:00',
    onChange,
    disabled = false,
    className = '',
    ariaLabel = 'Вибрати час'
}) {
    const [isOpen, setIsOpen] = useState(false)
    const rootRef = useRef(null)
    const buttonRef = useRef(null)
    const inputRef = useRef(null)
    const menuRef = useRef(null)
    const [isEditing, setIsEditing] = useState(false)
    const [draftValue, setDraftValue] = useState(value || '00:00')
    const [hourValue, minuteValue] = useMemo(() => {
        const match = /^(\d{1,2}):(\d{1,2})$/.exec(String(value || ''))
        if (!match) return ['00', '00']
        return [pad2(Math.min(23, Math.max(0, Number(match[1])))), pad2(Math.min(59, Math.max(0, Number(match[2]))))]
    }, [value])

    const hours = useMemo(() => Array.from({ length: 24 }, (_, index) => pad2(index)), [])
    const minutes = useMemo(() => Array.from({ length: 60 }, (_, index) => pad2(index)), [])

    useEffect(() => {
        if (!isEditing) {
            setDraftValue(`${hourValue}:${minuteValue}`)
        }
    }, [hourValue, minuteValue, isEditing])

    useEffect(() => {
        if (!isOpen) return undefined

        const handlePointerDown = (event) => {
            const insideRoot = rootRef.current && rootRef.current.contains(event.target)
            const insideMenu = menuRef.current && menuRef.current.contains(event.target)
            if (!insideRoot && !insideMenu) {
                setIsOpen(false)
            }
        }

        const handleKeyDown = (event) => {
            if (event.key === 'Escape') setIsOpen(false)
        }

        document.addEventListener('mousedown', handlePointerDown)
        document.addEventListener('keydown', handleKeyDown)
        return () => {
            document.removeEventListener('mousedown', handlePointerDown)
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [isOpen])

    const commitTime = (raw = draftValue) => {
        const nextValue = timeFromInput(raw, `${hourValue}:${minuteValue}`)
        setDraftValue(nextValue)
        onChange?.(nextValue)
        return nextValue
    }

    const selectTimePart = (nextHour, nextMinute) => {
        const nextValue = `${nextHour}:${nextMinute}`
        setDraftValue(nextValue)
        onChange?.(nextValue)
    }

    const handleInputChange = (event) => {
        const nextDraft = draftTimeValue(event.target.value)
        setDraftValue(nextDraft)
        if (/^\d{1,2}:\d{2}$/.test(nextDraft)) {
            onChange?.(timeFromInput(nextDraft, `${hourValue}:${minuteValue}`))
        }
    }

    const handleInputKeyDown = (event) => {
        if (event.key === 'Enter') {
            event.preventDefault()
            commitTime()
            setIsOpen(false)
        } else if (event.key === 'Escape') {
            event.preventDefault()
            setDraftValue(`${hourValue}:${minuteValue}`)
            setIsOpen(false)
            setIsEditing(false)
        }
    }

    const renderColumn = (items, current, onPick, label) => (
        <div className="app-time-column" role="listbox" aria-label={label}>
            {items.map(item => (
                <button
                    key={item}
                    type="button"
                    className={`app-time-option ${item === current ? 'selected' : ''}`}
                    onClick={() => onPick(item)}
                    role="option"
                    aria-selected={item === current}
                >
                    {item}
                </button>
            ))}
        </div>
    )

    return (
        <div className={`app-time-picker ${disabled ? 'disabled' : ''} ${className}`} ref={rootRef}>
            <div
                ref={buttonRef}
                className={`app-time-button ${isOpen ? 'open' : ''}`}
                onClick={() => {
                    if (disabled) return
                    setIsOpen(true)
                    inputRef.current?.focus()
                }}
                aria-haspopup="dialog"
                aria-expanded={isOpen}
            >
                <input
                    ref={inputRef}
                    type="text"
                    inputMode="numeric"
                    className="app-time-input"
                    value={isEditing ? draftValue : `${hourValue}:${minuteValue}`}
                    onChange={handleInputChange}
                    onFocus={(event) => {
                        const input = event.currentTarget
                        setIsEditing(true)
                        setDraftValue(`${hourValue}:${minuteValue}`)
                        setIsOpen(true)
                        requestAnimationFrame(() => input.select())
                    }}
                    onBlur={(event) => {
                        commitTime(event.currentTarget.value)
                        setIsEditing(false)
                    }}
                    onKeyDown={handleInputKeyDown}
                    disabled={disabled}
                    aria-label={ariaLabel}
                    placeholder="00:00"
                    maxLength={5}
                />
                <button
                    type="button"
                    className="app-time-icon"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={(event) => {
                        event.stopPropagation()
                        if (!disabled) setIsOpen(prev => !prev)
                    }}
                    disabled={disabled}
                    aria-label={ariaLabel}
                >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="9" />
                        <path d="M12 7v5l3 2" />
                    </svg>
                </button>
            </div>

            <FloatingPanel
                open={isOpen}
                anchorRef={buttonRef}
                panelRef={menuRef}
                className="app-time-menu"
                matchWidth
                maxHeight={260}
                zIndex={11000}
            >
                    {renderColumn(hours, hourValue, hour => selectTimePart(hour, minuteValue), 'Години')}
                    {renderColumn(minutes, minuteValue, minute => selectTimePart(hourValue, minute), 'Хвилини')}
            </FloatingPanel>
        </div>
    )
}

export function NumberStepper({
    value,
    onChange,
    min = 0,
    max = 1000,
    step = 1,
    disabled = false,
    className = '',
    ariaLabel
}) {
    const normalize = (nextValue) => {
        const numeric = Number(nextValue)
        if (!Number.isFinite(numeric)) return min
        return Math.min(max, Math.max(min, numeric))
    }

    const commit = (nextValue) => {
        onChange?.(normalize(nextValue))
    }

    const adjust = (direction) => {
        commit(Number(value || 0) + (direction * step))
    }

    return (
        <div className={`number-stepper ${className}`}>
            <input
                type="text"
                inputMode="numeric"
                className="number-stepper-input"
                value={value}
                onChange={(event) => commit(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'ArrowUp') {
                        event.preventDefault()
                        adjust(1)
                    } else if (event.key === 'ArrowDown') {
                        event.preventDefault()
                        adjust(-1)
                    }
                }}
                onWheel={(event) => {
                    if (disabled || document.activeElement !== event.currentTarget) return
                    event.preventDefault()
                    adjust(event.deltaY < 0 ? 1 : -1)
                }}
                disabled={disabled}
                aria-label={ariaLabel}
            />
            <div className="number-stepper-buttons" aria-hidden="false">
                <button
                    type="button"
                    className="number-stepper-button"
                    onClick={() => commit(Number(value) + step)}
                    disabled={disabled || Number(value) >= max}
                    aria-label="Збільшити"
                >
                    ▲
                </button>
                <button
                    type="button"
                    className="number-stepper-button"
                    onClick={() => commit(Number(value) - step)}
                    disabled={disabled || Number(value) <= min}
                    aria-label="Зменшити"
                >
                    ▼
                </button>
            </div>
        </div>
    )
}

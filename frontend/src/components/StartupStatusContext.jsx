import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { API_URL } from '../api/client'

const StartupStatusContext = createContext({ progress: null, unavailable: false })

export const useStartupStatus = () => useContext(StartupStatusContext)

export default function StartupStatusProvider({ children }) {
    const [progress, setProgress] = useState(null)
    const [unavailable, setUnavailable] = useState(false)
    const completed = useRef(new Set())

    useEffect(() => {
        const controller = new AbortController()
        let timer
        let failures = 0
        const poll = async () => {
            try {
                const response = await fetch(`${API_URL}/startup`, { signal: controller.signal })
                if (!response.ok) throw new Error('Startup status unavailable')
                const data = await response.json()
                if (controller.signal.aborted) return
                setProgress(data)
                setUnavailable(false)
                failures = 0
                for (const [key, step] of Object.entries(data.steps)) {
                    if (step.state === 'done' && !completed.current.has(key)) {
                        completed.current.add(key)
                        window.dispatchEvent(new CustomEvent('startup-sync-complete', { detail: { service: key } }))
                    }
                }
                if (data.finished) return
            } catch (error) {
                if (controller.signal.aborted) return
                if (++failures >= 3) setUnavailable(true)
            }
            if (!controller.signal.aborted) timer = window.setTimeout(poll, 1000)
        }
        poll()
        return () => { controller.abort(); window.clearTimeout(timer) }
    }, [])

    return (
        <StartupStatusContext.Provider value={{ progress, unavailable }}>
            {children}
        </StartupStatusContext.Provider>
    )
}

const QUEUE_LIMITS = {
    thumb: 2,
    animation: 1
}

const queues = {
    thumb: { active: 0, pending: [], activeTasks: new Set() },
    animation: { active: 0, pending: [], activeTasks: new Set() }
}

const mediaCache = new Map()
const pendingByUrl = new Map()

const createAbortError = () => {
    try {
        return new DOMException('Aborted', 'AbortError')
    } catch {
        const error = new Error('Aborted')
        error.name = 'AbortError'
        return error
    }
}

const normalizeKind = (kind) => (kind === 'animation' ? 'animation' : 'thumb')

const removeTask = (queue, task) => {
    const index = queue.pending.indexOf(task)
    if (index >= 0) queue.pending.splice(index, 1)
}

const pumpQueue = (kind) => {
    const queue = queues[kind]
    const limit = QUEUE_LIMITS[kind]

    while (queue.active < limit && queue.pending.length > 0) {
        const task = queue.pending.shift()
        if (!task || task.cancelled) {
            task?.cleanup?.()
            continue
        }

        queue.active += 1
        runTask(kind, task)
    }
}

const runTask = async (kind, task) => {
    task.started = true
    task.controller = new AbortController()
    queues[kind].activeTasks.add(task)

    const abortFromCaller = () => {
        task.cancelled = true
        task.controller?.abort()
    }
    if (task.signal) {
        if (task.signal.aborted) abortFromCaller()
        else task.signal.addEventListener('abort', abortFromCaller, { once: true })
    }

    try {
        if (task.cancelled) throw createAbortError()

        const response = await fetch(task.url, { signal: task.controller.signal })
        if (!response.ok) {
            const message = await response.text().catch(() => '')
            throw new Error(message || `HTTP ${response.status}`)
        }

        const blob = await response.blob()
        if (task.cancelled) throw createAbortError()

        const objectUrl = URL.createObjectURL(blob)
        mediaCache.set(task.url, objectUrl)
        task.resolve(objectUrl)
    } catch (error) {
        task.reject(error)
    } finally {
        queues[kind].activeTasks.delete(task)
        task.cleanup?.()
        pendingByUrl.delete(task.url)
        queues[kind].active = Math.max(0, queues[kind].active - 1)
        pumpQueue(kind)
    }
}

const mirrorAbort = (promise, signal) => {
    if (!signal) return promise
    if (signal.aborted) return Promise.reject(createAbortError())

    return new Promise((resolve, reject) => {
        const abort = () => reject(createAbortError())
        signal.addEventListener('abort', abort, { once: true })
        promise.then(resolve, reject).finally(() => {
            signal.removeEventListener('abort', abort)
        })
    })
}

export const loadStickerMedia = (url, kind = 'thumb', signal = null) => {
    if (!url) return Promise.resolve('')
    if (signal?.aborted) return Promise.reject(createAbortError())
    const cached = mediaCache.get(url)
    if (cached) return Promise.resolve(cached)

    const existing = pendingByUrl.get(url)
    if (existing) return mirrorAbort(existing, signal)

    const queueKind = normalizeKind(kind)
    const queue = queues[queueKind]

    let task
    const promise = new Promise((resolve, reject) => {
        task = {
            url,
            signal,
            resolve,
            reject,
            started: false,
            cancelled: false,
            controller: null,
            cleanup: null
        }

        const abort = () => {
            task.cancelled = true
            if (task.started) task.controller?.abort()
            else {
                removeTask(queue, task)
                pendingByUrl.delete(url)
                reject(createAbortError())
            }
        }

        task.cleanup = () => {
            signal?.removeEventListener('abort', abort)
        }

        if (signal?.aborted) {
            reject(createAbortError())
            return
        }

        signal?.addEventListener('abort', abort, { once: true })
        queue.pending.push(task)
        pumpQueue(queueKind)
    })

    pendingByUrl.set(url, promise)
    return promise
}

export const clearStickerMediaMemoryCache = () => {
    for (const queue of Object.values(queues)) {
        for (const task of queue.activeTasks) {
            task.cancelled = true
            task.controller?.abort()
        }
        queue.activeTasks.clear()

        for (const task of queue.pending) {
            task.cancelled = true
            task.cleanup?.()
            task.reject?.(createAbortError())
        }
        queue.pending = []
    }

    for (const url of mediaCache.values()) {
        URL.revokeObjectURL(url)
    }
    mediaCache.clear()
    pendingByUrl.clear()
}

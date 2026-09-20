export function reportClientError(moduleName, message) {
    try {
        fetch(buildApiUrl('/logs/client'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                level: 'ERROR',
                module: moduleName || 'Frontend',
                message: String(message || '')
            })
        }).catch(() => {})
    } catch (_) {}
}

export const API_URL = import.meta.env.PROD ? '/api' : 'http://localhost:8001/api'

export function buildApiUrl(path) {
    if (!path) return API_URL
    if (/^https?:\/\//i.test(path)) return path
    return `${API_URL}${path.startsWith('/') ? path : `/${path}`}`
}

async function readResponseBody(response) {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
        return response.json().catch(() => ({}))
    }
    return response.text().catch(() => '')
}

export async function apiFetch(path, options = {}) {
    const response = await fetch(buildApiUrl(path), options)
    const data = await readResponseBody(response)

    if (!response.ok) {
        const message = data?.detail || data?.error || data?.message || response.statusText || 'Request failed'
        const error = new Error(message)
        error.status = response.status
        error.data = data
        throw error
    }

    return data
}

export function jsonOptions(method, body, options = {}) {
    return {
        ...options,
        method,
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {})
        },
        body: body === undefined ? undefined : JSON.stringify(body)
    }
}

export const api = {
    get: (path, options) => apiFetch(path, { ...(options || {}), method: 'GET' }),
    post: (path, body, options) => apiFetch(path, jsonOptions('POST', body, options)),
    put: (path, body, options) => apiFetch(path, jsonOptions('PUT', body, options)),
    patch: (path, body, options) => apiFetch(path, jsonOptions('PATCH', body, options)),
    delete: (path, options) => apiFetch(path, { ...(options || {}), method: 'DELETE' }),
    form: (path, formData, method = 'POST', options = {}) => apiFetch(path, {
        ...options,
        method,
        body: formData
    })
}

import { useCallback } from 'react'
import { apiFetch, jsonOptions } from '../api/client'
import { useToast } from '../components/ToastProvider'

function makeRequest(method, path, body, options = {}) {
    if (body instanceof FormData) {
        return apiFetch(path, { ...options, method, body })
    }
    if (body === undefined) {
        return apiFetch(path, { ...options, method })
    }
    return apiFetch(path, jsonOptions(method, body, options))
}

export function useApi() {
    const { showToast } = useToast()

    const request = useCallback(async (method, path, body, options = {}) => {
        try {
            return await makeRequest(method, path, body, options)
        } catch (error) {
            if (options.toast !== false) {
                showToast({ type: 'error', text: error.message || 'Помилка запиту' })
            }
            throw error
        }
    }, [showToast])

    return {
        request,
        get: useCallback((path, options) => request('GET', path, undefined, options), [request]),
        post: useCallback((path, body, options) => request('POST', path, body, options), [request]),
        put: useCallback((path, body, options) => request('PUT', path, body, options), [request]),
        patch: useCallback((path, body, options) => request('PATCH', path, body, options), [request]),
        delete: useCallback((path, options) => request('DELETE', path, undefined, options), [request]),
        form: useCallback((path, formData, method = 'POST', options = {}) => (
            request(method, path, formData, options)
        ), [request])
    }
}

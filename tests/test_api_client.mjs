import { readFile } from 'node:fs/promises'
import assert from 'node:assert/strict'
import { test } from 'node:test'

const source = (await readFile(new URL('../frontend/src/api/client.js', import.meta.url), 'utf8'))
    .replace('import.meta.env.PROD', 'true')
const { api } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('aborting response body parsing remains an abort, never an empty object', async t => {
    const abort = new DOMException('Aborted', 'AbortError')
    t.mock.method(globalThis, 'fetch', async () => ({ ok: true,
        headers: new Headers({ 'content-type': 'application/json' }), json: async () => { throw abort } }))
    await assert.rejects(api.get('/tasks'), error => error === abort)
})

test('late responses from an already cancelled request are discarded', async t => {
    const controller = new AbortController()
    t.mock.method(globalThis, 'fetch', async () => { controller.abort(); return new Response(JSON.stringify({ items: [] }),
        { headers: { 'content-type': 'application/json' } }) })
    await assert.rejects(api.get('/tasks', { signal: controller.signal }), { name: 'AbortError' })
})

test('broken JSON is reported without replacing the cached calendar data', async t => {
    t.mock.method(globalThis, 'fetch', async () => new Response('{', { headers: { 'content-type': 'application/json' } }))
    await assert.rejects(api.get('/tasks'), /некоректну відповідь/)
})

test('an HTML fallback is rejected instead of reaching calendar rendering', async t => {
    t.mock.method(globalThis, 'fetch', async () => new Response('<html></html>', { headers: { 'content-type': 'text/html' } }))
    await assert.rejects(api.get('/tasks'), /некоректну відповідь/)
})

test('successful JSON and HTTP validation errors keep their original shape', async t => {
    const response = { items: [{ id: 'one' }], total: 1 }
    const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(response))
    assert.deepEqual(await api.get('/tasks'), response)
    fetch.mock.mockImplementation(async () => Response.json({ detail: 'Перевірте дату' }, { status: 422 }))
    await assert.rejects(api.get('/tasks'), error => error.status === 422 && error.message === 'Перевірте дату')
})

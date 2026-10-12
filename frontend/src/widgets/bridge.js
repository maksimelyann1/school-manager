export const widgetKinds = { calendar: 'Календар', agenda: 'Мої справи', lessons: 'Найближчі уроки' }
export const widgetChannel = 'school-manager-widgets'

export async function desktopCall(method, ...args) {
    const call = window.pywebview?.api?.[method]
    if (!call) throw new Error('Керування віджетами доступне у настільній програмі.')
    return call(...args)
}

export function announceChange() {
    if (!window.BroadcastChannel) return
    const channel = new BroadcastChannel(widgetChannel)
    channel.postMessage({ changed: true })
    channel.close()
}

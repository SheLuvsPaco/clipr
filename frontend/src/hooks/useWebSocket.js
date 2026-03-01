import { useEffect, useRef, useState } from 'react'

export function useWebSocket(url, { onMessage, enabled = true }) {
    const wsRef = useRef(null)
    const [connected, setConnected] = useState(false)

    useEffect(() => {
        if (!enabled || !url) return

        const ws = new WebSocket(url)
        wsRef.current = ws

        ws.onopen = () => setConnected(true)
        ws.onclose = () => setConnected(false)
        ws.onerror = () => setConnected(false)

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)
                if (data.type === 'ping') return // ignore keepalive
                onMessage?.(data)
            } catch (e) {
                console.error('WS parse error:', e)
            }
        }

        return () => {
            ws.close()
            wsRef.current = null
        }
    }, [url, enabled])

    return { connected }
}

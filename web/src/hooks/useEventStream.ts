/**
 * SSE hook for real-time event streaming from News API.
 */

import { useEffect, useRef, useCallback } from 'react'
import { usePakoStore } from '../store'
import type {
  PipelineEvent,
  SSEConnectedMessage,
  SSEInitialStateMessage,
  SSEActiveStrategiesMessage,
} from '../types'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8100'
const API_KEY = import.meta.env.VITE_API_KEY || ''

const RECONNECT_DELAY = 3000 // 3 seconds

export function useEventStream() {
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)

  const {
    setConnected,
    setError,
    addEvent,
    setInitialState,
  } = usePakoStore()

  const connect = useCallback(() => {
    // Clean up existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }

    // Build URL with API key as query param (EventSource doesn't support headers)
    const url = new URL('/stream', API_BASE_URL)
    if (API_KEY) {
      url.searchParams.set('api_key', API_KEY)
    }

    try {
      const eventSource = new EventSource(url.toString())
      eventSourceRef.current = eventSource

      eventSource.onopen = () => {
        console.log('[SSE] Connected')
        setConnected(true)
        setError(null)
      }

      eventSource.onerror = (error) => {
        console.error('[SSE] Error:', error)
        setConnected(false)
        setError('Connection lost. Reconnecting...')

        eventSource.close()

        // Schedule reconnect
        reconnectTimeoutRef.current = window.setTimeout(() => {
          console.log('[SSE] Attempting reconnect...')
          connect()
        }, RECONNECT_DELAY)
      }

      // Handle connection message
      eventSource.addEventListener('connected', (e: MessageEvent) => {
        try {
          const data: SSEConnectedMessage = JSON.parse(e.data)
          console.log('[SSE] Connected message:', data)
        } catch (err) {
          console.error('[SSE] Error parsing connected message:', err)
        }
      })

      // Handle initial state and active strategies
      // Both events are needed to initialize the store - handle race condition by storing
      // whichever arrives first and calling setInitialState when both are ready
      let initialEvents: PipelineEvent[] | null = null
      let activeStrategies: SSEActiveStrategiesMessage['strategies'] | null = null

      const trySetInitialState = () => {
        if (initialEvents !== null && activeStrategies !== null) {
          console.log('[SSE] Setting initial state with', initialEvents.length, 'events and', activeStrategies.length, 'strategies')
          setInitialState(initialEvents, activeStrategies)
        }
      }

      eventSource.addEventListener('initial_state', (e: MessageEvent) => {
        try {
          const data: SSEInitialStateMessage = JSON.parse(e.data)
          console.log('[SSE] Initial state received:', data.events.length, 'events')
          initialEvents = data.events
          trySetInitialState()
        } catch (err) {
          console.error('[SSE] Error parsing initial_state:', err)
          initialEvents = []
          trySetInitialState()
        }
      }, { once: true })

      eventSource.addEventListener('active_strategies', (e: MessageEvent) => {
        try {
          const stratData: SSEActiveStrategiesMessage = JSON.parse(e.data)
          console.log('[SSE] Active strategies received:', stratData.strategies.length)
          activeStrategies = stratData.strategies
          trySetInitialState()
        } catch (err) {
          console.error('[SSE] Error parsing active_strategies:', err)
          activeStrategies = []
          trySetInitialState()
        }
      }, { once: true })

      // Handle heartbeat
      eventSource.addEventListener('heartbeat', (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data)
          console.log('[SSE] Heartbeat:', data.timestamp)
        } catch (err) {
          console.error('[SSE] Error parsing heartbeat:', err)
        }
      })

      // Handle pipeline events
      const pipelineEventTypes = [
        'news_received',
        'news_decision',
        'strategy_spawned',
        'order_placed',
        'order_filled',
        'order_cancelled',
        'strategy_stopped',
        'manual_exit_requested',
        'timer_extend_requested',
        'cancel_order_requested',
      ]

      for (const eventType of pipelineEventTypes) {
        eventSource.addEventListener(eventType, (e: MessageEvent) => {
          try {
            const event: PipelineEvent = JSON.parse(e.data)
            console.log(`[SSE] ${eventType}:`, event)
            addEvent(event)
          } catch (err) {
            console.error(`[SSE] Error parsing ${eventType}:`, err)
          }
        })
      }

    } catch (err) {
      console.error('[SSE] Failed to create EventSource:', err)
      setError('Failed to connect')

      // Schedule reconnect
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect()
      }, RECONNECT_DELAY)
    }
  }, [setConnected, setError, addEvent, setInitialState])

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    setConnected(false)
  }, [setConnected])

  // Auto-connect on mount
  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return { connect, disconnect }
}

/**
 * Alternative: Fetch-based SSE for better header support.
 * Use this if you need custom headers and can't modify the server.
 */
export function useFetchEventStream() {
  const abortControllerRef = useRef<AbortController | null>(null)
  const reconnectTimeoutRef = useRef<number | null>(null)

  const {
    setConnected,
    setError,
    addEvent,
    setInitialState,
  } = usePakoStore()

  const connect = useCallback(async () => {
    // Clean up existing connection
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }

    const abortController = new AbortController()
    abortControllerRef.current = abortController

    try {
      const response = await fetch(`${API_BASE_URL}/stream`, {
        headers: {
          'Accept': 'text/event-stream',
          ...(API_KEY ? { 'X-API-Key': API_KEY } : {}),
        },
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setConnected(true)
      setError(null)

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        let currentData = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7)
          } else if (line.startsWith('data: ')) {
            currentData = line.slice(6)
          } else if (line === '' && currentEvent && currentData) {
            // Process complete event
            try {
              const data = JSON.parse(currentData)

              if (currentEvent === 'connected') {
                console.log('[SSE] Connected')
              } else if (currentEvent === 'initial_state') {
                console.log('[SSE] Initial state')
                // Need to wait for active_strategies too
              } else if (currentEvent === 'heartbeat') {
                console.log('[SSE] Heartbeat')
              } else {
                // Pipeline event
                addEvent(data)
              }
            } catch (err) {
              console.error('[SSE] Parse error:', err)
            }

            currentEvent = ''
            currentData = ''
          }
        }
      }

    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        console.log('[SSE] Connection aborted')
        return
      }

      console.error('[SSE] Error:', err)
      setConnected(false)
      setError('Connection lost. Reconnecting...')

      // Schedule reconnect
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect()
      }, RECONNECT_DELAY)
    }
  }, [setConnected, setError, addEvent, setInitialState])

  const disconnect = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    setConnected(false)
  }, [setConnected])

  useEffect(() => {
    connect()
    return () => disconnect()
  }, [connect, disconnect])

  return { connect, disconnect }
}

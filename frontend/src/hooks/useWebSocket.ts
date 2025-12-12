import { useState, useEffect, useCallback, useRef } from 'react'

export interface AgentEvent {
  type: string
  timestamp: string
  session_id?: string
  payload: Record<string, unknown>
}

export interface UseWebSocketOptions {
  onEvent?: (event: AgentEvent) => void
  onConnect?: () => void
  onDisconnect?: () => void
  onError?: (error: Event) => void
  autoReconnect?: boolean
  reconnectInterval?: number
}

export function useWebSocket(sessionId: string | null, options: UseWebSocketOptions = {}) {
  const [isConnected, setIsConnected] = useState(false)
  const [events, setEvents] = useState<AgentEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const connectingRef = useRef(false) // 防止重复连接
  
  const {
    onEvent,
    onConnect,
    onDisconnect,
    onError,
    autoReconnect = true,
    reconnectInterval = 3000,
  } = options

  const connect = useCallback(() => {
    if (!sessionId) return
    
    // 防止重复连接
    if (connectingRef.current) {
      console.log('[WebSocket] 已在连接中，跳过...')
      return
    }
    
    // 如果已经连接到同一个 session，跳过
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] 已连接，跳过重复连接')
      return
    }
    
    connectingRef.current = true
    
    // 构建 WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/${sessionId}`
    
    console.log('[WebSocket] 🔌 开始连接:', wsUrl)
    console.log('[WebSocket] Session ID:', sessionId)
    
    // 关闭之前的连接
    if (wsRef.current) {
      console.log('[WebSocket] 关闭之前的连接')
      wsRef.current.close()
      wsRef.current = null
    }
    
    try {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws
      
      const connectStartTime = Date.now()
      console.log('[WebSocket] 对象已创建, readyState:', ws.readyState)
      
      ws.onopen = () => {
        const connectDuration = Date.now() - connectStartTime
        console.log(`[WebSocket] ✅ 已连接 (耗时 ${connectDuration}ms)`)
        connectingRef.current = false
        setIsConnected(true)
        onConnect?.()
      }
      
      ws.onmessage = (event) => {
        try {
          const data: AgentEvent = JSON.parse(event.data)
          const timestamp = new Date().toLocaleTimeString()
          
          // 详细的事件日志
          console.log(`[WebSocket] 📩 [${timestamp}] 收到: ${data.type}`)
          
          // 对不同类型的事件显示不同的详情
          switch (data.type) {
            case 'connected':
              console.log('[WebSocket]   └─ 连接确认, session:', data.session_id)
              break
            case 'phase_change':
              console.log('[WebSocket]   └─ 阶段变更:', data.payload.phase)
              break
            case 'task_started':
              console.log('[WebSocket]   └─ 开始任务:', data.payload.task_name)
              break
            case 'task_completed':
              console.log('[WebSocket]   └─ 完成任务:', data.payload.task_name)
              break
            case 'task_failed':
              console.log('[WebSocket]   └─ 任务失败:', data.payload.task_name, data.payload.error)
              break
            case 'tool_call':
              console.log('[WebSocket]   └─ 工具调用:', data.payload.tool)
              break
            case 'tool_result':
              console.log('[WebSocket]   └─ 工具结果:', data.payload.tool, data.payload.status)
              break
            case 'code_generated':
              console.log('[WebSocket]   └─ 生成代码, 任务:', data.payload.task_id)
              break
            case 'image_generated':
              console.log('[WebSocket]   └─ 生成图表, 任务:', data.payload.task_id)
              break
            case 'tasks_planned':
              console.log('[WebSocket]   └─ 规划任务数:', (data.payload.tasks as unknown[])?.length)
              break
            case 'agent_completed':
              console.log('[WebSocket]   └─ Agent 完成!')
              break
            case 'agent_error':
              console.error('[WebSocket]   └─ Agent 错误:', data.payload.error)
              break
            case 'heartbeat':
            case 'pong':
              // 心跳消息不记录
              break
            default:
              console.log('[WebSocket]   └─ payload:', JSON.stringify(data.payload).slice(0, 100))
          }
          
          // 跳过心跳消息
          if (data.type !== 'heartbeat' && data.type !== 'pong') {
            setEvents(prev => [...prev, data])
            onEvent?.(data)
          }
        } catch (e) {
          console.error('[WebSocket] 解析消息失败:', e, 'raw:', event.data)
        }
      }
      
      ws.onclose = (event) => {
        console.log('[WebSocket] ❌ 连接关闭')
        console.log('[WebSocket]   └─ code:', event.code, 'reason:', event.reason || '(无)', 'wasClean:', event.wasClean)
        connectingRef.current = false
        setIsConnected(false)
        onDisconnect?.()
        
        // 自动重连（只有非正常关闭才重连）
        if (autoReconnect && sessionId && event.code !== 1000) {
          console.log(`[WebSocket] ⏳ ${reconnectInterval}ms 后重连...`)
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        }
      }
      
      ws.onerror = (error) => {
        console.error('[WebSocket] 🔴 错误:', error)
        console.error('[WebSocket]   └─ readyState:', ws.readyState)
        connectingRef.current = false
        onError?.(error)
      }
      
      // 3秒后检查连接状态
      setTimeout(() => {
        if (ws.readyState !== WebSocket.OPEN) {
          console.warn('[WebSocket] ⚠️ 3秒后仍未连接, readyState:', ws.readyState)
        }
      }, 3000)
      
    } catch (e) {
      console.error('[WebSocket] 创建失败:', e)
      connectingRef.current = false
    }
  }, [sessionId, onEvent, onConnect, onDisconnect, onError, autoReconnect, reconnectInterval])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(message)
    }
  }, [])

  const clearEvents = useCallback(() => {
    setEvents([])
  }, [])

  useEffect(() => {
    if (sessionId) {
      connect()
    }
    
    return () => {
      disconnect()
    }
  }, [sessionId, connect, disconnect])

  // 心跳检测
  useEffect(() => {
    if (!isConnected) return
    
    const heartbeatInterval = setInterval(() => {
      sendMessage('ping')
    }, 25000)
    
    return () => {
      clearInterval(heartbeatInterval)
    }
  }, [isConnected, sendMessage])

  return {
    isConnected,
    events,
    sendMessage,
    clearEvents,
    connect,
    disconnect,
  }
}


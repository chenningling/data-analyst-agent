import { useEffect, useRef, useMemo } from 'react'
import { 
  CheckCircle, 
  XCircle, 
  Database, 
  Image as ImageIcon,
  Terminal,
  Brain,
  Loader2,
  Code,
  AlertTriangle
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CodeBlock } from './CodeBlock'
import type { AgentEvent } from '@/hooks/useWebSocket'

interface AgentProcessProps {
  events: AgentEvent[]
  isConnected: boolean
  currentTaskId?: number | 'planning'
  onTaskClick?: (taskId: number | 'planning') => void
}

// 任务执行分组
interface TaskExecutionGroup {
  taskId: number | 'planning'
  taskName: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  events: ProcessedEvent[]
  startTime?: string
  endTime?: string
}

// 处理后的事件（用于显示）
interface ProcessedEvent {
  id: string
  type: 'data_explored' | 'thinking' | 'code' | 'tool_result' | 'image' | 'error'
  timestamp: string
  data: {
    // data_explored
    schema?: Array<{ name: string; dtype: string }>
    statistics?: { total_rows?: number; total_columns?: number; missing_percentage?: number }
    // thinking
    thinking?: string
    isStreaming?: boolean
    // code
    code?: string
    description?: string
    // tool_result
    tool?: string
    stdout?: string
    status?: string
    // image
    image_base64?: string
    // error
    error?: string
  }
}

// 需要过滤的事件类型
const FILTERED_EVENTS = [
  'connected',
  'agent_started', 
  'phase_change',
  'llm_start',
  'llm_complete',
  'llm_tool_calling',
  'tasks_planned',
  'report_generated',
  'agent_completed',
]

// 判断事件是否应该显示
function shouldShowEvent(event: AgentEvent): boolean {
  // 过滤基础事件
  if (FILTERED_EVENTS.includes(event.type)) return false
  
  // 过滤 todo_write 工具调用
  if (event.type === 'tool_call' && event.payload.tool === 'todo_write') return false
  if (event.type === 'tool_result' && event.payload.tool === 'todo_write') return false
  
  return true
}

// 将原始事件转换为处理后的事件
function processEvent(event: AgentEvent): ProcessedEvent | null {
  const id = `${event.type}-${event.timestamp}-${Math.random().toString(36).slice(2, 8)}`
  
  switch (event.type) {
    case 'data_explored':
      return {
        id,
        type: 'data_explored',
        timestamp: event.timestamp,
        data: {
          schema: event.payload.schema as ProcessedEvent['data']['schema'],
          statistics: event.payload.statistics as ProcessedEvent['data']['statistics'],
        }
      }
    
    case 'llm_streaming':
      // 只处理 reasoning 类型的流式输出
      if (event.payload.type === 'reasoning') {
        return {
          id,
          type: 'thinking',
          timestamp: event.timestamp,
          data: {
            thinking: event.payload.full_content as string,
            isStreaming: true,
          }
        }
      }
      return null
    
    case 'llm_thinking':
      return {
        id,
        type: 'thinking',
        timestamp: event.timestamp,
        data: {
          thinking: event.payload.thinking as string,
          isStreaming: false,
        }
      }
    
    case 'code_generated':
      return {
        id,
        type: 'code',
        timestamp: event.timestamp,
        data: {
          code: event.payload.code as string,
          description: event.payload.description as string,
        }
      }
    
    case 'tool_call':
      // 不单独显示 tool_call 事件（等待 tool_result 来显示完整结果）
      // 只在前端需要即时反馈时显示，这里跳过
      return null
    
    case 'tool_result':
      if (event.payload.tool !== 'todo_write') {
        return {
          id,
          type: 'tool_result',
          timestamp: event.timestamp,
          data: {
            tool: event.payload.tool as string,
            stdout: event.payload.stdout_preview as string,
            status: event.payload.status as string,
          }
        }
      }
      return null
    
    case 'image_generated':
      return {
        id,
        type: 'image',
        timestamp: event.timestamp,
        data: {
          image_base64: event.payload.image_base64 as string,
        }
      }
    
    case 'agent_error':
      return {
        id,
        type: 'error',
        timestamp: event.timestamp,
        data: {
          error: event.payload.error as string,
        }
      }
    
    default:
      return null
  }
}

// 将事件按任务分组
function groupEventsByTask(events: AgentEvent[]): TaskExecutionGroup[] {
  const groups: TaskExecutionGroup[] = []
  
  // 第0步：用户需求分析和任务规划
  let currentGroup: TaskExecutionGroup = {
    taskId: 'planning',
    taskName: '用户需求分析和任务规划',
    status: 'in_progress',
    events: [],
    startTime: events[0]?.timestamp
  }
  
  let taskListCreated = false
  
  for (const event of events) {
    // 检测任务列表创建（第一次 tasks_updated 且 source 是 tool）
    if (event.type === 'tasks_updated' && !taskListCreated) {
      const source = event.payload.source as string
      if (source === 'tool') {
        taskListCreated = true
        currentGroup.status = 'completed'
        currentGroup.endTime = event.timestamp
        groups.push(currentGroup)
        
        // 找到第一个 in_progress 的任务
        const tasks = event.payload.tasks as Array<{ id: number; name: string; status: string }>
        const firstTask = tasks?.find(t => t.status === 'in_progress') || tasks?.[0]
        
        if (firstTask) {
          currentGroup = {
            taskId: firstTask.id,
            taskName: firstTask.name,
            status: firstTask.status as TaskExecutionGroup['status'],
            events: [],
            startTime: event.timestamp
          }
        }
        continue
      }
    }
    
    // 检测任务切换
    if (event.type === 'tasks_updated' && taskListCreated) {
      const tasks = event.payload.tasks as Array<{ id: number; name: string; status: string }>
      
      // 找到当前 in_progress 的任务
      const inProgressTask = tasks?.find(t => t.status === 'in_progress')
      
      // 检查当前任务是否完成
      const currentTask = tasks?.find(t => t.id === currentGroup.taskId)
      if (currentTask && currentTask.status === 'completed' && currentGroup.status !== 'completed') {
        currentGroup.status = 'completed'
        currentGroup.endTime = event.timestamp
      }
      
      // 如果有新的 in_progress 任务且不是当前任务
      if (inProgressTask && inProgressTask.id !== currentGroup.taskId) {
        // 保存当前组
        if (currentGroup.events.length > 0 || currentGroup.taskId === 'planning') {
          groups.push(currentGroup)
        }
        
        // 创建新组
        currentGroup = {
          taskId: inProgressTask.id,
          taskName: inProgressTask.name,
          status: 'in_progress',
          events: [],
          startTime: event.timestamp
        }
      }
      continue
    }
    
    // 处理并添加事件到当前组
    if (shouldShowEvent(event)) {
      const processed = processEvent(event)
      if (processed) {
        // 合并 thinking 事件：避免重复显示相同或相似的思考内容
        if (processed.type === 'thinking') {
          const lastEvent = currentGroup.events[currentGroup.events.length - 1]
          if (lastEvent?.type === 'thinking') {
            const lastThinking = lastEvent.data.thinking || ''
            const currentThinking = processed.data.thinking || ''
            
            // 如果内容相同，或者新内容是旧内容的扩展，或者旧内容是新内容的前缀，则替换
            if (currentThinking === lastThinking ||
                currentThinking.startsWith(lastThinking.slice(0, 50)) ||
                lastThinking.startsWith(currentThinking.slice(0, 50))) {
              // 保留更完整的内容
              if (currentThinking.length >= lastThinking.length) {
                currentGroup.events[currentGroup.events.length - 1] = processed
              }
              continue
            }
          }
        }
        currentGroup.events.push(processed)
      }
    }
  }
  
  // 添加最后一组
  if (currentGroup.events.length > 0 || groups.length === 0) {
    groups.push(currentGroup)
  }
  
  return groups
}

export function AgentProcess({ events, isConnected, currentTaskId, onTaskClick }: AgentProcessProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const taskRefs = useRef<Map<number | 'planning', HTMLDivElement>>(new Map())
  
  // 将事件按任务分组
  const taskGroups = useMemo(() => groupEventsByTask(events), [events])
  
  // 自动滚动到当前任务
  useEffect(() => {
    if (currentTaskId !== undefined) {
      const taskRef = taskRefs.current.get(currentTaskId)
      if (taskRef) {
        taskRef.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }, [currentTaskId])

  // 自动滚动到底部（跟踪最新进度）
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events.length])

  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <Terminal className="w-12 h-12 mb-4 opacity-50" />
        <p className="text-sm">等待 Agent 启动...</p>
        {!isConnected && (
          <p className="text-xs text-yellow-400 mt-2">WebSocket 未连接</p>
        )}
      </div>
    )
  }

  return (
    <div 
      ref={containerRef}
      className="space-y-4 max-h-[700px] overflow-y-auto pr-2"
    >
      {taskGroups.map((group) => (
        <TaskGroupCard
          key={group.taskId}
          group={group}
          isActive={currentTaskId === group.taskId}
          ref={(el) => {
            if (el) taskRefs.current.set(group.taskId, el)
          }}
          onClick={() => onTaskClick?.(group.taskId)}
        />
      ))}
      
      {/* 处理中指示器 */}
      {isConnected && !events.some(e => e.type === 'agent_completed' || e.type === 'agent_error') && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-primary/10 border border-primary/30">
          <Loader2 className="w-4 h-4 text-primary animate-spin" />
          <span className="text-sm text-primary">Agent 正在工作...</span>
        </div>
      )}
    </div>
  )
}

// 任务分组卡片
interface TaskGroupCardProps {
  group: TaskExecutionGroup
  isActive: boolean
  onClick?: () => void
}

import { forwardRef } from 'react'

const TaskGroupCard = forwardRef<HTMLDivElement, TaskGroupCardProps>(
  ({ group, isActive, onClick }, ref) => {
    const formatTime = (timestamp?: string) => {
      if (!timestamp) return ''
      return new Date(timestamp).toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
    }

    const getStatusIcon = () => {
      switch (group.status) {
        case 'in_progress':
          return <Loader2 className="w-4 h-4 text-primary animate-spin" />
        case 'completed':
          return <CheckCircle className="w-4 h-4 text-green-400" />
        case 'failed':
          return <XCircle className="w-4 h-4 text-destructive" />
        default:
          return <div className="w-4 h-4 rounded-full border-2 border-muted-foreground/30" />
      }
    }

    const getStatusBadge = () => {
      switch (group.status) {
        case 'in_progress':
          return <span className="px-2 py-0.5 text-xs rounded-full bg-primary/20 text-primary">执行中</span>
        case 'completed':
          return <span className="px-2 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400">已完成</span>
        case 'failed':
          return <span className="px-2 py-0.5 text-xs rounded-full bg-destructive/20 text-destructive">失败</span>
        default:
          return <span className="px-2 py-0.5 text-xs rounded-full bg-secondary text-muted-foreground">等待中</span>
      }
    }

    return (
      <div 
        ref={ref}
        className={cn(
          "rounded-lg border transition-all duration-200",
          isActive ? "border-primary/50 bg-primary/5 shadow-lg shadow-primary/10" : "border-border bg-card/50",
          group.status === 'completed' && "border-green-500/30",
          group.status === 'failed' && "border-destructive/30",
          onClick && "cursor-pointer hover:bg-card/80"
        )}
        onClick={onClick}
      >
        {/* 卡片头部 */}
        <div className="flex items-center gap-3 p-4 border-b border-border/50">
          <div className="flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center bg-secondary">
            {getStatusIcon()}
          </div>
          
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-foreground">
                {group.taskId === 'planning' ? '📋' : `#${group.taskId}`} {group.taskName}
              </span>
              {getStatusBadge()}
            </div>
            {group.startTime && (
              <span className="text-xs text-muted-foreground">
                {formatTime(group.startTime)}
                {group.endTime && ` - ${formatTime(group.endTime)}`}
              </span>
            )}
          </div>
        </div>
        
        {/* 事件列表 */}
        {group.events.length > 0 && (
          <div className="p-4 space-y-3">
            {group.events.map((event) => (
              <EventItem key={event.id} event={event} />
            ))}
          </div>
        )}
        
        {/* 空状态 */}
        {group.events.length === 0 && group.status === 'in_progress' && (
          <div className="p-4 text-center text-muted-foreground text-sm">
            <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
            准备执行...
          </div>
        )}
      </div>
    )
  }
)

TaskGroupCard.displayName = 'TaskGroupCard'

// 单个事件展示
function EventItem({ event }: { event: ProcessedEvent }) {
  switch (event.type) {
    case 'data_explored':
      return <DataExploredEvent event={event} />
    case 'thinking':
      return <ThinkingEvent event={event} />
    case 'code':
      return <CodeEvent event={event} />
    case 'tool_result':
      return <ToolResultEvent event={event} />
    case 'image':
      return <ImageEvent event={event} />
    case 'error':
      return <ErrorEvent event={event} />
    default:
      return null
  }
}

// 数据探索事件
function DataExploredEvent({ event }: { event: ProcessedEvent }) {
  const { statistics, schema } = event.data
  
  return (
    <div className="rounded-lg bg-cyan-500/10 border border-cyan-500/20 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Database className="w-4 h-4 text-cyan-400" />
        <span className="text-sm font-medium text-cyan-400">数据集概览</span>
      </div>
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <span className="text-muted-foreground">行数</span>
          <p className="text-foreground font-medium">{statistics?.total_rows?.toLocaleString() || '-'}</p>
        </div>
        <div>
          <span className="text-muted-foreground">列数</span>
          <p className="text-foreground font-medium">{statistics?.total_columns || '-'}</p>
        </div>
        <div>
          <span className="text-muted-foreground">缺失值</span>
          <p className="text-foreground font-medium">{statistics?.missing_percentage?.toFixed(1) || 0}%</p>
        </div>
      </div>
      {schema && schema.length > 0 && (
        <div className="mt-3 pt-3 border-t border-cyan-500/20">
          <p className="text-xs text-muted-foreground mb-2">字段列表</p>
          <div className="flex flex-wrap gap-1">
            {schema.slice(0, 8).map((col, i) => (
              <span key={i} className="px-2 py-0.5 text-xs rounded bg-secondary text-muted-foreground">
                {col.name}
              </span>
            ))}
            {schema.length > 8 && (
              <span className="px-2 py-0.5 text-xs rounded bg-secondary text-muted-foreground">
                +{schema.length - 8} 更多
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// 思考过程事件
function ThinkingEvent({ event }: { event: ProcessedEvent }) {
  const { thinking, isStreaming } = event.data
  
  if (!thinking) return null
  
  return (
    <div className="rounded-lg bg-violet-500/10 border border-violet-500/20 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Brain className="w-4 h-4 text-violet-400" />
        <span className="text-sm font-medium text-violet-400">AI 思考过程</span>
        {isStreaming && (
          <span className="inline-block w-2 h-4 bg-violet-400 animate-pulse" />
        )}
      </div>
      {/* 固定高度，可滚动 */}
      <div className="max-h-48 overflow-y-auto text-sm text-violet-200/80 whitespace-pre-wrap break-words scrollbar-thin scrollbar-thumb-violet-500/30 scrollbar-track-transparent">
        {thinking}
      </div>
    </div>
  )
}

// 代码事件
function CodeEvent({ event }: { event: ProcessedEvent }) {
  const { code, description } = event.data
  
  if (!code) return null
  
  return (
    <div className="rounded-lg bg-yellow-500/10 border border-yellow-500/20 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Code className="w-4 h-4 text-yellow-400" />
        <span className="text-sm font-medium text-yellow-400">
          {description || '执行代码'}
        </span>
      </div>
      <CodeBlock code={code} language="python" />
    </div>
  )
}

// 工具名称中文映射
const TOOL_NAME_MAP: Record<string, string> = {
  'run_code': '执行代码',
  'read_dataset': '读取数据',
  'todo_write': '更新任务',
}

// 获取工具中文名称
function getToolDisplayName(tool?: string): string {
  if (!tool) return '工具调用'
  return TOOL_NAME_MAP[tool] || tool
}

// 工具结果事件
function ToolResultEvent({ event }: { event: ProcessedEvent }) {
  const { tool, stdout, status } = event.data
  const displayName = getToolDisplayName(tool)
  
  return (
    <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 p-3">
      <div className="flex items-center gap-2 mb-2">
        <Terminal className="w-4 h-4 text-emerald-400" />
        <span className="text-sm font-medium text-emerald-400">{displayName}</span>
        {status === 'success' && <CheckCircle className="w-3 h-3 text-green-400" />}
        {status === 'error' && <XCircle className="w-3 h-3 text-destructive" />}
      </div>
      {stdout && (
        <pre className="max-h-40 overflow-y-auto text-xs text-emerald-200/80 bg-secondary/50 p-2 rounded scrollbar-thin">
          {stdout}
        </pre>
      )}
    </div>
  )
}

// 图片事件
function ImageEvent({ event }: { event: ProcessedEvent }) {
  const { image_base64 } = event.data
  
  if (!image_base64) return null
  
  return (
    <div className="rounded-lg bg-pink-500/10 border border-pink-500/20 p-3">
      <div className="flex items-center gap-2 mb-2">
        <ImageIcon className="w-4 h-4 text-pink-400" />
        <span className="text-sm font-medium text-pink-400">生成图表</span>
      </div>
      <img
        src={`data:image/png;base64,${image_base64}`}
        alt="Generated chart"
        className="max-w-full rounded-lg border border-border"
      />
    </div>
  )
}

// 错误事件
function ErrorEvent({ event }: { event: ProcessedEvent }) {
  const { error } = event.data
  
  return (
    <div className="rounded-lg bg-destructive/10 border border-destructive/30 p-3">
      <div className="flex items-center gap-2 mb-2">
        <AlertTriangle className="w-4 h-4 text-destructive" />
        <span className="text-sm font-medium text-destructive">执行错误</span>
      </div>
      <p className="text-sm text-destructive/80">{error}</p>
    </div>
  )
}

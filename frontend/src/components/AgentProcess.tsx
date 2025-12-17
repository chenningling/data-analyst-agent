import { useEffect, useRef, useState } from 'react'
import { 
  Play, 
  CheckCircle, 
  XCircle, 
  Code2, 
  Database, 
  FileText, 
  Image as ImageIcon,
  Zap,
  Terminal,
  Brain,
  ChevronDown,
  ChevronRight
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CodeBlock } from './CodeBlock'
import type { AgentEvent } from '@/hooks/useWebSocket'

interface AgentProcessProps {
  events: AgentEvent[]
  isConnected: boolean
}

const eventIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  connected: CheckCircle,
  agent_started: Play,
  agent_completed: CheckCircle,
  agent_error: XCircle,
  phase_change: Zap,
  task_started: Play,
  task_completed: CheckCircle,
  task_failed: XCircle,
  tool_call: Terminal,
  tool_result: Database,
  code_generated: Code2,
  image_generated: ImageIcon,
  report_generated: FileText,
  log: Terminal,
  data_explored: Database,
  tasks_planned: FileText,
  tasks_updated: FileText,
  llm_thinking: Brain,
  // 新增流式事件图标
  llm_start: Brain,
  llm_streaming: Brain,
  llm_tool_calling: Terminal,
  llm_complete: CheckCircle,
}

const eventColors: Record<string, string> = {
  connected: 'text-green-400',
  agent_started: 'text-primary',
  agent_completed: 'text-green-400',
  agent_error: 'text-destructive',
  phase_change: 'text-purple-400',
  task_started: 'text-blue-400',
  task_completed: 'text-green-400',
  task_failed: 'text-destructive',
  tool_call: 'text-yellow-400',
  tool_result: 'text-cyan-400',
  code_generated: 'text-orange-400',
  image_generated: 'text-pink-400',
  report_generated: 'text-green-400',
  log: 'text-muted-foreground',
  data_explored: 'text-cyan-400',
  tasks_planned: 'text-purple-400',
  tasks_updated: 'text-emerald-400',
  llm_thinking: 'text-violet-400',
  // 新增流式事件颜色
  llm_start: 'text-blue-400',
  llm_streaming: 'text-violet-400',
  llm_tool_calling: 'text-yellow-400',
  llm_complete: 'text-green-400',
}

const phaseLabels: Record<string, string> = {
  data_exploration: '📊 数据探索',
  planning: '📋 任务规划',
  executing: '⚡ 执行分析',
  reporting: '📝 生成报告',
  error_recovery: '🔧 错误修复',
  autonomous_running: '🤖 自主分析中',
}

// 判断事件是否有详细内容可展开
function hasExpandableContent(event: AgentEvent): boolean {
  const { type, payload } = event
  
  switch (type) {
    case 'code_generated':
      return !!(payload.code)
    case 'image_generated':
      return !!(payload.image_base64)
    case 'tool_call':
      return !!(payload.arguments)
    case 'tool_result':
      return !!(payload.stdout_preview)
    case 'llm_thinking':
      return !!(payload.thinking)
    case 'data_explored':
      return true
    case 'tasks_planned':
      return !!(payload.tasks)
    case 'tasks_updated':
      return !!(payload.tasks)
    case 'llm_streaming':
      return !!(payload.full_content)
    default:
      return false
  }
}

export function AgentProcess({ events, isConnected }: AgentProcessProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // 记录每个事件的展开状态，默认最新的展开，历史的收起
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set())
  // 流式内容状态
  const [streamingContent, setStreamingContent] = useState<string>('')
  const [streamingType, setStreamingType] = useState<'content' | 'reasoning'>('content')
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentIteration, setCurrentIteration] = useState(0)
  
  // 处理流式事件
  useEffect(() => {
    if (events.length === 0) return
    
    const lastEvent = events[events.length - 1]
    
    if (lastEvent.type === 'llm_start') {
      // 开始新的 LLM 调用，重置流式状态
      setStreamingContent('')
      setIsStreaming(true)
      setCurrentIteration(lastEvent.payload.iteration as number)
    } else if (lastEvent.type === 'llm_streaming') {
      // 更新流式内容
      setStreamingContent(lastEvent.payload.full_content as string || '')
      setStreamingType(lastEvent.payload.type as 'content' | 'reasoning' || 'content')
      setIsStreaming(true)
    } else if (lastEvent.type === 'llm_complete' || lastEvent.type === 'tool_call' || lastEvent.type === 'tool_result') {
      // LLM 调用完成，停止流式显示
      setIsStreaming(false)
    }
  }, [events])
  
  // 当事件更新时，自动展开最新的事件
  useEffect(() => {
    if (events.length > 0) {
      const lastIndex = events.length - 1
      // 只展开最新的可展开事件（排除流式事件）
      const lastEvent = events[lastIndex]
      if (hasExpandableContent(lastEvent) && lastEvent.type !== 'llm_streaming') {
        setExpandedEvents(new Set([lastIndex]))
      } else if (lastEvent.type !== 'llm_streaming') {
        setExpandedEvents(new Set())
      }
    }
  }, [events.length])

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events])

  const toggleExpand = (index: number) => {
    setExpandedEvents(prev => {
      const next = new Set(prev)
      if (next.has(index)) {
        next.delete(index)
      } else {
        next.add(index)
      }
      return next
    })
  }

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

  // 过滤掉重复的流式事件，只保留最后一个
  const filteredEvents = events.filter((event, index) => {
    // 如果是流式事件，只保留最后一个相同迭代的流式事件
    if (event.type === 'llm_streaming') {
      const nextEvent = events[index + 1]
      // 如果下一个也是同迭代的流式事件，跳过当前的
      if (nextEvent && nextEvent.type === 'llm_streaming' && 
          nextEvent.payload.iteration === event.payload.iteration) {
        return false
      }
    }
    return true
  })

  return (
    <div 
      ref={containerRef}
      className="space-y-2 max-h-[600px] overflow-y-auto pr-2"
    >
      {filteredEvents.map((event, index) => (
        <ProcessEvent 
          key={`${event.type}-${event.timestamp}-${index}`} 
          event={event} 
          index={index}
          isExpanded={expandedEvents.has(index)}
          onToggle={() => toggleExpand(index)}
          isLatest={index === filteredEvents.length - 1}
        />
      ))}
      
      {/* 流式输出实时显示区域 */}
      {isStreaming && streamingContent && (
        <div className="rounded-lg border border-violet-500/30 bg-violet-500/10 animate-pulse-slow">
          <div className="flex items-start gap-3 p-3">
            <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
              <div className="w-2 h-2 rounded-full bg-violet-400 animate-ping" />
            </div>
            <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-violet-500/20">
              <Brain className="w-4 h-4 text-violet-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-medium text-violet-400">
                  🧠 {streamingType === 'reasoning' ? 'Agent 思考中...' : 'Agent 输出中...'}
                </span>
                <span className="text-xs text-muted-foreground">迭代 #{currentIteration}</span>
              </div>
              <div className="text-sm text-violet-200 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {streamingContent}
                <span className="inline-block w-2 h-4 bg-violet-400 animate-pulse ml-1" />
              </div>
            </div>
          </div>
        </div>
      )}
      
      {/* 处理中指示器 */}
      {isConnected && !isStreaming && !events.some(e => e.type === 'agent_completed' || e.type === 'agent_error') && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-primary/10 border border-primary/30 animate-pulse">
          <div className="w-2 h-2 rounded-full bg-primary animate-ping" />
          <span className="text-sm text-primary">处理中...</span>
        </div>
      )}
    </div>
  )
}

interface ProcessEventProps {
  event: AgentEvent
  index?: number
  isExpanded: boolean
  onToggle: () => void
  isLatest: boolean
}

function ProcessEvent({ event, isExpanded, onToggle, isLatest }: ProcessEventProps) {
  const Icon = eventIcons[event.type] || Terminal
  const color = eventColors[event.type] || 'text-muted-foreground'
  const payload = event.payload
  const canExpand = hasExpandableContent(event)

  const renderSummary = (): React.ReactNode => {
    switch (event.type) {
      case 'connected':
        return '🔗 WebSocket 连接成功'
      
      case 'agent_started':
        return '🚀 Agent 开始执行'
      
      case 'phase_change':
        return phaseLabels[payload.phase as string] || `阶段: ${String(payload.phase)}`
      
      case 'llm_thinking':
        return (
          <span className="text-violet-300">
            🧠 {String(payload.action || '')}
            {payload.duration ? <span className="text-xs ml-2 text-muted-foreground">({Number(payload.duration).toFixed(1)}s)</span> : null}
          </span>
        )
      
      case 'code_generated':
        return `生成代码: ${String(payload.description || '任务 #' + payload.task_id)}`
      
      case 'image_generated':
        return `生成图表: 任务 #${String(payload.task_id)}`
      
      case 'tool_call':
        return `调用工具: ${String(payload.tool)}`
      
      case 'tool_result':
        return (
          <span className={payload.status === 'success' ? 'text-green-400' : 'text-destructive'}>
            {String(payload.tool)}: {String(payload.status)}
            {payload.has_image ? <span className="text-xs text-pink-400 ml-2">📷 包含图表</span> : null}
          </span>
        )
      
      case 'tasks_planned':
        return `规划了 ${(payload.tasks as unknown[])?.length || 0} 个任务`
      
      case 'tasks_updated':
        const updatedTasksList = payload.tasks as Array<{status: string}>
        const completedCount = updatedTasksList?.filter(t => t.status === 'completed').length || 0
        const totalCount = updatedTasksList?.length || 0
        return `任务进度: ${completedCount}/${totalCount} 已完成`
      
      case 'data_explored':
        return `数据集: ${(payload.statistics as Record<string, number>)?.total_rows || 0} 行 × ${(payload.statistics as Record<string, number>)?.total_columns || 0} 列`
      
      case 'task_started':
        return `开始执行: ${String(payload.task_name)}`
      
      case 'task_completed':
        return `✅ 完成: ${String(payload.task_name)}`
      
      case 'task_failed':
        return `❌ 失败: ${String(payload.task_name)}`
      
      case 'report_generated':
        return '✨ 报告生成完成'
      
      case 'log':
        return String(payload.message || '')
      
      case 'agent_completed':
        return '🎉 分析完成！'
      
      case 'agent_error':
        return `❌ 错误: ${String(payload.error)}`
      
      // 新增流式事件
      case 'llm_start':
        return `🚀 开始第 ${String(payload.iteration)} 次思考`
      
      case 'llm_streaming': {
        const streamType = payload.type === 'reasoning' ? '思考' : '输出'
        const fullContent = String(payload.full_content || '')
        const contentPreview = fullContent.slice(0, 50)
        return `💭 ${streamType}中: ${contentPreview}${fullContent.length > 50 ? '...' : ''}`
      }
      
      case 'llm_tool_calling':
        return `🔧 准备调用: ${String(payload.tool)}`
      
      case 'llm_complete':
        return (
          <span className="text-green-400">
            ✅ 第 {String(payload.iteration)} 次思考完成
            <span className="text-xs ml-2 text-muted-foreground">({Number(payload.duration || 0).toFixed(1)}s)</span>
          </span>
        )
      
      default:
        return event.type.replace(/_/g, ' ')
    }
  }

  const renderExpandedContent = (): React.ReactNode => {
    if (!canExpand || !isExpanded) return null

    switch (event.type) {
      case 'llm_thinking':
        return (
          <div className="mt-2 p-3 bg-violet-500/10 rounded-lg border border-violet-500/20">
            {/* 区分真实思考 vs 系统生成 */}
            {payload.is_real ? (
              <div className="text-xs text-violet-400 mb-2 flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full bg-violet-400 animate-pulse"></span>
                Agent 思考中...
              </div>
            ) : null}
            <p className="text-sm text-violet-200 whitespace-pre-wrap">
              {String(payload.thinking || '')}
            </p>
            {payload.input_summary ? (
              <p className="text-xs text-muted-foreground mt-2">
                输入: {String(payload.input_summary)}
              </p>
            ) : null}
            {payload.output_summary ? (
              <p className="text-xs text-muted-foreground mt-1">
                输出: {String(payload.output_summary)}
              </p>
            ) : null}
            {payload.iteration ? (
              <p className="text-xs text-muted-foreground mt-1">
                迭代: #{String(payload.iteration)}
              </p>
            ) : null}
          </div>
        )
      
      case 'code_generated':
        return (
          <div className="mt-2">
            <CodeBlock 
              code={payload.code as string} 
              language="python"
              title={`Task ${payload.task_id}`}
            />
          </div>
        )
      
      case 'image_generated':
        return (
          <div className="mt-2">
            <img
              src={`data:image/png;base64,${payload.image_base64}`}
              alt="Generated chart"
              className="max-w-full rounded-lg border border-border"
            />
          </div>
        )
      
      case 'tool_call':
        return payload.arguments ? (
          <pre className="mt-2 text-xs text-muted-foreground bg-secondary/50 p-3 rounded-lg overflow-x-auto">
            {JSON.stringify(payload.arguments, null, 2)}
          </pre>
        ) : null
      
      case 'tool_result':
        return payload.stdout_preview ? (
          <pre className="mt-2 text-xs text-muted-foreground bg-secondary/50 p-3 rounded-lg overflow-x-auto max-h-40">
            {String(payload.stdout_preview)}
          </pre>
        ) : null
      
      case 'data_explored':
        return (
          <div className="mt-2 text-xs text-muted-foreground space-y-1">
            <p>缺失值: {(payload.statistics as Record<string, number>)?.missing_percentage || 0}%</p>
          </div>
        )
      
      case 'tasks_planned':
        return (
          <div className="mt-2 space-y-1">
            {payload.analysis_goal ? (
              <p className="text-sm text-muted-foreground mb-2">
                目标: {String(payload.analysis_goal)}
              </p>
            ) : null}
            <div className="text-xs space-y-1">
              {(payload.tasks as Array<{id: number, name: string, type: string}>)?.map((task, i) => (
                <div key={i} className="flex items-center gap-2 text-muted-foreground">
                  <span className="w-5 h-5 rounded bg-secondary flex items-center justify-center text-xs">
                    {task.id}
                  </span>
                  <span>{task.name}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-secondary/50">{task.type}</span>
                </div>
              ))}
            </div>
          </div>
        )
      
      case 'tasks_updated':
        return (
          <div className="mt-2 space-y-1">
            <div className="text-xs space-y-1">
              {(payload.tasks as Array<{id: number, name: string, status: string}>)?.map((task, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className={cn(
                    "w-5 h-5 rounded flex items-center justify-center text-xs",
                    task.status === 'completed' 
                      ? "bg-green-500/20 text-green-400" 
                      : "bg-secondary text-muted-foreground"
                  )}>
                    {task.status === 'completed' ? '✓' : task.id}
                  </span>
                  <span className={task.status === 'completed' ? 'text-green-400' : 'text-muted-foreground'}>
                    {task.name}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )
      
      case 'llm_streaming':
        return (
          <div className="mt-2 p-3 bg-violet-500/10 rounded-lg border border-violet-500/20">
            <p className="text-sm text-violet-200 whitespace-pre-wrap">
              {String(payload.full_content || '')}
            </p>
          </div>
        )
      
      default:
        return null
    }
  }

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  return (
    <div 
      className={cn(
        "rounded-lg border transition-all duration-200",
        isLatest ? "bg-card border-primary/30" : "bg-card/50 border-border",
        canExpand && "cursor-pointer hover:bg-card/80"
      )}
    >
      {/* 头部 - 始终显示 */}
      <div 
        className="flex items-start gap-3 p-3"
        onClick={canExpand ? onToggle : undefined}
      >
        {/* 展开/收起图标 */}
        <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
          {canExpand ? (
            isExpanded ? (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            )
          ) : (
            <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
          )}
        </div>
        
        {/* 图标 */}
        <div className={cn(
          "flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center",
          "bg-secondary"
        )}>
          <Icon className={cn("w-4 h-4", color)} />
        </div>
        
        {/* 内容 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("text-sm font-medium", color)}>
              {renderSummary()}
            </span>
          </div>
          <span className="text-xs text-muted-foreground/50">
            {formatTime(event.timestamp)}
          </span>
        </div>
      </div>
      
      {/* 展开内容 */}
      {isExpanded && canExpand && (
        <div className="px-3 pb-3 pl-12">
          {renderExpandedContent()}
        </div>
      )}
    </div>
  )
}

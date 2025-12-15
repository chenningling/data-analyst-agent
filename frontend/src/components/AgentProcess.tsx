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
  llm_thinking: Brain,
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
  llm_thinking: 'text-violet-400',
}

const phaseLabels: Record<string, string> = {
  data_exploration: '📊 数据探索',
  planning: '📋 任务规划',
  executing: '⚡ 执行分析',
  reporting: '📝 生成报告',
  error_recovery: '🔧 错误修复',
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
    default:
      return false
  }
}

export function AgentProcess({ events, isConnected }: AgentProcessProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // 记录每个事件的展开状态，默认最新的展开，历史的收起
  const [expandedEvents, setExpandedEvents] = useState<Set<number>>(new Set())
  
  // 当事件更新时，自动展开最新的事件
  useEffect(() => {
    if (events.length > 0) {
      const lastIndex = events.length - 1
      // 只展开最新的可展开事件
      if (hasExpandableContent(events[lastIndex])) {
        setExpandedEvents(new Set([lastIndex]))
      } else {
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

  return (
    <div 
      ref={containerRef}
      className="space-y-2 max-h-[600px] overflow-y-auto pr-2"
    >
      {events.map((event, index) => (
        <ProcessEvent 
          key={index} 
          event={event} 
          index={index}
          isExpanded={expandedEvents.has(index)}
          onToggle={() => toggleExpand(index)}
          isLatest={index === events.length - 1}
        />
      ))}
      
      {/* 处理中指示器 */}
      {isConnected && !events.some(e => e.type === 'agent_completed' || e.type === 'agent_error') && (
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
  index: number
  isExpanded: boolean
  onToggle: () => void
  isLatest: boolean
}

function ProcessEvent({ event, index, isExpanded, onToggle, isLatest }: ProcessEventProps) {
  const Icon = eventIcons[event.type] || Terminal
  const color = eventColors[event.type] || 'text-muted-foreground'
  const payload = event.payload
  const canExpand = hasExpandableContent(event)

  const renderSummary = () => {
    switch (event.type) {
      case 'connected':
        return '🔗 WebSocket 连接成功'
      
      case 'agent_started':
        return '🚀 Agent 开始执行'
      
      case 'phase_change':
        return phaseLabels[payload.phase as string] || `阶段: ${payload.phase}`
      
      case 'llm_thinking':
        return (
          <span className="text-violet-300">
            🧠 {payload.action as string}
            {payload.duration && <span className="text-xs ml-2 text-muted-foreground">({(payload.duration as number).toFixed(1)}s)</span>}
          </span>
        )
      
      case 'code_generated':
        return `生成代码: ${payload.description || '任务 #' + payload.task_id}`
      
      case 'image_generated':
        return `生成图表: 任务 #${payload.task_id}`
      
      case 'tool_call':
        return `调用工具: ${payload.tool}`
      
      case 'tool_result':
        return (
          <span className={payload.status === 'success' ? 'text-green-400' : 'text-destructive'}>
            {payload.tool}: {payload.status}
            {payload.has_image && <span className="text-xs text-pink-400 ml-2">📷 包含图表</span>}
          </span>
        )
      
      case 'tasks_planned':
        return `规划了 ${(payload.tasks as unknown[])?.length || 0} 个任务`
      
      case 'data_explored':
        return `数据集: ${(payload.statistics as Record<string, number>)?.total_rows || 0} 行 × ${(payload.statistics as Record<string, number>)?.total_columns || 0} 列`
      
      case 'task_started':
        return `开始执行: ${payload.task_name}`
      
      case 'task_completed':
        return `✅ 完成: ${payload.task_name}`
      
      case 'task_failed':
        return `❌ 失败: ${payload.task_name}`
      
      case 'report_generated':
        return '✨ 报告生成完成'
      
      case 'log':
        return payload.message as string
      
      case 'agent_completed':
        return '🎉 分析完成！'
      
      case 'agent_error':
        return `❌ 错误: ${payload.error}`
      
      default:
        return event.type.replace(/_/g, ' ')
    }
  }

  const renderExpandedContent = () => {
    if (!canExpand || !isExpanded) return null

    switch (event.type) {
      case 'llm_thinking':
        return (
          <div className="mt-2 p-3 bg-violet-500/10 rounded-lg border border-violet-500/20">
            <p className="text-sm text-violet-200 whitespace-pre-wrap">
              {payload.thinking as string}
            </p>
            {payload.input_summary && (
              <p className="text-xs text-muted-foreground mt-2">
                输入: {payload.input_summary as string}
              </p>
            )}
            {payload.output_summary && (
              <p className="text-xs text-muted-foreground mt-1">
                输出: {payload.output_summary as string}
              </p>
            )}
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
        return payload.arguments && (
          <pre className="mt-2 text-xs text-muted-foreground bg-secondary/50 p-3 rounded-lg overflow-x-auto">
            {JSON.stringify(payload.arguments, null, 2)}
          </pre>
        )
      
      case 'tool_result':
        return payload.stdout_preview && (
          <pre className="mt-2 text-xs text-muted-foreground bg-secondary/50 p-3 rounded-lg overflow-x-auto max-h-40">
            {payload.stdout_preview}
          </pre>
        )
      
      case 'data_explored':
        return (
          <div className="mt-2 text-xs text-muted-foreground space-y-1">
            <p>缺失值: {(payload.statistics as Record<string, number>)?.missing_percentage || 0}%</p>
          </div>
        )
      
      case 'tasks_planned':
        return (
          <div className="mt-2 space-y-1">
            {payload.analysis_goal && (
              <p className="text-sm text-muted-foreground mb-2">
                目标: {payload.analysis_goal as string}
              </p>
            )}
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

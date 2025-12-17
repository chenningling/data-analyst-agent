import { useEffect, useRef, useState, useMemo } from 'react'
import { 
  Play, 
  CheckCircle, 
  XCircle, 
  Database, 
  FileText, 
  Image as ImageIcon,
  Zap,
  Terminal,
  Brain,
  ChevronDown,
  ChevronRight,
  Loader2
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CodeBlock } from './CodeBlock'
import type { AgentEvent } from '@/hooks/useWebSocket'

interface AgentProcessProps {
  events: AgentEvent[]
  isConnected: boolean
}

// 迭代步骤数据结构
interface IterationStep {
  iteration: number
  status: 'thinking' | 'tool_calling' | 'completed' | 'error'
  thinkingContent: string  // 思考过程（实时更新）
  outputContent: string    // 输出内容（实时更新）
  toolCalls: Array<{
    tool: string
    arguments?: Record<string, unknown>
    status?: 'calling' | 'success' | 'error'
    result?: {
      stdout?: string
      hasImage?: boolean
      code?: string
      description?: string
    }
  }>
  duration?: number
  timestamp: string
}

// 将事件列表转换为迭代步骤
function groupEventsByIteration(events: AgentEvent[]): {
  iterations: Map<number, IterationStep>
  otherEvents: AgentEvent[]
  currentStreaming: { iteration: number; content: string; type: 'reasoning' | 'content' } | null
} {
  const iterations = new Map<number, IterationStep>()
  const otherEvents: AgentEvent[] = []
  let currentStreaming: { iteration: number; content: string; type: 'reasoning' | 'content' } | null = null
  
  for (const event of events) {
    const iteration = event.payload.iteration as number | undefined
    
    switch (event.type) {
      case 'llm_start':
        if (iteration !== undefined) {
          iterations.set(iteration, {
            iteration,
            status: 'thinking',
            thinkingContent: '',
            outputContent: '',
            toolCalls: [],
            timestamp: event.timestamp
          })
        }
        break
        
      case 'llm_streaming':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step) {
            const streamType = event.payload.type as 'reasoning' | 'content'
            const content = String(event.payload.full_content || '')
            if (streamType === 'reasoning') {
              step.thinkingContent = content
            } else {
              step.outputContent = content
            }
            // 记录当前正在流式输出的内容
            currentStreaming = { iteration, content, type: streamType }
          }
        }
        break
        
      case 'llm_tool_calling':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step) {
            step.status = 'tool_calling'
            step.toolCalls.push({
              tool: String(event.payload.tool),
              status: 'calling'
            })
          }
        }
        break
        
      case 'llm_complete':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step) {
            step.status = 'completed'
            step.duration = event.payload.duration as number
          }
          currentStreaming = null
        }
        break
        
      case 'tool_call':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step) {
            // 更新或添加工具调用信息
            const existingCall = step.toolCalls.find(tc => tc.tool === event.payload.tool)
            if (existingCall) {
              existingCall.arguments = event.payload.arguments as Record<string, unknown>
            } else {
              step.toolCalls.push({
                tool: String(event.payload.tool),
                arguments: event.payload.arguments as Record<string, unknown>,
                status: 'calling'
              })
            }
          }
        } else {
          otherEvents.push(event)
        }
        break
        
      case 'tool_result':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step && step.toolCalls.length > 0) {
            const lastCall = step.toolCalls[step.toolCalls.length - 1]
            lastCall.status = event.payload.status === 'success' ? 'success' : 'error'
            lastCall.result = {
              stdout: event.payload.stdout_preview as string,
              hasImage: event.payload.has_image as boolean
            }
          }
        } else {
          otherEvents.push(event)
        }
        break
        
    case 'code_generated':
        if (iteration !== undefined) {
          const step = iterations.get(iteration)
          if (step && step.toolCalls.length > 0) {
            const lastCall = step.toolCalls[step.toolCalls.length - 1]
            lastCall.result = {
              ...lastCall.result,
              code: event.payload.code as string,
              description: event.payload.description as string
            }
          }
        } else {
          otherEvents.push(event)
        }
        break
        
    case 'image_generated':
        // 图片事件单独处理，添加到 otherEvents
        otherEvents.push(event)
        break
        
    default:
        // 非迭代相关的事件
        otherEvents.push(event)
  }
  }
  
  return { iterations, otherEvents, currentStreaming }
}

export function AgentProcess({ events, isConnected }: AgentProcessProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [expandedIterations, setExpandedIterations] = useState<Set<number>>(new Set())
  const [expandedOtherEvents, setExpandedOtherEvents] = useState<Set<number>>(new Set())
  
  // 解析事件为迭代步骤
  const { iterations, otherEvents, currentStreaming } = useMemo(
    () => groupEventsByIteration(events),
    [events]
  )
  
  // 自动展开最新的迭代
  useEffect(() => {
    if (iterations.size > 0) {
      const maxIteration = Math.max(...iterations.keys())
      setExpandedIterations(new Set([maxIteration]))
    }
  }, [iterations.size])

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events.length, currentStreaming?.content])

  const toggleIteration = (iteration: number) => {
    setExpandedIterations(prev => {
      const next = new Set(prev)
      if (next.has(iteration)) {
        next.delete(iteration)
      } else {
        next.add(iteration)
      }
      return next
    })
  }

  const toggleOtherEvent = (index: number) => {
    setExpandedOtherEvents(prev => {
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

  // 将迭代步骤转换为数组并按迭代号排序
  const sortedIterations = Array.from(iterations.values()).sort((a, b) => a.iteration - b.iteration)
  
  // 过滤出重要的非迭代事件（排除流式相关事件）
  const importantOtherEvents = otherEvents.filter(e => 
    !['llm_start', 'llm_streaming', 'llm_tool_calling', 'llm_complete'].includes(e.type)
  )

  return (
    <div 
      ref={containerRef}
      className="space-y-3 max-h-[600px] overflow-y-auto pr-2"
    >
      {/* 非迭代事件（如 agent_started, phase_change 等） */}
      {importantOtherEvents.filter(e => 
        ['connected', 'agent_started', 'phase_change', 'tasks_planned', 'data_explored'].includes(e.type)
      ).map((event, index) => (
        <SimpleEventCard 
          key={`other-${index}`} 
          event={event}
          isExpanded={expandedOtherEvents.has(index)}
          onToggle={() => toggleOtherEvent(index)}
        />
      ))}
      
      {/* 迭代步骤卡片 */}
      {sortedIterations.map((step) => (
        <IterationCard
          key={step.iteration}
          step={step}
          isExpanded={expandedIterations.has(step.iteration)}
          onToggle={() => toggleIteration(step.iteration)}
          isStreaming={currentStreaming?.iteration === step.iteration}
        />
      ))}
      
      {/* 任务更新、图片生成等事件 */}
      {importantOtherEvents.filter(e => 
        ['tasks_updated', 'image_generated', 'report_generated', 'agent_completed', 'agent_error'].includes(e.type)
      ).map((event, index) => (
        <SimpleEventCard 
          key={`result-${index}`} 
          event={event} 
          isExpanded={expandedOtherEvents.has(1000 + index)}
          onToggle={() => toggleOtherEvent(1000 + index)}
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

// 迭代步骤卡片组件
interface IterationCardProps {
  step: IterationStep
  isExpanded: boolean
  onToggle: () => void
  isStreaming: boolean
}

function IterationCard({ step, isExpanded, onToggle, isStreaming }: IterationCardProps) {
  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  const getStatusIcon = () => {
    switch (step.status) {
      case 'thinking':
        return <Brain className="w-4 h-4 text-violet-400 animate-pulse" />
      case 'tool_calling':
        return <Terminal className="w-4 h-4 text-yellow-400" />
      case 'completed':
        return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'error':
        return <XCircle className="w-4 h-4 text-destructive" />
    }
  }

  const getStatusText = () => {
    switch (step.status) {
      case 'thinking':
        return '思考中...'
      case 'tool_calling':
        return '调用工具中...'
      case 'completed':
        return `完成 (${step.duration?.toFixed(1)}s)`
      case 'error':
        return '出错'
    }
  }

  const hasContent = step.thinkingContent || step.outputContent || step.toolCalls.length > 0

        return (
    <div className={cn(
      "rounded-lg border transition-all duration-200",
      isStreaming ? "border-violet-500/50 bg-violet-500/5" : "border-border bg-card/50",
      step.status === 'completed' && "border-green-500/30"
    )}>
      {/* 卡片头部 */}
      <div 
        className="flex items-center gap-3 p-3 cursor-pointer hover:bg-card/80"
        onClick={onToggle}
      >
        <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
          {hasContent ? (
            isExpanded ? (
              <ChevronDown className="w-4 h-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            )
          ) : (
            <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground/30" />
          )}
        </div>
        
        <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-secondary">
          {getStatusIcon()}
        </div>
        
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn(
              "text-sm font-medium",
              step.status === 'thinking' && "text-violet-400",
              step.status === 'tool_calling' && "text-yellow-400",
              step.status === 'completed' && "text-green-400",
              step.status === 'error' && "text-destructive"
            )}>
              迭代 #{step.iteration} - {getStatusText()}
            </span>
            {step.toolCalls.length > 0 && (
              <span className="text-xs text-muted-foreground">
                ({step.toolCalls.map(tc => tc.tool).join(', ')})
              </span>
            )}
          </div>
          <span className="text-xs text-muted-foreground/50">
            {formatTime(step.timestamp)}
          </span>
        </div>
        
        {isStreaming && (
          <div className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full bg-violet-400 animate-ping" />
            <span className="text-xs text-violet-400">实时</span>
          </div>
        )}
      </div>
      
      {/* 卡片内容（展开时显示） */}
      {isExpanded && hasContent && (
        <div className="px-4 pb-4 space-y-3">
          {/* 思考过程 */}
          {step.thinkingContent && (
            <div className="rounded-lg bg-violet-500/10 border border-violet-500/20 p-3">
              <div className="flex items-center gap-2 mb-2">
                <Brain className="w-4 h-4 text-violet-400" />
                <span className="text-xs font-medium text-violet-400">思考过程</span>
                {isStreaming && step.status === 'thinking' && (
                  <span className="inline-block w-2 h-4 bg-violet-400 animate-pulse" />
                )}
              </div>
              <div className="text-sm text-violet-200 whitespace-pre-wrap break-words max-h-96 overflow-y-auto">
                {step.thinkingContent}
              </div>
            </div>
          )}
          
          {/* 输出内容 */}
          {step.outputContent && (
            <div className="rounded-lg bg-blue-500/10 border border-blue-500/20 p-3">
              <div className="flex items-center gap-2 mb-2">
                <FileText className="w-4 h-4 text-blue-400" />
                <span className="text-xs font-medium text-blue-400">输出内容</span>
              </div>
              <div className="text-sm text-blue-200 whitespace-pre-wrap break-words max-h-40 overflow-y-auto">
                {step.outputContent}
              </div>
            </div>
          )}
          
          {/* 工具调用 */}
          {step.toolCalls.map((toolCall, index) => (
            <div key={index} className="rounded-lg bg-yellow-500/10 border border-yellow-500/20 p-3">
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="w-4 h-4 text-yellow-400" />
                <span className="text-xs font-medium text-yellow-400">
                  调用工具: {toolCall.tool}
          </span>
                {toolCall.status === 'calling' && (
                  <Loader2 className="w-3 h-3 text-yellow-400 animate-spin" />
                )}
                {toolCall.status === 'success' && (
                  <CheckCircle className="w-3 h-3 text-green-400" />
                )}
                {toolCall.status === 'error' && (
                  <XCircle className="w-3 h-3 text-destructive" />
                )}
              </div>
              
              {/* 代码显示 */}
              {toolCall.result?.code && (
                <div className="mt-2">
                  <CodeBlock 
                    code={toolCall.result.code} 
                    language="python"
                    title={toolCall.result.description || toolCall.tool}
                  />
                </div>
              )}
              
              {/* 工具参数（非代码情况） */}
              {toolCall.arguments && !toolCall.result?.code && (
                <pre className="text-xs text-muted-foreground bg-secondary/50 p-2 rounded overflow-x-auto max-h-32">
                  {JSON.stringify(toolCall.arguments, null, 2)}
                </pre>
              )}
              
              {/* 工具输出 */}
              {toolCall.result?.stdout && (
                <div className="mt-2">
                  <div className="text-xs text-muted-foreground mb-1">输出结果:</div>
                  <pre className="text-xs text-cyan-300 bg-secondary/50 p-2 rounded overflow-x-auto max-h-40">
                    {toolCall.result.stdout}
                  </pre>
                </div>
              )}
              
              {/* 图片标记 */}
              {toolCall.result?.hasImage && (
                <div className="mt-2 text-xs text-pink-400 flex items-center gap-1">
                  <ImageIcon className="w-3 h-3" />
                  生成了图表
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// 简单事件卡片组件
interface SimpleEventCardProps {
  event: AgentEvent
  isExpanded: boolean
  onToggle: () => void
}

function SimpleEventCard({ event, isExpanded, onToggle }: SimpleEventCardProps) {
  const payload = event.payload
  
  const getIcon = () => {
    switch (event.type) {
      case 'connected': return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'agent_started': return <Play className="w-4 h-4 text-primary" />
      case 'agent_completed': return <CheckCircle className="w-4 h-4 text-green-400" />
      case 'agent_error': return <XCircle className="w-4 h-4 text-destructive" />
      case 'phase_change': return <Zap className="w-4 h-4 text-purple-400" />
      case 'data_explored': return <Database className="w-4 h-4 text-cyan-400" />
      case 'tasks_planned': return <FileText className="w-4 h-4 text-purple-400" />
      case 'tasks_updated': return <FileText className="w-4 h-4 text-emerald-400" />
      case 'image_generated': return <ImageIcon className="w-4 h-4 text-pink-400" />
      case 'report_generated': return <FileText className="w-4 h-4 text-green-400" />
      default: return <Terminal className="w-4 h-4 text-muted-foreground" />
    }
  }

  const getSummary = (): string => {
    switch (event.type) {
      case 'connected': return '🔗 WebSocket 连接成功'
      case 'agent_started': return '🚀 Agent 开始执行'
      case 'agent_completed': return '🎉 分析完成！'
      case 'agent_error': return `❌ 错误: ${String(payload.error)}`
      case 'phase_change': return `📍 ${String(payload.phase)}`
      case 'data_explored': 
        const stats = payload.statistics as Record<string, number>
        return `📊 数据集: ${stats?.total_rows || 0} 行 × ${stats?.total_columns || 0} 列`
      case 'tasks_planned':
        return `📋 规划了 ${(payload.tasks as unknown[])?.length || 0} 个任务`
      case 'tasks_updated':
        const tasks = payload.tasks as Array<{status: string}>
        const completed = tasks?.filter(t => t.status === 'completed').length || 0
        return `✅ 任务进度: ${completed}/${tasks?.length || 0}`
      case 'image_generated':
        return `🖼️ 生成图表`
      case 'report_generated':
        return '✨ 报告生成完成'
      default:
        return event.type.replace(/_/g, ' ')
    }
  }

  const hasExpandableContent = () => {
    switch (event.type) {
      case 'data_explored': return true
      case 'tasks_planned': return !!(payload.tasks)
      case 'tasks_updated': return !!(payload.tasks)
      case 'image_generated': return !!(payload.image_base64)
      default: return false
    }
  }

  const canExpand = hasExpandableContent()

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  }

  return (
    <div className="rounded-lg border border-border bg-card/50">
      <div 
        className={cn("flex items-center gap-3 p-3", canExpand && "cursor-pointer hover:bg-card/80")}
        onClick={canExpand ? onToggle : undefined}
      >
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
        
        <div className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-secondary">
          {getIcon()}
        </div>
        
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-foreground">{getSummary()}</span>
          <div className="text-xs text-muted-foreground/50">{formatTime(event.timestamp)}</div>
        </div>
      </div>
      
      {/* 展开内容 */}
      {isExpanded && canExpand && (
        <div className="px-4 pb-4">
          {event.type === 'tasks_planned' && (
            <div className="space-y-1">
              {(payload.tasks as Array<{id: number, name: string, type: string}>)?.map((task, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-5 h-5 rounded bg-secondary flex items-center justify-center">
                    {task.id}
                  </span>
                  <span>{task.name}</span>
                  <span className="px-1.5 py-0.5 rounded bg-secondary/50">{task.type}</span>
                </div>
              ))}
            </div>
          )}
          
          {event.type === 'tasks_updated' && (
            <div className="space-y-1">
              {(payload.tasks as Array<{id: number, name: string, status: string}>)?.map((task, i) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={cn(
                    "w-5 h-5 rounded flex items-center justify-center",
                    task.status === 'completed' ? "bg-green-500/20 text-green-400" : "bg-secondary text-muted-foreground"
                  )}>
                    {task.status === 'completed' ? '✓' : task.id}
                  </span>
                  <span className={task.status === 'completed' ? 'text-green-400' : 'text-muted-foreground'}>
                    {task.name}
                  </span>
                </div>
              ))}
            </div>
          )}
          
          {event.type === 'image_generated' && payload.image_base64 ? (
            <img
              src={`data:image/png;base64,${String(payload.image_base64)}`}
              alt="Generated chart"
              className="max-w-full rounded-lg border border-border"
            />
          ) : null}
          
          {event.type === 'data_explored' && (
            <div className="text-xs text-muted-foreground space-y-1">
              <p>缺失值: {(payload.statistics as Record<string, number>)?.missing_percentage || 0}%</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

import React, { useEffect, useRef } from 'react'
import { 
  Play, 
  Pause, 
  CheckCircle, 
  XCircle, 
  Code2, 
  Database, 
  FileText, 
  Image as ImageIcon,
  Zap,
  Terminal
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CodeBlock } from './CodeBlock'
import type { AgentEvent } from '@/hooks/useWebSocket'

interface AgentProcessProps {
  events: AgentEvent[]
  isConnected: boolean
}

const eventIcons: Record<string, React.ComponentType<{ className?: string }>> = {
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
}

const eventColors: Record<string, string> = {
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
}

const phaseLabels: Record<string, string> = {
  data_exploration: '📊 数据探索',
  planning: '📋 任务规划',
  executing: '⚡ 执行分析',
  reporting: '📝 生成报告',
}

export function AgentProcess({ events, isConnected }: AgentProcessProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events])

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
      className="space-y-3 max-h-[600px] overflow-y-auto pr-2"
    >
      {events.map((event, index) => (
        <ProcessEvent 
          key={index} 
          event={event} 
          index={index}
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

function ProcessEvent({ event, index }: { event: AgentEvent; index: number }) {
  const Icon = eventIcons[event.type] || Terminal
  const color = eventColors[event.type] || 'text-muted-foreground'
  const payload = event.payload

  const renderContent = () => {
    switch (event.type) {
      case 'phase_change':
        return (
          <div className="font-medium text-foreground">
            {phaseLabels[payload.phase as string] || `阶段: ${payload.phase}`}
          </div>
        )
      
      case 'code_generated':
        return (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              任务 #{payload.task_id}: {payload.description || '生成代码'}
            </p>
            <CodeBlock 
              code={payload.code as string} 
              language="python"
              title={`Task ${payload.task_id}`}
            />
          </div>
        )
      
      case 'image_generated':
        return (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              任务 #{payload.task_id} 生成了图表
            </p>
            <img
              src={`data:image/png;base64,${payload.image_base64}`}
              alt="Generated chart"
              className="max-w-full rounded-lg border border-border"
            />
          </div>
        )
      
      case 'tool_call':
        return (
          <div className="text-sm">
            <span className="text-foreground font-medium">
              调用工具: {payload.tool}
            </span>
            {payload.arguments && (
              <pre className="mt-1 text-xs text-muted-foreground bg-secondary/50 p-2 rounded overflow-x-auto">
                {JSON.stringify(payload.arguments, null, 2)}
              </pre>
            )}
          </div>
        )
      
      case 'tool_result':
        return (
          <div className="text-sm">
            <span className={cn(
              "font-medium",
              payload.status === 'success' ? 'text-green-400' : 'text-destructive'
            )}>
              {payload.tool}: {payload.status}
            </span>
            {payload.stdout_preview && (
              <pre className="mt-1 text-xs text-muted-foreground bg-secondary/50 p-2 rounded overflow-x-auto max-h-32">
                {payload.stdout_preview}
              </pre>
            )}
            {payload.has_image && (
              <span className="text-xs text-pink-400 ml-2">📷 包含图表</span>
            )}
          </div>
        )
      
      case 'tasks_planned':
        return (
          <div className="space-y-2">
            <p className="text-sm text-foreground font-medium">
              规划了 {(payload.tasks as unknown[])?.length || 0} 个任务
            </p>
            {payload.analysis_goal && (
              <p className="text-sm text-muted-foreground">
                目标: {payload.analysis_goal as string}
              </p>
            )}
          </div>
        )
      
      case 'data_explored':
        return (
          <div className="text-sm space-y-1">
            <p className="text-foreground">
              数据集: {(payload.statistics as Record<string, number>)?.total_rows || 0} 行 × {(payload.statistics as Record<string, number>)?.total_columns || 0} 列
            </p>
            <p className="text-muted-foreground text-xs">
              缺失值: {(payload.statistics as Record<string, number>)?.missing_percentage || 0}%
            </p>
          </div>
        )
      
      case 'task_started':
      case 'task_completed':
      case 'task_failed':
        return (
          <div className="text-sm">
            <span className="font-medium text-foreground">
              {event.type === 'task_started' && '开始执行: '}
              {event.type === 'task_completed' && '✅ 完成: '}
              {event.type === 'task_failed' && '❌ 失败: '}
              {payload.task_name}
            </span>
            {payload.error && (
              <p className="text-xs text-destructive mt-1">{payload.error as string}</p>
            )}
          </div>
        )
      
      case 'report_generated':
        return (
          <div className="text-sm text-green-400 font-medium">
            ✨ 报告生成完成
          </div>
        )
      
      case 'log':
        return (
          <div className="text-sm text-muted-foreground">
            {payload.message as string}
          </div>
        )
      
      case 'agent_completed':
        return (
          <div className="text-sm text-green-400 font-medium">
            🎉 分析完成！
          </div>
        )
      
      case 'agent_error':
        return (
          <div className="text-sm text-destructive">
            ❌ 错误: {payload.error as string}
          </div>
        )
      
      default:
        return (
          <div className="text-sm text-muted-foreground">
            {JSON.stringify(payload)}
          </div>
        )
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
      className="flex gap-3 p-3 rounded-lg bg-card/50 border border-border animate-slide-up"
      style={{ animationDelay: `${Math.min(index * 20, 200)}ms` }}
    >
      <div className={cn(
        "flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center",
        "bg-secondary"
      )}>
        <Icon className={cn("w-4 h-4", color)} />
      </div>
      
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={cn("text-xs font-medium", color)}>
            {event.type.replace(/_/g, ' ').toUpperCase()}
          </span>
          <span className="text-xs text-muted-foreground/50">
            {formatTime(event.timestamp)}
          </span>
        </div>
        {renderContent()}
      </div>
    </div>
  )
}


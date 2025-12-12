import React from 'react'
import { CheckCircle, Circle, Loader2, XCircle, SkipForward } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Task {
  id: number
  name: string
  description?: string
  type?: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped'
  code?: string
  error?: string
}

interface TaskListProps {
  tasks: Task[]
  currentTaskId?: number
}

const statusConfig: Record<string, {
  icon: React.ComponentType<{ className?: string }>
  color: string
  bgColor: string
  label: string
  animate?: boolean
}> = {
  pending: {
    icon: Circle,
    color: 'text-muted-foreground',
    bgColor: 'bg-secondary',
    label: '等待中',
  },
  in_progress: {
    icon: Loader2,
    color: 'text-primary',
    bgColor: 'bg-primary/20',
    label: '执行中',
    animate: true,
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-400',
    bgColor: 'bg-green-500/20',
    label: '已完成',
  },
  failed: {
    icon: XCircle,
    color: 'text-destructive',
    bgColor: 'bg-destructive/20',
    label: '失败',
  },
  skipped: {
    icon: SkipForward,
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/20',
    label: '已跳过',
  },
}

const typeLabels: Record<string, string> = {
  data_exploration: '数据探索',
  analysis: '数据分析',
  visualization: '可视化',
  report: '报告生成',
}

export function TaskList({ tasks, currentTaskId }: TaskListProps) {
  if (tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-muted-foreground text-sm">
        等待任务规划...
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {tasks.map((task, index) => {
        const config = statusConfig[task.status]
        const Icon = config.icon
        const isCurrent = task.id === currentTaskId
        
        return (
          <div
            key={task.id}
            className={cn(
              "relative p-4 rounded-lg border transition-all duration-300",
              isCurrent 
                ? "border-primary/50 bg-primary/5 shadow-lg shadow-primary/10" 
                : "border-border bg-card/50",
              "animate-slide-up"
            )}
            style={{ animationDelay: `${index * 50}ms` }}
          >
            {/* 连接线 */}
            {index < tasks.length - 1 && (
              <div className="absolute left-[30px] top-[60px] w-0.5 h-[calc(100%-20px)] bg-border" />
            )}
            
            <div className="flex items-start gap-3">
              {/* 状态图标 */}
              <div className={cn(
                "flex-shrink-0 w-10 h-10 rounded-lg flex items-center justify-center",
                config.bgColor
              )}>
                <Icon className={cn(
                  "w-5 h-5",
                  config.color,
                  config.animate && "animate-spin"
                )} />
              </div>
              
              {/* 任务内容 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-foreground">
                    {task.name}
                  </span>
                  {task.type && (
                    <span className="px-2 py-0.5 text-xs rounded-full bg-secondary text-muted-foreground">
                      {typeLabels[task.type] || task.type}
                    </span>
                  )}
                </div>
                
                {task.description && (
                  <p className="text-sm text-muted-foreground line-clamp-2">
                    {task.description}
                  </p>
                )}
                
                {task.error && (
                  <p className="mt-2 text-sm text-destructive bg-destructive/10 p-2 rounded">
                    {task.error}
                  </p>
                )}
                
                {/* 状态标签 */}
                <div className="mt-2 flex items-center gap-2">
                  <span className={cn(
                    "text-xs px-2 py-0.5 rounded",
                    config.bgColor,
                    config.color
                  )}>
                    {config.label}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}


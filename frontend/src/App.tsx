import { useState, useCallback, useMemo } from 'react'
import { 
  Sparkles, 
  Upload, 
  Brain, 
  FileText, 
  Loader2,
  CheckCircle,
  AlertCircle,
  Wifi,
  WifiOff,
  StopCircle,
  LayoutList,
  FileBarChart
} from 'lucide-react'
import { Button } from './components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/Card'
import { FileUpload } from './components/FileUpload'
import { TaskList, Task } from './components/TaskList'
import { AgentProcess } from './components/AgentProcess'
import { ReportViewer } from './components/ReportViewer'
import { useWebSocket, AgentEvent } from './hooks/useWebSocket'
import { cn } from './lib/utils'

type AppState = 'idle' | 'uploading' | 'processing' | 'completed' | 'stopped' | 'error'
type RightPanelTab = 'process' | 'report'

interface AnalysisResult {
  report: string
  images: Array<{
    task_id: number
    task_name: string
    image_base64: string
  }>
}

function App() {
  // 状态
  const [appState, setAppState] = useState<AppState>('idle')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [userRequest, setUserRequest] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [currentTaskId, setCurrentTaskId] = useState<number | undefined>()
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  
  // 新增状态
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>('process')
  const [selectedTaskId, setSelectedTaskId] = useState<number | 'planning'>('planning')
  const [planningStatus, setPlanningStatus] = useState<'pending' | 'in_progress' | 'completed'>('pending')

  // 计算 planningStatus：根据事件判断规划阶段的状态
  const computePlanningStatus = useCallback((events: AgentEvent[]): 'pending' | 'in_progress' | 'completed' => {
    // 检查是否有任务列表创建事件（第一次 tasks_updated with source=tool）
    const hasTasksCreated = events.some(e => 
      e.type === 'tasks_updated' && e.payload.source === 'tool'
    )
    
    if (hasTasksCreated) return 'completed'
    
    // 检查是否已开始（有任何事件）
    const hasStarted = events.some(e => 
      e.type === 'data_explored' || e.type === 'llm_streaming' || e.type === 'llm_thinking'
    )
    
    if (hasStarted) return 'in_progress'
    
    return 'pending'
  }, [])

  // WebSocket 事件处理
  const handleEvent = useCallback((event: AgentEvent) => {
    const { type, payload } = event

    // 记录状态变更
    console.log(`[App] 处理事件: ${type}`)

    switch (type) {
      case 'connected':
        console.log('[App] ✅ WebSocket 连接确认')
        setPlanningStatus('in_progress')
        break

      case 'tasks_planned':
        const plannedTasks = (payload.tasks as Task[]) || []
        console.log(`[App] 📋 收到任务规划: ${plannedTasks.length} 个任务`)
        plannedTasks.forEach((t, i) => console.log(`[App]   ${i + 1}. ${t.name}`))
        setTasks(plannedTasks)
        break

      case 'tasks_updated':
        // 自主循环模式：LLM 自主更新任务状态
        const updatedTasks = (payload.tasks as Task[]) || []
        console.log(`[App] 🔄 任务状态更新 (来源: ${payload.source}): ${updatedTasks.length} 个任务`)
        updatedTasks.forEach((t, i) => console.log(`[App]   ${t.status === 'completed' ? '✅' : '⏳'} ${t.name}`))
        
        // 标记规划阶段完成
        if (payload.source === 'tool') {
          setPlanningStatus('completed')
        }
        
        if (payload.source === 'llm') {
          // LLM 自主更新的任务状态：合并更新
          setTasks(prevTasks => {
            if (prevTasks.length === 0) {
              // 如果没有之前的任务，直接使用新任务
              return updatedTasks.map(t => ({
                ...t,
                status: t.status as Task['status']
              }))
            }
            // 合并更新：保留原有任务信息，更新状态
            return updatedTasks.map((newTask, index) => ({
              ...(prevTasks[index] || {}),
              ...newTask,
              status: newTask.status as Task['status']
            }))
          })
        } else {
          setTasks(updatedTasks)
        }
        
        // 更新当前任务ID（找到 in_progress 的任务）
        const inProgressTask = updatedTasks.find(t => t.status === 'in_progress')
        if (inProgressTask) {
          setCurrentTaskId(inProgressTask.id as number)
          setSelectedTaskId(inProgressTask.id as number)
        }
        break

      case 'task_started':
        console.log(`[App] ▶️ 任务开始: #${payload.task_id} ${payload.task_name}`)
        setCurrentTaskId(payload.task_id as number)
        setSelectedTaskId(payload.task_id as number)
        setTasks(prev => prev.map(t => 
          t.id === payload.task_id 
            ? { ...t, status: 'in_progress' as const }
            : t
        ))
        break

      case 'task_completed':
        console.log(`[App] ✅ 任务完成: #${payload.task_id} ${payload.task_name}`)
        // 任务完成时清除错误状态
        setTasks(prev => prev.map(t => 
          t.id === payload.task_id 
            ? { ...t, status: 'completed' as const, error: undefined }
            : t
        ))
        break

      case 'task_failed':
        console.log(`[App] ❌ 任务失败: #${payload.task_id} ${payload.task_name}`)
        console.log(`[App]    错误: ${payload.error}`)
        setTasks(prev => prev.map(t => 
          t.id === payload.task_id 
            ? { ...t, status: 'failed' as const, error: payload.error as string }
            : t
        ))
        break

      case 'image_generated':
        console.log(`[App] 🖼️ 收到图表: 任务 #${payload.task_id}`)
        setResult(prev => ({
          report: prev?.report || '',
          images: [
            ...(prev?.images || []),
            {
              task_id: payload.task_id as number,
              task_name: payload.task_name as string || `Task ${payload.task_id}`,
              image_base64: payload.image_base64 as string,
            }
          ]
        }))
        break

      case 'report_generated':
        console.log(`[App] 📝 收到报告: ${(payload.report as string)?.length || 0} 字符`)
        setResult(prev => ({
          ...prev,
          report: payload.report as string,
          images: prev?.images || []
        }))
        break

      case 'agent_completed':
        console.log('[App] 🎉 Agent 执行完成!')
        setAppState('completed')
        setCurrentTaskId(undefined)
        // 检查是否因达到迭代上限而结束
        if (payload.reached_max_iterations) {
          console.warn(`[App] ⚠️ 达到最大迭代次数，${payload.incomplete_tasks_count} 个任务未完成`)
          setError(`分析达到最大迭代次数，${payload.incomplete_tasks_count} 个任务未完成。报告可能不完整。`)
        }
        // 自动切换到报告 Tab
        setRightPanelTab('report')
        if (payload.final_report) {
          setResult(prev => ({
            report: payload.final_report as string,
            images: (payload.images as AnalysisResult['images']) || prev?.images || []
          }))
        }
        break

      case 'agent_warning':
        console.warn('[App] ⚠️ Agent 警告:', payload.warning)
        setError(payload.warning as string)
        break

      case 'agent_error':
        console.error('[App] 💥 Agent 错误:', payload.error)
        setAppState('error')
        setError(payload.error as string)
        break

      case 'agent_stopped':
        console.log('[App] ⏹️ Agent 已停止')
        setAppState('stopped')
        break

      case 'phase_change':
        console.log(`[App] 📍 阶段变更: ${payload.phase}`)
        break

      case 'tool_call':
        console.log(`[App] 🔧 工具调用: ${payload.tool}`)
        break

      case 'tool_result':
        console.log(`[App] 📊 工具结果: ${payload.tool} - ${payload.status}`)
        break

      case 'log':
        console.log(`[App] 📝 日志: ${payload.message}`)
        break

      default:
        console.log(`[App] 未处理事件类型: ${type}`)
    }
  }, [])

  // WebSocket 连接
  const { isConnected, events, clearEvents } = useWebSocket(sessionId, {
    onEvent: handleEvent,
    onConnect: () => {
      console.log('[App] 🟢 WebSocket 已连接')
    },
    onDisconnect: () => {
      console.log('[App] 🔴 WebSocket 已断开')
    },
    onError: (error) => {
      console.error('[App] ⚠️ WebSocket 错误:', error)
    }
  })

  // 开始分析
  const handleStartAnalysis = async () => {
    if (!selectedFile || !userRequest.trim()) return

    console.log('========================================')
    console.log('[App] 开始分析流程')
    console.log('[App] 文件:', selectedFile.name, '大小:', selectedFile.size)
    console.log('[App] 需求:', userRequest.slice(0, 100))
    console.log('========================================')

    setAppState('uploading')
    setError(null)
    setResult(null)
    setTasks([])
    setRightPanelTab('process')
    setSelectedTaskId('planning')
    setPlanningStatus('pending')
    clearEvents()

    const formData = new FormData()
    formData.append('file', selectedFile)
    formData.append('user_request', userRequest)

    try {
      console.log('[App] 📤 调用 /api/start...')
      const startTime = Date.now()
      
      const response = await fetch('/api/start', {
        method: 'POST',
        body: formData,
      })

      const apiDuration = Date.now() - startTime
      console.log(`[App] API 响应耗时: ${apiDuration}ms`)

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `服务器错误: ${response.status}`)
      }

      const data = await response.json()
      console.log('[App] ✅ API 响应:', data)

      if (data.session_id) {
        console.log('[App] 🔗 准备连接 WebSocket, session:', data.session_id)
        // 先设置 processing 状态，然后设置 sessionId 触发 WebSocket 连接
        setAppState('processing')
        // 使用 setTimeout 确保状态更新后再设置 sessionId
        // 这样可以确保 UI 先切换到 processing 状态
        setTimeout(() => {
          console.log('[App] 🔌 触发 WebSocket 连接')
          setSessionId(data.session_id)
        }, 50)
      } else {
        throw new Error('未获取到 session_id')
      }
    } catch (e) {
      console.error('[App] ❌ 启动分析失败:', e)
      setAppState('error')
      if (e instanceof TypeError && e.message.includes('fetch')) {
        setError('无法连接到后端服务，请确保后端已启动（端口 8003）')
      } else {
        setError(e instanceof Error ? e.message : '未知错误')
      }
    }
  }

  // 停止分析
  const handleStopAnalysis = async () => {
    if (!sessionId) return
    
    console.log('[App] ⏹️ 请求停止分析...')
    
    try {
      const response = await fetch(`/api/stop/${sessionId}`, {
        method: 'POST',
      })
      
      if (response.ok) {
        console.log('[App] ✅ 停止请求已发送')
        setAppState('stopped')
      } else {
        console.error('[App] ❌ 停止请求失败')
      }
    } catch (e) {
      console.error('[App] ❌ 停止请求出错:', e)
    }
  }

  // 重置
  const handleReset = () => {
    setAppState('idle')
    setSelectedFile(null)
    setUserRequest('')
    setSessionId(null)
    setTasks([])
    setCurrentTaskId(undefined)
    setResult(null)
    setError(null)
    setRightPanelTab('process')
    setSelectedTaskId('planning')
    setPlanningStatus('pending')
    clearEvents()
  }

  // 处理任务点击
  const handleTaskClick = useCallback((taskId: number | 'planning') => {
    setSelectedTaskId(taskId)
  }, [])

  // 实际的 planningStatus 应该根据事件动态计算
  const actualPlanningStatus = useMemo(() => {
    if (appState === 'idle' || appState === 'uploading') return 'pending'
    return computePlanningStatus(events)
  }, [appState, events, computePlanningStatus])

  return (
    <div className="min-h-screen gradient-bg">
      {/* 头部 */}
      <header className="border-b border-border/50 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
              <Brain className="w-6 h-6 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-foreground">
                数据分析 Agent
              </h1>
              <p className="text-xs text-muted-foreground">
                AI 驱动的智能数据分析
              </p>
            </div>
          </div>
          
          <div className="flex items-center gap-4">
            {/* 停止分析按钮 */}
            {appState === 'processing' && (
              <Button
                variant="destructive"
                size="sm"
                onClick={handleStopAnalysis}
              >
                <StopCircle className="w-4 h-4 mr-2" />
                停止分析
              </Button>
            )}
            
            {/* 连接状态 */}
            {sessionId && (
              <div className={cn(
                "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs",
                isConnected 
                  ? "bg-green-500/20 text-green-400"
                  : "bg-yellow-500/20 text-yellow-400"
              )}>
                {isConnected ? (
                  <><Wifi className="w-3 h-3" /> 已连接</>
                ) : (
                  <><WifiOff className="w-3 h-3" /> 连接中...</>
                )}
              </div>
            )}
            
            {/* 状态指示 */}
            <StatusBadge state={appState} />
          </div>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-7xl mx-auto px-4 py-8">
        {appState === 'idle' || appState === 'uploading' ? (
          // 上传界面
          <div className="max-w-2xl mx-auto space-y-6 animate-fade-in">
            <div className="text-center mb-8">
              <h2 className="text-3xl font-bold text-foreground mb-3">
                开始您的数据分析之旅
              </h2>
              <p className="text-muted-foreground">
                上传数据文件，描述您的分析需求，AI Agent 将自动完成分析
              </p>
            </div>

            <Card className="glass">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Upload className="w-5 h-5 text-primary" />
                  上传数据
                </CardTitle>
                <CardDescription>
                  支持 Excel (.xlsx, .xls) 和 CSV 格式
                </CardDescription>
              </CardHeader>
              <CardContent>
                <FileUpload
                  selectedFile={selectedFile}
                  onFileSelect={setSelectedFile}
                  onClear={() => setSelectedFile(null)}
                />
              </CardContent>
            </Card>

            <Card className="glass">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-primary" />
                  分析需求
                </CardTitle>
                <CardDescription>
                  描述您想要分析的内容，越详细越好
                </CardDescription>
              </CardHeader>
              <CardContent>
                <textarea
                  value={userRequest}
                  onChange={(e) => setUserRequest(e.target.value)}
                  placeholder="例如：分析销售数据的趋势，找出表现最好的产品类别，并预测下个季度的销售额..."
                  className="w-full h-32 px-4 py-3 rounded-lg bg-secondary/30 border border-border text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                />
              </CardContent>
            </Card>

            <Button
              size="lg"
              className="w-full"
              onClick={handleStartAnalysis}
              disabled={!selectedFile || !userRequest.trim() || appState === 'uploading'}
              isLoading={appState === 'uploading'}
            >
              {appState === 'uploading' ? '启动中...' : '开始分析'}
            </Button>
          </div>
        ) : (
          // 分析界面
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* 左侧：任务列表 */}
            <div className="lg:col-span-1 space-y-4">
              <Card className="glass">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary" />
                    任务规划
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <TaskList 
                    tasks={tasks} 
                    currentTaskId={currentTaskId}
                    planningStatus={actualPlanningStatus}
                    onTaskClick={handleTaskClick}
                    selectedTaskId={selectedTaskId}
                  />
                </CardContent>
              </Card>

              {(appState === 'completed' || appState === 'error' || appState === 'stopped') && (
                <Button
                  variant="outline"
                  className="w-full"
                  onClick={handleReset}
                >
                  开始新分析
                </Button>
              )}
            </div>

            {/* 右侧：执行过程 & 结果 */}
            <div className="lg:col-span-2 space-y-4">
              {/* Tab 切换 */}
              <div className="flex border-b border-border">
                <button
                  onClick={() => setRightPanelTab('process')}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                    rightPanelTab === 'process'
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  )}
                >
                  <LayoutList className="w-4 h-4" />
                  执行过程
                </button>
                <button
                  onClick={() => setRightPanelTab('report')}
                  disabled={!result?.report}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors",
                    rightPanelTab === 'report'
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                    !result?.report && "opacity-50 cursor-not-allowed"
                  )}
                >
                  <FileBarChart className="w-4 h-4" />
                  分析报告
                  {result?.report && (
                    <span className="px-1.5 py-0.5 text-xs rounded-full bg-green-500/20 text-green-400">
                      完成
                    </span>
                  )}
                </button>
              </div>

              {/* Tab 内容 */}
              {rightPanelTab === 'process' ? (
                <Card className="glass">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2">
                      <Brain className="w-4 h-4 text-primary" />
                      Agent 执行过程
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <AgentProcess 
                      events={events} 
                      isConnected={isConnected}
                      currentTaskId={selectedTaskId}
                      onTaskClick={handleTaskClick}
                    />
                  </CardContent>
                </Card>
              ) : (
                <Card className="glass">
                  <CardContent className="pt-6">
                    <ReportViewer report={result?.report || ''} images={result?.images} />
                  </CardContent>
                </Card>
              )}

              {/* 错误信息 */}
              {error && (
                <Card className="border-destructive/50 bg-destructive/10">
                  <CardContent className="pt-6">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="font-medium text-destructive">分析出错</p>
                        <p className="text-sm text-destructive/80 mt-1">{error}</p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* 停止提示 */}
              {appState === 'stopped' && (
                <Card className="border-yellow-500/50 bg-yellow-500/10">
                  <CardContent className="pt-6">
                    <div className="flex items-start gap-3">
                      <StopCircle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
                      <div>
                        <p className="font-medium text-yellow-500">分析已停止</p>
                        <p className="text-sm text-yellow-500/80 mt-1">
                          分析过程已被手动停止，已完成的结果已保留。
                        </p>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          </div>
        )}
      </main>

      {/* 页脚 */}
      <footer className="border-t border-border/50 mt-16">
        <div className="max-w-7xl mx-auto px-4 py-6 text-center text-sm text-muted-foreground">
          <p>数据分析 Agent · AI 驱动的智能数据分析工具</p>
        </div>
      </footer>
    </div>
  )
}

// 状态徽章组件
function StatusBadge({ state }: { state: AppState }) {
  const config: Record<AppState, { icon: typeof Loader2 | null; label: string; className: string; animate: boolean }> = {
    idle: { icon: null, label: '就绪', className: 'bg-secondary text-muted-foreground', animate: false },
    uploading: { icon: Loader2, label: '上传中', className: 'bg-primary/20 text-primary', animate: true },
    processing: { icon: Brain, label: '分析中', className: 'bg-primary/20 text-primary', animate: true },
    completed: { icon: CheckCircle, label: '完成', className: 'bg-green-500/20 text-green-400', animate: false },
    stopped: { icon: StopCircle, label: '已停止', className: 'bg-yellow-500/20 text-yellow-500', animate: false },
    error: { icon: AlertCircle, label: '错误', className: 'bg-destructive/20 text-destructive', animate: false },
  }

  const { icon: Icon, label, className, animate } = config[state]

  return (
    <div className={cn(
      "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium",
      className
    )}>
      {Icon && <Icon className={cn("w-3 h-3", animate && "animate-spin")} />}
      {label}
    </div>
  )
}

export default App

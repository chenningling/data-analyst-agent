import React, { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import ReactECharts from 'echarts-for-react'
import mermaid from 'mermaid'
import { FileText, Download, Copy, Check, Image as ImageIcon } from 'lucide-react'
import { Button } from './ui/Button'
import { cn } from '@/lib/utils'

interface ReportViewerProps {
  report: string
  images?: Array<{
    task_id: number
    task_name: string
    image_base64: string
  }>
}

// 初始化 Mermaid
mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  themeVariables: {
    primaryColor: '#3b82f6',
    primaryTextColor: '#f1f5f9',
    primaryBorderColor: '#475569',
    lineColor: '#64748b',
    secondaryColor: '#1e293b',
    tertiaryColor: '#0f172a',
  },
})

export function ReportViewer({ report, images = [] }: ReportViewerProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(report)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleDownload = () => {
    const blob = new Blob([report], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `analysis-report-${new Date().toISOString().slice(0, 10)}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  if (!report) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <FileText className="w-12 h-12 mb-4 opacity-50" />
        <p className="text-sm">等待报告生成...</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* 工具栏 */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-foreground flex items-center gap-2">
          <FileText className="w-5 h-5 text-primary" />
          分析报告
        </h3>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleCopy}
          >
            {copied ? (
              <>
                <Check className="w-4 h-4 mr-1" />
                已复制
              </>
            ) : (
              <>
                <Copy className="w-4 h-4 mr-1" />
                复制
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDownload}
          >
            <Download className="w-4 h-4 mr-1" />
            下载
          </Button>
        </div>
      </div>

      {/* 报告内容 */}
      <div className="rounded-xl border border-border bg-card/50 p-6 overflow-hidden">
        <div className="markdown-content">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code: ({ className, children, ...props }) => {
                const match = /language-(\w+)/.exec(className || '')
                const language = match ? match[1] : ''
                const code = String(children).replace(/\n$/, '')

                // ECharts 图表
                if (language === 'echarts') {
                  return <EChartsBlock code={code} />
                }

                // Mermaid 图表
                if (language === 'mermaid') {
                  return <MermaidBlock code={code} />
                }

                // 普通代码块
                if (match) {
                  return (
                    <pre className="bg-card/80 rounded-lg p-4 overflow-x-auto">
                      <code className={className} {...props}>
                        {children}
                      </code>
                    </pre>
                  )
                }

                // 行内代码
                return (
                  <code className="bg-secondary/50 text-primary px-1.5 py-0.5 rounded text-sm font-mono" {...props}>
                    {children}
                  </code>
                )
              },
              table: ({ children }) => (
                <div className="overflow-x-auto my-4">
                  <table className="w-full border-collapse">
                    {children}
                  </table>
                </div>
              ),
              th: ({ children }) => (
                <th className="border border-border px-3 py-2 bg-secondary/30 font-medium text-left">
                  {children}
                </th>
              ),
              td: ({ children }) => (
                <td className="border border-border px-3 py-2">
                  {children}
                </td>
              ),
            }}
          >
            {report}
          </ReactMarkdown>
        </div>
      </div>

      {/* 生成的图片 */}
      {images.length > 0 && (
        <div className="space-y-4">
          <h4 className="text-md font-medium text-foreground flex items-center gap-2">
            <ImageIcon className="w-4 h-4 text-pink-400" />
            生成的图表 ({images.length})
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {images.map((img, index) => (
              <div
                key={index}
                className="rounded-lg border border-border bg-card/50 overflow-hidden"
              >
                <div className="px-4 py-2 bg-secondary/30 border-b border-border">
                  <p className="text-sm font-medium text-foreground">
                    {img.task_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    任务 #{img.task_id}
                  </p>
                </div>
                <div className="p-4">
                  <img
                    src={`data:image/png;base64,${img.image_base64}`}
                    alt={img.task_name}
                    className="w-full rounded"
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ECharts 图表组件
function EChartsBlock({ code }: { code: string }) {
  const [error, setError] = useState<string | null>(null)
  const [option, setOption] = useState<object | null>(null)

  useEffect(() => {
    try {
      const parsed = JSON.parse(code)
      setOption(parsed)
      setError(null)
    } catch (e) {
      setError(`ECharts 配置解析错误: ${e}`)
    }
  }, [code])

  if (error) {
    return (
      <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
        {error}
      </div>
    )
  }

  if (!option) return null

  return (
    <div className="echarts-container my-4">
      <ReactECharts
        option={option}
        style={{ height: '400px', width: '100%' }}
        theme="dark"
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}

// Mermaid 图表组件
function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const renderDiagram = async () => {
      if (!containerRef.current) return

      try {
        const id = `mermaid-${Math.random().toString(36).slice(2, 11)}`
        const { svg } = await mermaid.render(id, code)
        containerRef.current.innerHTML = svg
        setError(null)
      } catch (e) {
        setError(`Mermaid 图表渲染错误: ${e}`)
      }
    }

    renderDiagram()
  }, [code])

  if (error) {
    return (
      <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
        {error}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="my-4 p-4 rounded-lg bg-card/30 flex justify-center overflow-x-auto"
    />
  )
}


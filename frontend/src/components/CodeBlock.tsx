import React, { useState } from 'react'
import { Check, Copy, Code2 } from 'lucide-react'
import { cn } from '@/lib/utils'

interface CodeBlockProps {
  code: string
  language?: string
  title?: string
  showLineNumbers?: boolean
}

export function CodeBlock({
  code,
  language = 'python',
  title,
  showLineNumbers = true,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const lines = code.split('\n')

  return (
    <div className="rounded-lg overflow-hidden border border-border bg-card/80">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-2 bg-secondary/50 border-b border-border">
        <div className="flex items-center gap-2">
          <Code2 className="w-4 h-4 text-primary" />
          <span className="text-sm font-medium text-foreground">
            {title || language}
          </span>
        </div>
        <button
          onClick={handleCopy}
          className={cn(
            "flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors",
            copied
              ? "bg-green-500/20 text-green-400"
              : "hover:bg-secondary text-muted-foreground hover:text-foreground"
          )}
        >
          {copied ? (
            <>
              <Check className="w-3 h-3" />
              已复制
            </>
          ) : (
            <>
              <Copy className="w-3 h-3" />
              复制
            </>
          )}
        </button>
      </div>
      
      {/* 代码内容 */}
      <div className="overflow-x-auto">
        <pre className="p-4 text-sm font-mono">
          <code>
            {lines.map((line, index) => (
              <div key={index} className="flex">
                {showLineNumbers && (
                  <span className="select-none w-10 pr-4 text-right text-muted-foreground/50">
                    {index + 1}
                  </span>
                )}
                <span className="flex-1 text-foreground/90 whitespace-pre">
                  {highlightPythonSyntax(line)}
                </span>
              </div>
            ))}
          </code>
        </pre>
      </div>
    </div>
  )
}

// 简单的 Python 语法高亮
function highlightPythonSyntax(line: string): React.ReactNode {
  const keywords = ['import', 'from', 'def', 'class', 'if', 'else', 'elif', 'for', 'while', 'return', 'try', 'except', 'finally', 'with', 'as', 'in', 'not', 'and', 'or', 'True', 'False', 'None', 'lambda', 'yield', 'async', 'await']
  const builtins = ['print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict', 'set', 'tuple', 'open', 'type']
  
  // 处理注释
  const commentIndex = line.indexOf('#')
  if (commentIndex !== -1 && !isInString(line, commentIndex)) {
    const beforeComment = line.slice(0, commentIndex)
    const comment = line.slice(commentIndex)
    return (
      <>
        {highlightPythonSyntax(beforeComment)}
        <span className="text-muted-foreground italic">{comment}</span>
      </>
    )
  }
  
  // 处理字符串
  const stringMatch = line.match(/(['"])(.*?)\1|f(['"])(.*?)\3/)
  if (stringMatch) {
    const index = line.indexOf(stringMatch[0])
    const before = line.slice(0, index)
    const stringPart = stringMatch[0]
    const after = line.slice(index + stringPart.length)
    return (
      <>
        {highlightPythonSyntax(before)}
        <span className="text-green-400">{stringPart}</span>
        {highlightPythonSyntax(after)}
      </>
    )
  }
  
  // 处理关键字
  const parts: React.ReactNode[] = []
  let remaining = line
  let key = 0
  
  while (remaining) {
    let matched = false
    
    // 检查关键字
    for (const keyword of keywords) {
      const regex = new RegExp(`^\\b${keyword}\\b`)
      if (regex.test(remaining)) {
        parts.push(
          <span key={key++} className="text-purple-400 font-medium">
            {keyword}
          </span>
        )
        remaining = remaining.slice(keyword.length)
        matched = true
        break
      }
    }
    
    if (!matched) {
      // 检查内置函数
      for (const builtin of builtins) {
        const regex = new RegExp(`^\\b${builtin}\\b(?=\\()`)
        if (regex.test(remaining)) {
          parts.push(
            <span key={key++} className="text-yellow-400">
              {builtin}
            </span>
          )
          remaining = remaining.slice(builtin.length)
          matched = true
          break
        }
      }
    }
    
    if (!matched) {
      // 检查数字
      const numMatch = remaining.match(/^\d+\.?\d*/)
      if (numMatch) {
        parts.push(
          <span key={key++} className="text-orange-400">
            {numMatch[0]}
          </span>
        )
        remaining = remaining.slice(numMatch[0].length)
        matched = true
      }
    }
    
    if (!matched) {
      // 普通字符
      parts.push(remaining[0])
      remaining = remaining.slice(1)
    }
  }
  
  return <>{parts}</>
}

function isInString(line: string, index: number): boolean {
  let inSingle = false
  let inDouble = false
  
  for (let i = 0; i < index; i++) {
    if (line[i] === "'" && !inDouble) inSingle = !inSingle
    if (line[i] === '"' && !inSingle) inDouble = !inDouble
  }
  
  return inSingle || inDouble
}


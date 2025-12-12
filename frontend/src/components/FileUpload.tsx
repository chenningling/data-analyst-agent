import React, { useCallback, useState } from 'react'
import { Upload, FileSpreadsheet, X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface FileUploadProps {
  onFileSelect: (file: File) => void
  accept?: string
  maxSize?: number
  selectedFile: File | null
  onClear: () => void
}

export function FileUpload({
  onFileSelect,
  accept = ".xlsx,.xls,.csv",
  maxSize = 50 * 1024 * 1024,
  selectedFile,
  onClear,
}: FileUploadProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const validateFile = useCallback((file: File): boolean => {
    setError(null)
    
    const validExtensions = accept.split(',').map(ext => ext.trim().toLowerCase())
    const fileExt = '.' + file.name.split('.').pop()?.toLowerCase()
    
    if (!validExtensions.includes(fileExt)) {
      setError(`不支持的文件格式。请上传 ${validExtensions.join(', ')} 格式的文件。`)
      return false
    }
    
    if (file.size > maxSize) {
      setError(`文件过大。最大支持 ${Math.round(maxSize / 1024 / 1024)}MB。`)
      return false
    }
    
    return true
  }, [accept, maxSize])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    
    const file = e.dataTransfer.files[0]
    if (file && validateFile(file)) {
      onFileSelect(file)
    }
  }, [onFileSelect, validateFile])

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && validateFile(file)) {
      onFileSelect(file)
    }
  }, [onFileSelect, validateFile])

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  }

  if (selectedFile) {
    return (
      <div className="relative group">
        <div className="flex items-center gap-4 p-4 rounded-xl bg-secondary/30 border border-primary/30">
          <div className="flex-shrink-0 w-12 h-12 rounded-lg bg-primary/20 flex items-center justify-center">
            <FileSpreadsheet className="w-6 h-6 text-primary" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">
              {selectedFile.name}
            </p>
            <p className="text-xs text-muted-foreground">
              {formatFileSize(selectedFile.size)}
            </p>
          </div>
          <button
            onClick={onClear}
            className="p-2 rounded-lg hover:bg-destructive/20 text-muted-foreground hover:text-destructive transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "relative border-2 border-dashed rounded-xl p-8 text-center transition-all duration-200 cursor-pointer",
          isDragging
            ? "border-primary bg-primary/10"
            : "border-border hover:border-primary/50 hover:bg-secondary/30"
        )}
      >
        <input
          type="file"
          accept={accept}
          onChange={handleFileInput}
          className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        />
        
        <div className="flex flex-col items-center gap-3">
          <div className={cn(
            "w-14 h-14 rounded-xl flex items-center justify-center transition-colors",
            isDragging ? "bg-primary/20" : "bg-secondary"
          )}>
            <Upload className={cn(
              "w-7 h-7 transition-colors",
              isDragging ? "text-primary" : "text-muted-foreground"
            )} />
          </div>
          
          <div>
            <p className="text-sm font-medium text-foreground mb-1">
              {isDragging ? "释放以上传文件" : "拖放文件到这里，或点击选择"}
            </p>
            <p className="text-xs text-muted-foreground">
              支持 Excel (.xlsx, .xls) 和 CSV 格式，最大 {Math.round(maxSize / 1024 / 1024)}MB
            </p>
          </div>
        </div>
      </div>
      
      {error && (
        <p className="text-sm text-destructive animate-fade-in">
          {error}
        </p>
      )}
    </div>
  )
}


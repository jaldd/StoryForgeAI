import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import './App.css'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

interface Document {
  documentId: string
  type: 'CHAPTER' | 'CHARACTER' | 'WORLD' | 'OUTLINE' | 'NOTE'
  name: string
  title?: string
  chapterNumber?: number
  content?: string
  wordCount?: number
  filePath?: string
  directoryPath?: string
}

interface DirectoryNode {
  name: string
  path: string
  children: DirectoryNode[]
  documents: Document[]
}

interface Project {
  projectId: string
  title: string
  author: string
  documentCount: number
}

interface OptimizationResult {
  documentId: string
  originalContent: string
  optimizedContent: string
  suggestions: string
  hasChanges: boolean
}

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [documents, setDocuments] = useState<Document[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [expandedDirectories, setExpandedDirectories] = useState<Set<string>>(new Set())
  const [optimizationResult, setOptimizationResult] = useState<OptimizationResult | null>(null)
  const [optimizing, setOptimizing] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const currentContentRef = useRef<string>('')

  useEffect(() => {
    loadProject()
    loadDocuments()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const loadProject = async () => {
    try {
      const response = await fetch(`/api/projects/default`)
      if (response.ok) {
        const data = await response.json()
        setProject(data)
      }
    } catch (error) {
      console.error('Failed to load project:', error)
    }
  }

  const loadDocuments = async () => {
    try {
      const response = await fetch(`/api/projects/default/documents`)
      if (response.ok) {
        const data = await response.json()
        setDocuments(data)
      }
    } catch (error) {
      console.error('Failed to load documents:', error)
    }
  }

  const reloadDocuments = async () => {
    try {
      await fetch(`/api/projects/default/reload`, { method: 'POST' })
      loadDocuments()
      loadProject()
    } catch (error) {
      console.error('Failed to reload documents:', error)
    }
  }

  const loadDocument = async (docId: string) => {
    try {
      const response = await fetch(`/api/projects/default/documents/${docId}`)
      if (response.ok) {
        const data = await response.json()
        setSelectedDocument(data)
      }
    } catch (error) {
      console.error('Failed to load document:', error)
    }
  }

  const optimizeDocument = async (docId: string) => {
    try {
      setOptimizing(true)
      const response = await fetch(`/api/projects/default/documents/${docId}/optimize`, { method: 'POST' })
      if (response.ok) {
        const data = await response.json()
        setOptimizationResult(data)
      }
    } catch (error) {
      console.error('Failed to optimize document:', error)
    } finally {
      setOptimizing(false)
    }
  }

  const applyOptimization = async () => {
    if (!optimizationResult || !selectedDocument) return
    
    try {
      const response = await fetch(
        `/api/projects/default/documents/${optimizationResult.documentId}/apply-optimization`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: optimizationResult.optimizedContent,
        }
      )
      
      if (response.ok) {
        setOptimizationResult(null)
        loadDocument(selectedDocument.documentId)
        loadDocuments()
      }
    } catch (error) {
      console.error('Failed to apply optimization:', error)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || streaming) return

    const userMessage: ChatMessage = { role: 'user', content: input.trim() }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setStreaming(true)
    currentContentRef.current = ''

    const assistantMessage: ChatMessage = { role: 'assistant', content: '' }
    setMessages(prev => [...prev, assistantMessage])

    const encodedMessage = encodeURIComponent(userMessage.content)
    const eventSource = new EventSource(`/api/chat?message=${encodedMessage}`)

    eventSource.addEventListener('token', (event) => {
      const token = event.data
      if (token) {
        currentContentRef.current += token
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: currentContentRef.current,
          }
          return updated
        })
      }
    })

    eventSource.addEventListener('done', () => {
      eventSource.close()
      setStreaming(false)
    })

    eventSource.onerror = () => {
      eventSource.close()
      if (currentContentRef.current === '') {
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: '连接失败，请重试',
          }
          return updated
        })
      }
      setStreaming(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const getDocumentIcon = (type: string) => {
    switch (type) {
      case 'CHAPTER': return '📖'
      case 'CHARACTER': return '👤'
      case 'WORLD': return '🌍'
      case 'OUTLINE': return '📋'
      default: return '📝'
    }
  }

  const buildDirectoryTree = (docs: Document[]): DirectoryNode => {
    const root: DirectoryNode = { name: '', path: '', children: [], documents: [] }
    
    docs.forEach(doc => {
      const dirPath = doc.directoryPath || ''
      const parts = dirPath.split('/').filter(p => p)
      
      let current = root
      
      parts.forEach(part => {
        let child = current.children.find(c => c.name === part)
        if (!child) {
          child = { name: part, path: current.path ? `${current.path}/${part}` : part, children: [], documents: [] }
          current.children.push(child)
        }
        current = child
      })
      
      current.documents.push(doc)
    })
    
    const sortDirectory = (node: DirectoryNode) => {
      node.children.sort((a, b) => a.name.localeCompare(b.name))
      node.documents.sort((a, b) => a.name.localeCompare(b.name))
      node.children.forEach(sortDirectory)
    }
    sortDirectory(root)
    
    return root
  }

  const toggleDirectory = (path: string) => {
    setExpandedDirectories(prev => {
      const newSet = new Set(prev)
      if (newSet.has(path)) {
        newSet.delete(path)
      } else {
        newSet.add(path)
      }
      return newSet
    })
  }

  const renderDirectoryTree = (node: DirectoryNode, level: number = 0) => {
    const isExpanded = expandedDirectories.has(node.path)
    
    return (
      <div key={node.path || 'root'} className="directory-node">
        {node.path && (
          <div 
            className="directory-header" 
            style={{ paddingLeft: `${level * 16 + 8}px` }}
            onClick={() => toggleDirectory(node.path)}
          >
            <span className="directory-toggle">
              {(node.children.length > 0 || node.documents.length > 0) ? (isExpanded ? '▼' : '▶') : ''}
            </span>
            <span className="directory-icon">📁</span>
            <span className="directory-name">{node.name}</span>
          </div>
        )}
        
        {(node.path === '' || isExpanded) && (
          <div className="directory-content">
            {node.children.map(child => renderDirectoryTree(child, level + (node.path ? 1 : 0)))}
            {node.documents.map(doc => (
              <div 
                key={doc.documentId}
                className={`document-item ${selectedDocument?.documentId === doc.documentId ? 'selected' : ''}`}
                style={{ paddingLeft: `${(level + (node.path ? 1 : 0)) * 16 + 8}px` }}
              >
                <div className="document-info" onClick={() => loadDocument(doc.documentId)}>
                  <span className="doc-icon">{getDocumentIcon(doc.type)}</span>
                  <span className="doc-name">
                    {doc.type === 'CHAPTER' && doc.chapterNumber ? `第${doc.chapterNumber}章` : ''} {doc.title || doc.name}
                  </span>
                </div>
                <button 
                  className="optimize-btn" 
                  onClick={(e) => {
                    e.stopPropagation()
                    optimizeDocument(doc.documentId)
                  }}
                  title="优化文档"
                  disabled={optimizing}
                >
                  ✨
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // const getDocumentTypeName = (type: string) => {
  //   switch (type) {
  //     case 'CHAPTER': return '章节'
  //     case 'CHARACTER': return '角色'
  //     case 'WORLD': return '世界观'
  //     case 'OUTLINE': return '大纲'
  //     default: return '笔记'
  //   }
  // }

  const directoryTree = buildDirectoryTree(documents)

  return (
    <div className="app">
      {sidebarOpen && (
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="project-info">
              <h2>{project?.title || '加载中...'}</h2>
              <span className="project-meta">{project?.documentCount} 个文档</span>
            </div>
            <button 
              className="reload-btn" 
              onClick={reloadDocuments}
              title="重新加载文档"
            >
              🔄
            </button>
          </div>

          <div className="document-list">
            {documents.length > 0 ? (
              renderDirectoryTree(directoryTree)
            ) : (
              <div className="empty-docs">
                <p>暂无文档</p>
                <p className="hint">将你的小说文档放到 ./../novel/documents 目录</p>
                <p className="hint">然后点击 🔄 重新加载</p>
              </div>
            )}
          </div>
        </aside>
      )}

      <main className="main-content">
        <header className="header">
          <button 
            className="toggle-sidebar" 
            onClick={() => setSidebarOpen(!sidebarOpen)}
            title={sidebarOpen ? '隐藏侧边栏' : '显示侧边栏'}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>
          <div className="header-title">
            <h1>StoryForgeAI</h1>
            <span className="subtitle">AI 驱动的小说创作助手</span>
          </div>
        </header>

        {selectedDocument && (
          <div className="document-preview">
            <div className="preview-header">
              <h3>{getDocumentIcon(selectedDocument.type)} {selectedDocument.title || selectedDocument.name}</h3>
              <button 
                className="close-preview" 
                onClick={() => setSelectedDocument(null)}
              >
                ✕
              </button>
            </div>
            <div className="preview-content">
              <ReactMarkdown>
                {selectedDocument.content || ''}
              </ReactMarkdown>
            </div>
          </div>
        )}

        <div className="messages">
          {messages.length === 0 && (
            <div className="empty">
              <p>开始你的创作之旅 ✍️</p>
              <p className="hint">试试："帮我分析一下张伟这个角色" 或 "根据第一章续写"</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`}>
              <div className="avatar">{msg.role === 'user' ? '👤' : '🤖'}</div>
              <div className="content">{msg.content || '...'}</div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的创作需求..."
            rows={2}
            disabled={streaming}
          />
          <button onClick={sendMessage} disabled={streaming || !input.trim()}>
            {streaming ? '生成中...' : '发送'}
          </button>
        </div>
      </main>

      {optimizationResult && (
        <div className="optimization-dialog">
          <div className="dialog-content">
            <div className="dialog-header">
              <h3>文档优化结果</h3>
              <button 
                className="close-dialog" 
                onClick={() => setOptimizationResult(null)}
              >
                ✕
              </button>
            </div>
            <div className="dialog-body">
              <div className="optimization-section">
                <h4>优化建议</h4>
                <div className="suggestions">
                  {optimizationResult.suggestions}
                </div>
              </div>
              {optimizationResult.hasChanges && (
                <div className="optimization-section">
                  <h4>格式转换</h4>
                  <p>文档已转换为标准Markdown格式</p>
                </div>
              )}
            </div>
            <div className="dialog-footer">
              <button 
                className="btn-secondary" 
                onClick={() => setOptimizationResult(null)}
              >
                取消
              </button>
              <button 
                className="btn-primary" 
                onClick={applyOptimization}
              >
                应用
              </button>
            </div>
          </div>
        </div>
      )}

      {optimizing && (
        <div className="loading-overlay">
          <div className="loading-spinner">
            <p>优化中...</p>
          </div>
        </div>
      )}
    </div>
  )
}

export default App

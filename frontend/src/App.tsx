import { useState, useRef, useEffect } from 'react'
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
}

interface Project {
  projectId: string
  title: string
  author: string
  documentCount: number
}

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [documents, setDocuments] = useState<Document[]>([])
  const [project, setProject] = useState<Project | null>(null)
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
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
      const response = await fetch('/api/projects/default')
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
      const response = await fetch('/api/projects/default/documents')
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
      await fetch('/api/projects/default/reload', { method: 'POST' })
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

  const getDocumentTypeName = (type: string) => {
    switch (type) {
      case 'CHAPTER': return '章节'
      case 'CHARACTER': return '角色'
      case 'WORLD': return '世界观'
      case 'OUTLINE': return '大纲'
      default: return '笔记'
    }
  }

  const chapters = documents.filter(d => d.type === 'CHAPTER').sort((a, b) => (a.chapterNumber || 0) - (b.chapterNumber || 0))
  const characters = documents.filter(d => d.type === 'CHARACTER')
  const worlds = documents.filter(d => d.type === 'WORLD')
  const others = documents.filter(d => !['CHAPTER', 'CHARACTER', 'WORLD'].includes(d.type))

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
            {chapters.length > 0 && (
              <div className="document-section">
                <h3>📖 章节</h3>
                {chapters.map(doc => (
                  <div 
                    key={doc.documentId}
                    className={`document-item ${selectedDocument?.documentId === doc.documentId ? 'selected' : ''}`}
                    onClick={() => loadDocument(doc.documentId)}
                  >
                    <span className="doc-icon">{getDocumentIcon(doc.type)}</span>
                    <span className="doc-name">
                      {doc.chapterNumber ? `第${doc.chapterNumber}章` : ''} {doc.title || doc.name}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {characters.length > 0 && (
              <div className="document-section">
                <h3>👤 角色</h3>
                {characters.map(doc => (
                  <div 
                    key={doc.documentId}
                    className={`document-item ${selectedDocument?.documentId === doc.documentId ? 'selected' : ''}`}
                    onClick={() => loadDocument(doc.documentId)}
                  >
                    <span className="doc-icon">{getDocumentIcon(doc.type)}</span>
                    <span className="doc-name">{doc.name}</span>
                  </div>
                ))}
              </div>
            )}

            {worlds.length > 0 && (
              <div className="document-section">
                <h3>🌍 世界观</h3>
                {worlds.map(doc => (
                  <div 
                    key={doc.documentId}
                    className={`document-item ${selectedDocument?.documentId === doc.documentId ? 'selected' : ''}`}
                    onClick={() => loadDocument(doc.documentId)}
                  >
                    <span className="doc-icon">{getDocumentIcon(doc.type)}</span>
                    <span className="doc-name">{doc.name}</span>
                  </div>
                ))}
              </div>
            )}

            {others.length > 0 && (
              <div className="document-section">
                <h3>📝 其他</h3>
                {others.map(doc => (
                  <div 
                    key={doc.documentId}
                    className={`document-item ${selectedDocument?.documentId === doc.documentId ? 'selected' : ''}`}
                    onClick={() => loadDocument(doc.documentId)}
                  >
                    <span className="doc-icon">{getDocumentIcon(doc.type)}</span>
                    <span className="doc-name">{doc.name}</span>
                  </div>
                ))}
              </div>
            )}

            {documents.length === 0 && (
              <div className="empty-docs">
                <p>暂无文档</p>
                <p className="hint">将你的小说文档放到 ./documents 目录</p>
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
              <pre>{selectedDocument.content}</pre>
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
    </div>
  )
}

export default App

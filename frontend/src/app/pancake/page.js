'use client'

import { useState, useEffect, useRef } from 'react'
import { 
  Send, Loader2, BookOpen, X, Upload, FileText, CheckSquare, Square, 
  ChevronRight, ChevronLeft, ThumbsUp, ThumbsDown, BarChart3, User, 
  Trash2, Sparkles, Zap, ArrowRight, Layers, LayoutGrid, Database, Eye
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Markdown from '../../components/Markdown'
import { t, resolveLang } from '../../lib/i18n'
import {
  streamQuery, streamSSE, listDocuments, getDocumentCategories, uploadDocuments, getTaskStatus,
  getRetrievalConfig, submitFeedback, getDocumentContent, getConversations,
  createConversation, getConversationMessages, deleteConversation
} from '../../lib/api'
import GuideModal from '../../components/GuideModal'

function enhanceCitations(content) {
  let out = String(content || '')
  out = out.replace(/\[Source\s+(\d+)\](?!\()/gi, '[$1](#cite-$1)')
  out = out.replace(/\[(\d+)\](?!\()/g, '[$1](#cite-$1)')
  return out
}

const REASON_IDS = ['hallucination', 'incomplete_chunk', 'off_topic', 'wrong_reference'];
const STORAGE_KEYS = {
  profile: 'rag_profile_v1',
  lang: 'rag_lang',
  chatPrefix: 'rag_chat_',
  sourcesPrefix: 'rag_sources_',
  drawerOpen: 'rag_drawer_open',
};

const newMsgId = () => 'm-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7);

function hashUserId(name) {
  const n = (name || '').trim();
  if (!n || n === 'Guest_01') return 1;
  let h = 0;
  for (let i = 0; i < n.length; i++) {
    h = ((h << 5) - h + n.charCodeAt(i)) | 0;
  }
  return (Math.abs(h) % 2147483000) + 1001;
}

function readLocal(key, fallback) {
  if (typeof window === 'undefined') return fallback;
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) { return fallback; }
}

function writeLocal(key, value) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (err) {}
}

function defaultProfile() {
  const saved = readLocal(STORAGE_KEYS.profile, null);
  if (saved && typeof saved === 'object' && saved.name) {
    const name = saved.name.trim() || 'Guest_01';
    return { name, userId: Number(saved.userId) || hashUserId(name), apiKey: saved.apiKey || '', baseUrl: saved.baseUrl || '', model: saved.model || '' };
  }
  return { name: 'Guest_01', userId: 1, apiKey: '', baseUrl: '', model: '' };
}

export default function Home() {
  const [entered, setEntered] = useState(false)
  const [navTab, setNavTab] = useState('gallery')
  const [isFading, setIsFading] = useState(false) 
  const [mousePos, setMousePos] = useState({ x: 0, y: 0, cx: -999, cy: -999 })

  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [showSourcesPanel, setShowSourcesPanel] = useState(false)
  const [isDrawerOpen, setIsDrawerOpen] = useState(() => readLocal(STORAGE_KEYS.drawerOpen, true))
  const [rightTab, setRightTab] = useState('sources')
  const [documents, setDocuments] = useState([])
  const [categoryTree, setCategoryTree] = useState(null)
  const [selectedDocIds, setSelectedDocIds] = useState(new Set())
  const [kbMode, setKbMode] = useState('keyword')
  const [docLoading, setDocLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')
  const [strategy, setStrategy] = useState('hybrid_parent_child')
  const [strategies, setStrategies] = useState(['naive', 'hybrid', 'hybrid_parent_child'])
  const [presets, setPresets] = useState([])
  const [activePreset, setActivePreset] = useState(null)
  const [lang, setLang] = useState('zh')
  const [profileOpen, setProfileOpen] = useState(false)
  const [profileDraft, setProfileDraft] = useState(null)
  const [profile, setProfile] = useState(defaultProfile)
  const [feedbackByMsg, setFeedbackByMsg] = useState({})
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState(null)
  const [conversationLoading, setConversationLoading] = useState(false)
  const [viewerDoc, setViewerDoc] = useState(null)
  const [viewerLoading, setViewerLoading] = useState(false)
  const [highlightText, setHighlightText] = useState('')
  
  const fileInputRef = useRef(null)
  const chatContainerRef = useRef(null) // 修复页面飞出 Bug 的内部滚动锚点

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('tab') === 'workspace') {
      setEntered(true)
      setNavTab('workspace')
    } else if (params.get('tab') === 'gallery') {
      setEntered(false)
      setNavTab('gallery')
    } else {
      setNavTab(entered ? 'workspace' : 'gallery')
    }
  }, [])

  // 丝滑过渡与防偏移修正
  const handleTabChange = (targetTab) => {
    if (targetTab === navTab) return;
    setIsFading(true);
    setTimeout(() => {
      if (targetTab === 'dashboard') {
        window.location.href = '/dashboard';
      } else {
        // 强制归零任何隐形页面坐标偏移，防止视口异常
        window.scrollTo(0, 0);
        document.body.scrollTop = 0;
        document.documentElement.scrollTop = 0;

        setNavTab(targetTab);
        setEntered(targetTab === 'workspace');
        requestAnimationFrame(() => {
          setIsFading(false);
        });
      }
    }, 300);
  }

  const handleMouseMove = (e) => {
    const { innerWidth, innerHeight } = window
    const x = (e.clientX / innerWidth - 0.5) * 40
    const y = (e.clientY / innerHeight - 0.5) * 40
    setMousePos({ x, y, cx: e.clientX, cy: e.clientY })
  }

  const loadDocuments = async (userId) => {
    setDocLoading(true)
    try {
      // Fetch the flat doc list and the authoritative category tree in parallel.
      const [data, catData] = await Promise.all([
        listDocuments(userId),
        getDocumentCategories(userId).catch(() => null),
      ])
      const docs = data.documents || []
      setDocuments(docs)
      setKbMode(data.mode || 'keyword')
      setCategoryTree(catData?.categories || null)
      const ids = docs.map(d => d.id).filter(id => id != null)
      if (ids.length) setSelectedDocIds(new Set(ids))
    } catch (error) {
      console.error('Failed to load documents', error)
      setDocuments([])
      setCategoryTree(null)
    } finally {
      setDocLoading(false)
    }
  }

  const loadConversations = async (userId) => {
    try {
      const list = await getConversations(userId || profile.userId)
      setConversations(list)
    } catch (err) {
      console.error('Failed to load conversations', err)
    }
  }

  const openConversation = async (conv) => {
    if (!conv?.id) return
    setConversationLoading(true)
    try {
      const list = await getConversationMessages(conv.id, profile.userId)
      const normalized = (list || []).map(m => ({
        id: m.id != null ? 'srv-' + m.id : newMsgId(),
        role: m.role,
        content: m.content,
        sources: m.sources || [],
        meta: m.latency_meta && Object.keys(m.latency_meta).length ? { ...m.latency_meta, refusal: !!m.latency_meta.refusal } : null
      }))
      setMessages(normalized)
      setSources(normalized.filter(m => m.role === 'assistant').at(-1)?.sources || [])
      setActiveConversationId(conv.id)
      setShowSourcesPanel(false)
    } catch (err) {
      console.error('Failed to open conversation', err)
    } finally {
      setConversationLoading(false)
    }
  }

  const newConversation = async () => {
    try {
      const res = await createConversation(profile.userId, t(lang, 'newSession'))
      const conv = { id: res.conversation_id, title: res.title || t(lang, 'newSession'), message_count: 0 }
      setActiveConversationId(conv.id)
      setConversations(prev => [conv, ...prev.filter(c => c.id !== conv.id)])
      setMessages([])
      setSources([])
      setShowSourcesPanel(false)
      setViewerDoc(null)
    } catch (err) {
      console.error('Failed to create conversation', err)
    }
  }

  const removeConversation = async (conv, e) => {
    e && e.stopPropagation()
    if (typeof window !== 'undefined' && !window.confirm(t(lang, 'deleteConversationConfirm'))) return
    try {
      await deleteConversation(conv.id, profile.userId)
      setConversations(prev => prev.filter(c => c.id !== conv.id))
      if (activeConversationId === conv.id) {
        setActiveConversationId(null)
        setMessages([])
        setSources([])
      }
    } catch (err) {
      console.error('Failed to delete conversation', err)
    }
  }

  const formatSessionTime = (ts) => {
    if (!ts) return ''
    const d = new Date(Number(ts) * 1000)
    return d.toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  useEffect(() => { setProfile(defaultProfile()); setLang(resolveLang()); }, [])

  useEffect(() => {
    if (!profile.userId) return;
    setActiveConversationId(null)
    loadDocuments(profile.userId)
    loadConversations(profile.userId)
  }, [profile.userId])

  useEffect(() => {
    if (!profile.userId) return;
    const chatKey = STORAGE_KEYS.chatPrefix + profile.userId;
    const srcKey = STORAGE_KEYS.sourcesPrefix + profile.userId;
    const restored = readLocal(chatKey, []);
    const restoredSources = readLocal(srcKey, []);
    setMessages(Array.isArray(restored) ? restored : []);
    setSources(Array.isArray(restoredSources) ? restoredSources : []);
  }, [profile.userId])

  useEffect(() => {
    if (!profile.userId) return;
    if (messages.length > 0) writeLocal(STORAGE_KEYS.chatPrefix + profile.userId, messages)
  }, [messages, profile.userId])

  useEffect(() => {
    if (!profile.userId) return;
    if (sources.length > 0) writeLocal(STORAGE_KEYS.sourcesPrefix + profile.userId, sources)
  }, [sources, profile.userId])

  useEffect(() => {
    writeLocal(STORAGE_KEYS.drawerOpen, !!isDrawerOpen)
  }, [isDrawerOpen])

  useEffect(() => {
    getRetrievalConfig()
      .then(cfg => {
        if (cfg.strategies?.length) setStrategies(cfg.strategies)
        setStrategy(cfg.default_strategy || 'hybrid_parent_child')
        setPresets(cfg.presets || [])
      })
      .catch(err => console.error('Failed to load retrieval config', err))
  }, [])

  // 修复核心：安全内部滚动，杜绝 scrollIntoView 导致整个全屏被弹飞的 Bug
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTo({
        top: chatContainerRef.current.scrollHeight,
        behavior: 'smooth'
      })
    }
  }, [messages])

  useEffect(() => {
    if (viewerDoc?.content && highlightText) {
      const timer = setTimeout(() => {
        const el = document.querySelector('.rag-highlight');
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
      }, 250)
      return () => clearTimeout(timer)
    }
  }, [viewerDoc, highlightText])

  const toggleLang = () => {
    const next = lang === 'zh' ? 'en' : 'zh'
    setLang(next)
    try { window.localStorage.setItem(STORAGE_KEYS.lang, next) } catch (err) {}
  }

  const openProfileModal = () => {
    setProfileDraft({ ...profile })
    setProfileOpen(true)
  }

  const saveProfile = () => {
    const name = (profileDraft?.name || '').trim() || 'Guest_01'
    const next = {
      name,
      userId: name === 'Guest_01' ? 1 : hashUserId(name),
      apiKey: (profileDraft?.apiKey || '').trim(),
      baseUrl: (profileDraft?.baseUrl || '').trim(),
      model: (profileDraft?.model || '').trim(),
    }
    setProfile(next)
    writeLocal(STORAGE_KEYS.profile, next)
    setProfileOpen(false)
    setShowSourcesPanel(false)
  }

  const resetProfile = () => {
    const next = { name: 'Guest_01', userId: 1, apiKey: '', baseUrl: '', model: '' }
    setProfile(next)
    writeLocal(STORAGE_KEYS.profile, next)
    setProfileOpen(false)
    setShowSourcesPanel(false)
  }

  const upsertAssistant = (patch) => {
    setMessages(prev => {
      const last = prev[prev.length - 1]
      if (last?.role === 'assistant') {
        const copy = prev.slice()
        copy[copy.length - 1] = { ...last, ...patch }
        return copy
      }
      return [...prev, { id: newMsgId(), role: 'assistant', content: '', streaming: true, ...patch }]
    })
  }

  const showDrawer = (tab) => {
    setShowSourcesPanel(true)
    setIsDrawerOpen(true)
    if (tab) setRightTab(tab)
  }

  const openDocument = async (doc) => {
    if (!doc?.id) return
    showDrawer('viewer')
    setViewerLoading(true)
    setHighlightText('')
    try {
      const payload = await getDocumentContent(doc.id, profile.userId)
      setViewerDoc(payload)
    } catch (err) {
      console.error('Failed to open document', err)
      setViewerDoc({ id: doc.id, filename: doc.filename, content: '', chunk_count: 0 })
    } finally {
      setViewerLoading(false)
    }
  }

  const locateSource = async (item) => {
    const filename = String(item?.source || '').split(' #')[0]
    const doc = documents.find(d => d.filename === filename)
    if (!doc) return
    if (!viewerDoc || viewerDoc.id !== doc.id) {
      await openDocument(doc)
    }
    const excerpt = (item?.excerpt || '').trim().slice(0, 120)
    setHighlightText(excerpt || filename)
    showDrawer('viewer')
  }

  const handleCitation = (msg, n) => {
    const list = msg?.sources || sources
    const item = list[n - 1]
    if (item) locateSource(item)
  }

  const pollTask = async (taskId) => {
    let attempts = 0
    const maxAttempts = 60
    while (attempts < maxAttempts) {
      try {
        const task = await getTaskStatus(taskId)
        if (task.status === 'completed' || task.status === 'failed') {
          await loadDocuments(profile.userId)
          if (task.status === 'completed') {
            setUploadMessage('done:' + (task.result?.uploaded?.length || 0) + ':' + (task.result?.total_chunks || 0) + ':' + (task.result?.mode || 'keyword'))
          } else {
            setUploadMessage('failed:' + (task.error || 'unknown'))
          }
          return task
        }
        setUploadMessage('processing')
      } catch (err) {}
      await new Promise(r => setTimeout(r, 1000))
      attempts++
    }
    setUploadMessage('timeout')
  }

  const handleUpload = async (event) => {
    const fileList = Array.from(event.target.files || [])
    event.target.value = ''
    if (!fileList.length) return
    setUploading(true)
    setUploadMessage('uploading:' + fileList.length)
    try {
      const result = await uploadDocuments(fileList, profile.userId)
      if (result.task_id) {
        await pollTask(result.task_id)
      } else {
        await loadDocuments(profile.userId)
        setUploadMessage('done:' + (result.uploaded?.length || 0) + ':' + (result.total_chunks || 0) + ':' + (result.mode || 'keyword'))
      }
    } catch (error) {
      setUploadMessage('failed:' + error.message)
    } finally {
      setUploading(false)
    }
  }

  const clearChat = () => {
    if (typeof window !== 'undefined' && !window.confirm(t(lang, 'clearConfirm'))) return
    setMessages([])
    setSources([])
    setShowSourcesPanel(false)
    setViewerDoc(null)
    setHighlightText('')
  }

  const findQuestionFor = (msg) => {
    const idx = messages.indexOf(msg)
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') return messages[i].content
    }
    return ''
  }

  const submitRating = async (msg, thumbs, reasons = []) => {
    const next = { thumbs, reasons }
    setFeedbackByMsg(prev => ({ ...prev, [msg.id]: next }))
    try {
      await submitFeedback({
        user_id: profile.userId,
        thumbs,
        reasons,
        question: findQuestionFor(msg).slice(0, 300),
        answer_excerpt: msg.content.slice(0, 300),
      })
    } catch (err) {
      console.error('Failed to submit feedback', err)
    }
  }

  const ask = async (questionText, presetOverride) => {
    const question = String(questionText || '').trim()
    if (!question || isLoading) return
    const preset = presetOverride !== undefined ? presetOverride : activePreset
    const history = messages.slice(-6).map(m => ({ role: m.role, content: m.content }))
    const docIds = selectedDocIds.size ? Array.from(selectedDocIds) : undefined
    const startedAt = typeof performance !== 'undefined' ? performance.now() : Date.now()
    let firstTokenMs = null
    let text = ''
    let refusalFlag = false
    setMessages(prev => [...prev, { id: newMsgId(), role: 'user', content: question }])
    setInput('')
    setSources([])
    setIsLoading(true)
    try {
      const reader = await streamQuery({
        question,
        history,
        doc_ids: docIds,
        user_id: profile.userId,
        apiKey: profile.apiKey || undefined,
        baseUrl: profile.baseUrl || undefined,
        model: profile.model || undefined,
        strategy,
        preset,
        conversation_id: activeConversationId || null
      })
      for await (const event of streamSSE(reader)) {
        const type = event.event
        if (type === 'conversation') {
          try {
            const parsed = JSON.parse(event.data)
            if (parsed.conversation_id) setActiveConversationId(parsed.conversation_id)
          } catch (err) {}
        } else if (type === 'token') {
          if (firstTokenMs === null) firstTokenMs = Math.round((performance.now() - startedAt))
          let piece
          try { piece = JSON.parse(event.data) } catch (err) { piece = event.data }
          text += piece
          upsertAssistant({ content: text })
        } else if (type === 'sources') {
          try {
            const parsed = JSON.parse(event.data)
            setSources(parsed)
            showDrawer('sources')
            upsertAssistant({ sources: parsed })
          } catch (err) {}
        } else if (type === 'refusal') {
          refusalFlag = true
          try {
            const parsed = JSON.parse(event.data)
            upsertAssistant({ content: parsed.message || 'No answer', streaming: false, refusal: true, meta: { refusal: true, latency_ms: Math.round(performance.now() - startedAt) } })
          } catch (err) {
            upsertAssistant({ content: event.data, streaming: false, refusal: true })
          }
        } else if (type === 'done') {
          try {
            const stats = JSON.parse(event.data)
            upsertAssistant({
              streaming: false,
              refusal: refusalFlag ? true : false,
              meta: {
                retrieve_ms: Number(stats.retrieve_time_ms || 0),
                first_token_ms: firstTokenMs || 0,
                latency_ms: Math.round(performance.now() - startedAt),
                total_tokens: Number(stats.total_tokens || 0),
                refusal: refusalFlag
              }
            })
          } catch (err) {
            upsertAssistant({ streaming: false })
          }
        } else if (type === 'error') {
          setMessages(prev => [...prev, { id: newMsgId(), role: 'assistant', content: 'Error: ' + event.data, streaming: false }])
        }
      }
    } catch (error) {
      console.error('Streaming error:', error)
      setMessages(prev => [...prev, { id: newMsgId(), role: 'assistant', content: 'Error: ' + (error.message || 'network error'), streaming: false }])
    } finally {
      setIsLoading(false)
      loadConversations(profile.userId)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    ask(input)
  }

  const modeLabel = (mode) => mode === 'vector' ? t(lang, 'vectorMode') : t(lang, 'keywordMode')
  const statusLabel = (status) => {
    const map = { ready: 'statusReady', parsing: 'statusParsing', pending: 'statusPending', failed: 'statusFailed' }
    return t(lang, map[status] || 'statusPending')
  }

  const uploadNote = () => {
    if (!uploadMessage) return null
    if (uploadMessage.startsWith('uploading:')) return t(lang, 'uploadStatus', { n: uploadMessage.split(':')[1] || 0 })
    if (uploadMessage.startsWith('processing')) return t(lang, 'uploadProcessing')
    if (uploadMessage.startsWith('done:')) {
      const parts = uploadMessage.split(':')
      return t(lang, 'readyUploaded', { n: parts[1] || 0, c: parts[2] || 0 })
    }
    if (uploadMessage.startsWith('failed:')) return t(lang, 'uploadFailed', { msg: uploadMessage.slice(7) })
    if (uploadMessage === 'timeout') return t(lang, 'uploadFailed', { msg: 'timeout' })
    return null
  }

  const strategyLabel = (s) => t(lang, 'strategy_' + s)
  const presetLabel = (id) => {
    if (!id) return t(lang, 'preset_none')
    const fromApi = presets.find(p => p.id === id)?.label
    return fromApi && lang === 'zh' ? fromApi : t(lang, 'preset_' + id)
  }
  const selectedCount = selectedDocIds.size

  // Topic-scope filter: the backend /documents/categories tree is authoritative
  // and OVERRIDES any per-doc fallback — never silently collapse to ['default']
  // while a real tree is available.
  const catById = {};
  (categoryTree || []).forEach(g => (g.documents || []).forEach(d => { if (d.id != null) catById[d.id] = g.category }))
  const catOf = (d) => ((d && d.category) || catById[d && d.id] || 'default')
  const docCategories = (() => {
    const cats = []
    const push = (c) => { const k = (c && String(c)) || 'default'; if (!cats.includes(k)) cats.push(k) }
    if (categoryTree && categoryTree.length) {
      categoryTree.forEach(g => push(g.category))
    } else {
      (documents || []).forEach(d => push(catOf(d)))
    }
    return cats.length ? cats : ['default']
  })()
  const docsOfCategory = (c) => (documents || []).filter(d => catOf(d) === c)
  const isCatSelected = (c) => {
    const ds = docsOfCategory(c)
    return ds.length > 0 && ds.every(d => d.id != null && selectedDocIds.has(d.id))
  }
  const toggleCategory = (c) => {
    const ids = docsOfCategory(c).map(d => d.id).filter(Boolean)
    const on = isCatSelected(c)
    setSelectedDocIds(prev => {
      const next = new Set(prev)
      ids.forEach(id => (on ? next.delete(id) : next.add(id)))
      return next
    })
  }

  const navSwitcher = (
    <div className="flex items-center rounded-full bg-white/30 p-1 backdrop-blur-md border border-white/50 shadow-sm">
      <div className="relative flex items-center">
        <div 
          className="absolute inset-y-0 left-0 rounded-full bg-white shadow-sm transition-transform duration-500 ease-[cubic-bezier(0.23,1,0.32,1)]"
          style={{
            width: '33.33%',
            transform: `translateX(${navTab === 'gallery' ? '0%' : navTab === 'workspace' ? '100%' : '200%'})`
          }}
        />
        <button onClick={() => handleTabChange('gallery')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'gallery' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800'}`}>展示页</button>
        <button onClick={() => handleTabChange('workspace')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'workspace' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800'}`}>主页面</button>
        <button onClick={() => handleTabChange('dashboard')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'dashboard' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800'}`}>Dashboard</button>
      </div>
    </div>
  )

  return (
    <div 
      onMouseMove={handleMouseMove} 
      className="relative flex h-screen w-full overflow-hidden bg-gradient-to-tr from-[#68c5ff] via-[#d6b7ff] to-[#fed39f] bg-[length:200%_200%] animate-[fluid-bg_15s_ease-in-out_infinite] font-sans text-slate-800 selection:bg-orange-200 selection:text-orange-900"
    >
      <style>{`
        @keyframes fluid-bg {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
        @keyframes breathe-watermark {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50% { opacity: 0.9; transform: scale(1.03); }
        }
        .watermark-text {
          background: linear-gradient(90deg, rgba(255,255,255,0.6) 0%, rgba(255,255,255,1) 50%, rgba(255,255,255,0.6) 100%);
          background-size: 200% auto;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          animation: breathe-watermark 4s ease-in-out infinite, fluid-bg 3s linear infinite;
        }
        .watermark-text:hover {
          animation: none;
          transform: scale(1.08);
          -webkit-text-fill-color: white;
          text-shadow: 0 0 20px rgba(255,255,255,0.8);
        }
      `}</style>

      {/* 鼠标物理视差背景光晕 */}
      <div 
        className="pointer-events-none absolute -top-40 -left-40 h-[45rem] w-[45rem] rounded-full bg-sky-300/35 blur-[120px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${mousePos.x * 1.5}px, ${mousePos.y * 1.5}px, 0)` }}
      />
      <div 
        className="pointer-events-none absolute -bottom-40 -right-20 h-[50rem] w-[50rem] rounded-full bg-amber-300/35 blur-[140px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${-mousePos.x * 1.8}px, ${-mousePos.y * 1.8}px, 0)` }}
      />
      <div 
        className="pointer-events-none absolute top-1/3 left-1/3 h-[35rem] w-[35rem] rounded-full bg-purple-300/25 blur-[130px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${mousePos.x * 0.8}px, ${mousePos.y * 0.8}px, 0)` }}
      />

      <div 
        className="pointer-events-none fixed rounded-full bg-white/40 blur-[100px] transition-all duration-500 ease-out mix-blend-overlay z-0"
        style={{
          width: '800px',
          height: '800px',
          left: mousePos.cx !== -999 ? mousePos.cx - 400 : -999,
          top: mousePos.cy !== -999 ? mousePos.cy - 400 : -999,
        }}
      />

      {/* 全局水印 */}
      <div className="fixed bottom-6 right-6 z-50 pointer-events-none">
        <div className="watermark-text font-black text-3xl tracking-widest transition-all duration-300 pointer-events-auto cursor-default">
          MOBILITEEE
        </div>
      </div>

      <div 
        className={`absolute inset-0 w-full h-full transition-all duration-400 ease-in-out ${
          isFading ? 'opacity-0 scale-[0.98] blur-[2px]' : 'opacity-100 scale-100 blur-0'
        }`}
      >
        {!entered && (
          <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50">
            {navSwitcher}
          </div>
        )}

        {!entered ? (
          <div className="relative z-20 flex h-full w-full flex-col items-center justify-center p-6 md:p-10">
            <div className="flex max-w-4xl flex-col items-center text-center">
              <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-white/40 bg-white/10 px-4 py-1.5 text-[10px] font-black uppercase tracking-widest text-white backdrop-blur-md shadow-sm">
                <span className="h-2 w-2 animate-pulse rounded-full bg-orange-400" />
                Next-Gen RAG Architecture
              </div>

              <h1 className="font-serif text-5xl font-bold tracking-tight text-white drop-shadow-lg sm:text-6xl md:text-7xl">
                {lang === 'zh' ? 'Lumina 智能知识引擎' : 'Lumina Knowledge Engine'}
              </h1>
              <h2 className="mt-3 font-serif text-xl font-medium tracking-widest text-white/80 drop-shadow-md">
                {lang === 'zh' ? 'LUMINA KNOWLEDGE ENGINE' : 'LUMINA 智能知识引擎'}
              </h2>

              <p className="mt-8 max-w-2xl text-sm font-medium leading-relaxed text-white/90 drop-shadow-sm md:text-base bg-white/5 p-6 rounded-3xl border border-white/10 backdrop-blur-sm shadow-xl">
                基于前沿 RAG (检索增强生成) 架构的下一代知识工作台。深度融合混合检索与父子切片技术，赋予枯燥数据以生命，让每一次知识溯源都精准、优雅、清晰。
                <br/><br/>
                <span className="text-white/70 text-xs">
                  A next-generation workspace powered by advanced RAG architecture. Merging hybrid retrieval with parent-child chunking to breathe life into data, making every knowledge query precise, elegant, and traceable.
                </span>
              </p>

              <button 
                type="button" 
                onClick={() => handleTabChange('workspace')} 
                className="group mt-10 flex items-center gap-3 rounded-full bg-white/95 px-8 py-4 text-sm font-extrabold text-slate-800 shadow-[0_20px_40px_rgba(0,0,0,0.1)] backdrop-blur-xl transition-all duration-300 hover:scale-105 hover:bg-white hover:shadow-[0_25px_50px_rgba(0,0,0,0.18)] active:scale-95"
              >
                <span>Enter Workspace</span>
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </button>
            </div>
          </div>
        ) : (
        <div className="relative z-10 flex h-full w-full p-4 gap-4 overflow-hidden">
          
          <aside className="hidden w-[290px] shrink-0 flex-col rounded-[2rem] border border-white/70 bg-white/60 p-5 shadow-[0_8px_32px_rgba(31,38,135,0.06)] backdrop-blur-2xl md:flex min-h-0 overflow-hidden">
            
            <button type="button" onClick={openProfileModal} className="group mb-4 flex w-full items-center gap-3 rounded-2xl bg-white/80 p-2.5 pr-3 text-left shadow-xs transition-all hover:bg-white hover:shadow-md shrink-0">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-orange-100 text-orange-600 shadow-inner">
                <User className="h-4 w-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-extrabold text-slate-800">{profile.name}</span>
                <span className="block text-[10px] font-bold text-slate-400">UID #{profile.userId}</span>
              </span>
            </button>

            <button type="button" onClick={newConversation} className="mb-4 flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-900 py-3 text-xs font-extrabold text-white shadow-md transition-all hover:bg-slate-800 hover:shadow-lg active:scale-95 shrink-0">
              <Sparkles className="h-3.5 w-3.5 text-amber-300" /> {t(lang, 'newSession')}
            </button>

            <div className="mb-2 flex items-center justify-between px-1 shrink-0">
              <div className="flex items-center gap-2 text-slate-800">
                <BookOpen className="h-4 w-4 text-orange-500" />
                <h2 className="text-xs font-extrabold tracking-wide">{t(lang, 'knowledgeBase')}</h2>
              </div>
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading} className="rounded-full bg-white p-1.5 text-slate-500 shadow-xs hover:text-orange-600 hover:shadow-md transition-all disabled:opacity-50" aria-label={t(lang, 'uploadDocs')} title={t(lang, 'uploadDocs')}>
                {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              </button>
            </div>
            <input ref={fileInputRef} type="file" accept=".md,.pdf,.docx" multiple className="hidden" onChange={handleUpload} />

            <p className="mb-2.5 px-1 text-[10px] font-bold uppercase tracking-wide text-slate-400 shrink-0">{modeLabel(kbMode)} · {t(lang, 'documentCount', { n: documents.length })}</p>
            
            {documents.length > 0 && (
              <div className="mb-2 flex items-center gap-2 px-1 text-[10px] font-bold text-slate-400 shrink-0">
                <button type="button" onClick={() => setSelectedDocIds(new Set(documents.map(d => d.id).filter(Boolean)))} className="hover:text-orange-600 transition-colors">{t(lang, 'selectAll')}</button>
                <span>/</span>
                <button type="button" onClick={() => setSelectedDocIds(new Set())} className="hover:text-slate-600 transition-colors">{t(lang, 'clearSelection')}</button>
                <span className="ml-auto rounded-full bg-white/70 px-2 py-0.5 text-slate-600 shadow-xs">{selectedCount}</span>
              </div>
            )}

            {docCategories.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-1.5 px-1">
                <button
                  type="button"
                  onClick={() => setSelectedDocIds(new Set())}
                  className={selectedCount === 0
                    ? 'rounded-full border border-orange-300 bg-orange-50 px-2 py-0.5 text-[10px] font-bold text-orange-600'
                    : 'rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-500 transition-colors hover:border-orange-300 hover:text-orange-600'}
                >
                  {t(lang, 'categoryAll')}
                </button>
                {docCategories.map(c => {
                  const on = isCatSelected(c)
                  return (
                    <button
                      key={c}
                      type="button"
                      onClick={() => toggleCategory(c)}
                      className={on
                        ? 'rounded-full border border-orange-500 bg-orange-500 px-2 py-0.5 text-[10px] font-bold text-white'
                        : 'rounded-full border border-slate-200 px-2 py-0.5 text-[10px] font-bold text-slate-500 transition-colors hover:border-orange-300 hover:text-orange-600'}
                    >
                      {c === 'default' ? t(lang, 'categoryDefault') : c}
                    </button>
                  )
                })}
              </div>
            )}

            <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
              {docLoading && <div className="flex items-center gap-2 px-1 py-2 text-xs font-bold text-slate-400"><Loader2 className="h-3.5 w-3.5 animate-spin text-orange-500" />{t(lang, 'loadingDocs')}</div>}
              {!docLoading && documents.length === 0 && <div className="rounded-2xl bg-white/40 p-4 text-center text-xs font-bold text-slate-400">{t(lang, 'noDocuments')}</div>}
              {documents.map((doc, index) => (
                <div key={doc.id != null ? `doc-${doc.id}` : `${doc.filename}-${index}`} className="group flex items-start gap-2.5 rounded-2xl bg-white/50 p-2.5 shadow-xs transition-all hover:bg-white hover:shadow-md">
                  <button type="button" aria-label="select" onClick={() => {
                    setSelectedDocIds(prev => { const next = new Set(prev); next.has(doc.id) ? next.delete(doc.id) : next.add(doc.id); return next })
                  }} className="mt-0.5 shrink-0">
                    {doc.id != null && selectedDocIds.has(doc.id) ? <CheckSquare className="h-4 w-4 text-orange-500" /> : <Square className="h-4 w-4 text-slate-300 group-hover:text-orange-300" />}
                  </button>
                  <button type="button" onClick={() => openDocument(doc)} className="min-w-0 flex-1 text-left">
                    <div className="truncate text-xs font-extrabold text-slate-700 group-hover:text-orange-600 transition-colors">{doc.filename}</div>
                    <div className="mt-0.5 text-[9.5px] font-bold text-slate-400">{t(lang, 'chunkCount', { n: doc.chunk_count })} · <span className={doc.status === 'failed' ? 'text-rose-600' : doc.status === 'ready' ? 'text-emerald-600' : 'text-amber-600'}>{statusLabel(doc.status)}</span></div>
                  </button>
                </div>
              ))}
            </div>

            {conversations.length > 0 && (
              <div className="mt-3 max-h-40 min-h-0 shrink-0 overflow-y-auto border-t border-white/60 pt-2.5 pr-1">
                <div className="mb-1.5 flex items-center justify-between px-1">
                  <span className="text-[9.5px] font-extrabold uppercase tracking-widest text-slate-400">{t(lang, 'sessionHistory')}</span>
                  {conversationLoading && <Loader2 className="h-3 w-3 animate-spin text-orange-500" />}
                </div>
                <div className="space-y-1">
                  {conversations.map(conv => (
                    <div key={conv.id} onClick={() => openConversation(conv)} className={`group flex cursor-pointer items-center gap-1.5 rounded-xl p-2 transition-all ${activeConversationId === conv.id ? 'bg-white shadow-sm' : 'bg-transparent hover:bg-white/50'}`}>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-bold text-slate-700">{conv.title}</div>
                        <div className="text-[9px] font-medium text-slate-400">{conv.message_count} msgs · {formatSessionTime(conv.updated_at || conv.created_at)}</div>
                      </div>
                      <button type="button" onClick={(e) => removeConversation(conv, e)} className="shrink-0 p-1 text-slate-300 opacity-0 transition-all hover:text-rose-600 group-hover:opacity-100" aria-label="Delete">
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {uploadNote() && <div className="mt-2 shrink-0 rounded-xl bg-orange-50/80 p-2 text-[10px] font-medium leading-tight text-orange-800">{uploadNote()}</div>}
          </aside>

          <section className="flex min-w-0 min-h-0 flex-1 flex-col rounded-[2.5rem] border border-white/70 bg-white/50 shadow-[0_8px_32px_rgba(31,38,135,0.06)] backdrop-blur-2xl overflow-hidden">
            
            <header className="flex flex-col md:flex-row items-center justify-between px-6 py-4 border-b border-white/50 gap-4 shrink-0">
              <div className="flex-shrink-0">
                <div className="flex items-center gap-2">
                  <h1 className="font-serif text-lg font-bold tracking-tight text-slate-900">{t(lang, 'productName')}</h1>
                  <span className="hidden sm:inline-block rounded-full bg-orange-100/80 px-2 py-0.5 text-[9.5px] font-black text-orange-600">Lumina Engine</span>
                </div>
                <p className="mt-0.5 text-[11px] font-medium text-slate-500 hidden sm:block">{selectedCount > 0 ? t(lang, 'queryingDocs', { a: selectedCount, b: documents.length }) : t(lang, 'noDocsQuery')}</p>
              </div>

              <div className="flex-shrink-0 hidden lg:block">
                {navSwitcher}
              </div>

              <div className="flex items-center gap-2.5 flex-shrink-0">
                <GuideModal lang={lang} />
                <button type="button" onClick={toggleLang} className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-slate-600 shadow-xs hover:bg-white transition-all">{lang === 'zh' ? '中 / EN' : 'EN / 中'}</button>
                <button type="button" onClick={clearChat} className="flex items-center gap-1 rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-slate-600 shadow-xs hover:bg-rose-50 hover:text-rose-600 transition-all"><Trash2 className="h-3 w-3" />{t(lang, 'newChat')}</button>
                <button type="button" onClick={() => setIsDrawerOpen(prev => !prev)} className="rounded-full bg-white/80 px-3 py-1.5 text-xs font-bold text-slate-600 shadow-xs hover:bg-white transition-all">
                  {isDrawerOpen ? t(lang, 'hideSidebar') : t(lang, 'showSidebar')}
                </button>
              </div>
            </header>

            <main ref={chatContainerRef} className="flex-1 space-y-6 overflow-y-auto p-6 md:p-8">
              {messages.length === 0 && (
                <div className="mx-auto flex h-full max-w-2xl flex-col items-center justify-center text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-3xl bg-white/80 shadow-md shadow-orange-500/10 backdrop-blur-md">
                    <BookOpen className="h-7 w-7 text-orange-500" />
                  </div>
                  <h2 className="mb-2 font-serif text-3xl font-normal text-slate-900 tracking-tight">{t(lang, 'productName')}</h2>
                  <p className="mb-8 max-w-md text-xs font-medium text-slate-500 leading-relaxed">{documents.length ? t(lang, 'startTitle') : t(lang, 'noDocumentsHint')}</p>
                  
                  <div className="grid w-full gap-3.5 sm:grid-cols-3">
                    {[1, 2, 3].map(n => (
                      <button key={n} type="button" onClick={() => ask(t(lang, 'starter' + n), n === 3 ? 'prd_review' : null)} className="group rounded-[1.8rem] border border-white/80 bg-white/70 p-4 text-left shadow-[0_4px_20px_rgba(0,0,0,0.03)] backdrop-blur-md transition-all duration-300 hover:-translate-y-1 hover:bg-white hover:shadow-lg">
                        <span className="mb-2 inline-block rounded-full bg-orange-100/70 px-2.5 py-0.5 text-[9.5px] font-black uppercase tracking-wider text-orange-600 group-hover:bg-orange-500 group-hover:text-white transition-colors">{t(lang, 'quickStartLabel')} {n}</span>
                        <span className="line-clamp-3 text-xs font-bold leading-relaxed text-slate-700">{t(lang, 'starter' + n)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={msg.id || i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-[2rem] p-5 shadow-sm ${msg.role === 'user' ? 'bg-slate-900 text-white rounded-tr-sm shadow-md' : 'border border-white/80 bg-white/85 backdrop-blur-xl text-slate-800 rounded-tl-sm'}`}>
                    {msg.role === 'user' ? (
                      <div className="whitespace-pre-wrap break-words text-sm font-medium leading-relaxed">{msg.content}</div>
                    ) : (
                      <div className="prose prose-stone prose-sm max-w-none break-words text-[14.5px] font-medium leading-relaxed">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm]}
                          components={{
                            a: ({ node, ...props }) => {
                              const href = props.href || ''
                              if (href.startsWith('#cite-')) {
                                const num = Number(href.replace('#cite-', ''))
                                return (
                                  <button
                                    type="button"
                                    onClick={() => handleCitation(msg, num)}
                                    className="mx-0.5 inline-flex items-center justify-center rounded-full bg-orange-100 border border-orange-200/80 px-2 py-0.2 font-mono text-[11px] font-bold text-orange-600 shadow-xs hover:bg-orange-500 hover:text-white transition-all"
                                  >
                                    [{num}]
                                  </button>
                                )
                              }
                              return <a {...props} className="font-bold text-orange-600 underline underline-offset-4 decoration-orange-300 hover:decoration-orange-600" />
                            },
                          }}
                        >
                          {enhanceCitations(msg.content)}
                        </ReactMarkdown>

                        {msg.meta && (
                          <div className="mt-4 border-t border-slate-100 pt-2.5 text-[10px] font-mono text-slate-400 uppercase tracking-tight">
                            {msg.meta.refusal ? t(lang, 'refusalBadge', { ms: msg.meta.latency_ms || 0 }) : t(lang, 'performance', { ret: msg.meta.retrieve_ms || 0, ttft: msg.meta.first_token_ms || 0, tokens: msg.meta.total_tokens || 0 })}
                          </div>
                        )}

                        <div className={`mt-2 flex items-center gap-1.5 ${!msg.meta ? 'border-t border-slate-100 pt-2' : ''}`}>
                          <button type="button" onClick={() => submitRating(msg, 1)} className={`rounded-full p-1.5 transition-colors ${feedbackByMsg[msg.id]?.thumbs === 1 ? 'bg-green-100 text-green-600' : 'text-slate-300 hover:text-slate-600'}`} aria-label={t(lang, 'good')}><ThumbsUp className="h-3.5 w-3.5" /></button>
                          <button type="button" onClick={() => submitRating(msg, -1, feedbackByMsg[msg.id]?.thumbs === -1 ? feedbackByMsg[msg.id].reasons || [] : [])} className={`rounded-full p-1.5 transition-colors ${feedbackByMsg[msg.id]?.thumbs === -1 ? 'bg-rose-100 text-rose-600' : 'text-slate-300 hover:text-rose-600'}`} aria-label={t(lang, 'bad')}><ThumbsDown className="h-3.5 w-3.5" /></button>
                          {feedbackByMsg[msg.id]?.thumbs === -1 && !feedbackByMsg[msg.id].reasons?.length && <span className="text-[10px] font-bold text-slate-400">{t(lang, 'feedbackReason')}</span>}
                        </div>

                        {feedbackByMsg[msg.id]?.thumbs === -1 && !feedbackByMsg[msg.id].reasons?.length && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {REASON_IDS.map(id => <button key={id} type="button" onClick={() => submitRating(msg, -1, [id])} className="rounded-full bg-rose-50 border border-rose-200/60 px-2.5 py-0.5 text-[10px] font-bold text-rose-600 hover:bg-rose-100">{t(lang, 'reason_' + id)}</button>)}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {isLoading && messages[messages.length - 1]?.role === 'user' && (
                <div className="flex justify-start">
                  <div className="rounded-[2rem] border border-white/80 bg-white/80 p-4 shadow-sm backdrop-blur-md text-xs font-bold text-slate-500 flex items-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-orange-500" />
                    <span>Searching Chunks & Generating Response...</span>
                  </div>
                </div>
              )}
            </main>
            
            <footer className="p-4 px-6 border-t border-white/50 shrink-0">
              <div className="mx-auto max-w-3xl">
                
                <div className="mb-2.5 flex flex-wrap items-center gap-1.5 text-xs">
                  <div className="flex items-center rounded-full bg-white/60 p-1 shadow-xs backdrop-blur-md">
                    {strategies.map(s => (
                      <button key={s} type="button" onClick={() => setStrategy(s)} className={`rounded-full px-3 py-1 text-[11px] font-bold transition-all ${strategy === s ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}>{strategyLabel(s)}</button>
                    ))}
                  </div>
                  <span className="text-slate-300">|</span>
                  <button type="button" onClick={() => setActivePreset(null)} className={`rounded-full px-3 py-1 text-[11px] font-bold transition-all ${!activePreset ? 'bg-slate-900 text-white shadow-xs' : 'bg-white/60 text-slate-600 hover:bg-white'}`}>{t(lang, 'preset_none')}</button>
                  {presets.map(p => (
                    <button key={p.id} type="button" onClick={() => setActivePreset(activePreset === p.id ? null : p.id)} className={`rounded-full px-3 py-1 text-[11px] font-bold transition-all ${activePreset === p.id ? 'bg-slate-900 text-white shadow-xs' : 'bg-white/60 text-slate-600 hover:bg-white'}`}>{presetLabel(p.id)}</button>
                  ))}
                </div>

                <form onSubmit={handleSubmit} className="flex gap-2 rounded-full bg-white/90 p-1.5 shadow-[0_8px_30px_rgba(0,0,0,0.06)] backdrop-blur-xl focus-within:shadow-lg focus-within:ring-2 focus-within:ring-orange-200 transition-all">
                  <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder={t(lang, 'inputPlaceholder')} disabled={isLoading} className="flex-1 rounded-full bg-transparent px-5 py-3 text-sm font-medium text-slate-800 placeholder:text-slate-400 focus:outline-none disabled:opacity-50" />
                  <button type="submit" disabled={isLoading || !input.trim()} className="flex shrink-0 items-center justify-center rounded-full bg-orange-500 px-5 text-white shadow-md transition-all hover:bg-orange-400 hover:scale-105 active:scale-95 disabled:opacity-30">
                    {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </button>
                </form>
              </div>
            </footer>
          </section>

          {isDrawerOpen && (
            <aside className="hidden w-[310px] shrink-0 flex-col rounded-[2rem] border border-white/70 bg-white/60 p-5 shadow-[0_8px_32px_rgba(31,38,135,0.06)] backdrop-blur-2xl md:flex min-h-0 overflow-hidden">
              <div className="flex items-center justify-between border-b border-white/60 pb-3 mb-3 shrink-0">
                <div className="flex rounded-full bg-white/70 p-1 shadow-xs">
                  <button type="button" onClick={() => setRightTab('sources')} className={`rounded-full px-3 py-1 text-[11px] font-bold transition-all ${rightTab === 'sources' ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}><BookOpen className="mr-1 inline h-3 w-3" />{t(lang, 'sources')}</button>
                  <button type="button" onClick={() => setRightTab('viewer')} className={`rounded-full px-3 py-1 text-[11px] font-bold transition-all ${rightTab === 'viewer' ? 'bg-slate-900 text-white shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}><FileText className="mr-1 inline h-3 w-3" />{t(lang, 'documentViewer')}</button>
                </div>
                <button type="button" onClick={() => setIsDrawerOpen(false)} className="rounded-full p-1.5 text-slate-400 hover:bg-white hover:text-slate-700 transition-all"><X className="h-4 w-4" /></button>
              </div>
              
              <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                {rightTab === 'sources' && (
                  <div className="space-y-3">
                    {sources.length === 0 && <div className="rounded-2xl bg-white/40 p-6 text-center text-xs font-bold text-slate-400">{t(lang, 'noSources')}</div>}
                    {sources.map((source, idx) => (
                      <div key={idx} className="rounded-2xl border border-white/80 bg-white/70 p-3.5 shadow-xs transition-all hover:bg-white hover:shadow-md">
                        <div className="mb-1 truncate text-[11px] font-black text-slate-800">
                          <span className="mr-1.5 rounded-full bg-orange-100 px-1.5 py-0.2 text-orange-600 font-mono">#{idx + 1}</span>
                          {source.source}
                        </div>
                        <p className="mb-2 line-clamp-3 text-xs leading-relaxed text-slate-600 font-medium">{source.excerpt}</p>
                        <div className="flex items-center justify-between border-t border-slate-100 pt-2 text-[10px] font-mono">
                          <span className="font-bold text-orange-600">{Math.round((source.score || 0) * 100)}% Match</span>
                          <button type="button" onClick={() => locateSource(source)} className="font-bold text-slate-400 hover:text-orange-600 hover:underline transition-colors">{t(lang, 'locateOriginal')}</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {rightTab === 'viewer' && (
                  <div>
                    {viewerLoading && <div className="flex items-center justify-center py-6 text-xs font-bold text-slate-400"><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin text-orange-500" />{t(lang, 'loadingViewer')}</div>}
                    {!viewerLoading && !viewerDoc && <div className="rounded-2xl bg-white/40 p-6 text-center text-xs font-bold text-slate-400">{t(lang, 'chooseDocument')}</div>}
                    {!viewerLoading && viewerDoc && (
                      <div className="rounded-2xl border border-white/80 bg-white/80 p-4 shadow-xs">
                        <h3 className="mb-2 border-b border-slate-100 pb-2 text-xs font-extrabold text-slate-900">{viewerDoc.filename}</h3>
                        <div className="prose prose-stone prose-sm max-w-none text-xs leading-relaxed">
                          <Markdown content={viewerDoc.content || ''} highlightText={highlightText} onCitationClick={null} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </aside>
          )}
        </div>
        )}
      </div>

      {/* 用户设置弹窗 */}
      {profileOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/30 p-4 backdrop-blur-md">
          <div className="w-full max-w-sm rounded-[2.5rem] border border-white/80 bg-white/95 p-6 shadow-2xl backdrop-blur-2xl">
            <div className="mb-4 flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="font-serif text-base font-bold tracking-tight text-slate-900">{t(lang, 'profileTitle')}</h3>
              <button type="button" onClick={() => setProfileOpen(false)} className="rounded-full p-1 text-slate-400 hover:bg-slate-100"><X className="h-4 w-4" /></button>
            </div>
            
            <label className="mb-1 block text-[10px] font-extrabold uppercase text-slate-400">{t(lang, 'nickname')}</label>
            <input className="mb-3 w-full rounded-xl bg-slate-50 p-2.5 text-xs font-bold text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-200" value={profileDraft?.name || ''} onChange={e => setProfileDraft({ ...profileDraft, name: e.target.value })} placeholder="Guest_01" />
            
            <label className="mb-1 block text-[10px] font-extrabold uppercase text-slate-400">{t(lang, 'apiKey')}</label>
            <input type="password" className="mb-3 w-full rounded-xl bg-slate-50 p-2.5 text-xs font-mono text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-200" value={profileDraft?.apiKey || ''} onChange={e => setProfileDraft({ ...profileDraft, apiKey: e.target.value })} placeholder="sk-..." />
            
            <label className="mb-1 block text-[10px] font-extrabold uppercase text-slate-400">{t(lang, 'baseUrl')}</label>
            <input className="mb-3 w-full rounded-xl bg-slate-50 p-2.5 text-xs font-mono text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-200" value={profileDraft?.baseUrl || ''} onChange={e => setProfileDraft({ ...profileDraft, baseUrl: e.target.value })} placeholder="https://api.openai.com/v1" />
            
            <label className="mb-1 block text-[10px] font-extrabold uppercase text-slate-400">{t(lang, 'model')}</label>
            <input className="mb-5 w-full rounded-xl bg-slate-50 p-2.5 text-xs font-mono text-slate-800 focus:bg-white focus:outline-none focus:ring-2 focus:ring-orange-200" value={profileDraft?.model || ''} onChange={e => setProfileDraft({ ...profileDraft, model: e.target.value })} placeholder="gpt-4o-mini" />
            
            <div className="flex gap-2">
              <button type="button" onClick={saveProfile} className="flex-1 rounded-full bg-slate-900 py-2.5 text-xs font-extrabold text-white shadow-md hover:bg-slate-800 transition-all">{t(lang, 'saveProfile')}</button>
              <button type="button" onClick={resetProfile} className="flex-1 rounded-full bg-slate-100 py-2.5 text-xs font-extrabold text-slate-600 hover:bg-slate-200 transition-all">{t(lang, 'logout')}</button>
            </div>
            
            <p className="mt-4 text-center font-mono text-[9px] text-slate-400">{t(lang, 'profile')}: #{profile.userId} · {t(lang, 'language')}: {lang.toUpperCase()}</p>
          </div>
        </div>
      )}
    </div>
  )
}
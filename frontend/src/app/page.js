'use client'

import { useState, useEffect, useRef } from 'react'
import { Send, Loader2, BookOpen, X, Upload, FileText, CheckSquare, Square, ChevronRight, ChevronLeft, ThumbsUp, ThumbsDown, BarChart3, User, Trash2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import Markdown from '../components/Markdown'
import { t, resolveLang } from '../lib/i18n'
import { streamQuery, streamSSE, listDocuments, getDocumentCategories, uploadDocuments, getTaskStatus, getRetrievalConfig, submitFeedback, getDocumentContent, getConversations, createConversation, getConversationMessages, deleteConversation } from '../lib/api'
import GuideModal from '../components/GuideModal'


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

function removeLocal(key) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.removeItem(key); } catch (err) {}
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
  const messagesEndRef = useRef(null)

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
    if (Array.isArray(restored) && restored.length) setMessages(restored);
    if (Array.isArray(restoredSources) && restoredSources.length) {
      setSources(restoredSources);
      showDrawer('sources');
    }
  }, [profile.userId])

  useEffect(() => {
    if (!profile.userId) return;
    writeLocal(STORAGE_KEYS.chatPrefix + profile.userId, messages)
  }, [messages, profile.userId])

  useEffect(() => {
    if (!profile.userId) return;
    writeLocal(STORAGE_KEYS.sourcesPrefix + profile.userId, sources)
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

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (viewerDoc?.content && highlightText) {
      const timer = setTimeout(() => {
        const el = document.querySelector('.rag-highlight');
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
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
    setMessages([])
    setSources([])
    setShowSourcesPanel(false)
  }

  const resetProfile = () => {
    const next = { name: 'Guest_01', userId: 1, apiKey: '', baseUrl: '', model: '' }
    setProfile(next)
    writeLocal(STORAGE_KEYS.profile, next)
    setProfileOpen(false)
    setMessages([])
    setSources([])
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

  const tr = (key, vars) => t(lang, key, vars)

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

  return (
    <div className="flex h-screen bg-gray-50">

      <aside className="hidden w-72 shrink-0 flex-col border-r bg-white p-4 md:flex">
        <button type="button" onClick={openProfileModal} className="mb-3 flex w-full items-center gap-2 rounded-lg border border-gray-200 px-2.5 py-2 text-left hover:bg-gray-50">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700"><User className="h-4 w-4" /></span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold text-gray-800">{profile.name}</span>
            <span className="block text-[11px] text-gray-400">{t(lang, 'profile')} #{profile.userId}</span>
          </span>
        </button>
        <button type="button" onClick={newConversation} className="mb-3 flex w-full items-center justify-center gap-1 rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-blue-50 hover:text-blue-700">
          <span className="text-base leading-none">+</span> {t(lang, 'newSession')}
        </button>

        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-blue-600" />
            <h2 className="font-semibold text-gray-800">{t(lang, 'knowledgeBase')}</h2>
          </div>
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={uploading} className="rounded p-1.5 text-gray-500 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50" aria-label={t(lang, 'uploadDocs')} title={t(lang, 'uploadDocs')}>
            {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          </button>
        </div>
        <input ref={fileInputRef} type="file" accept=".md,.pdf,.docx" multiple className="hidden" onChange={handleUpload} />

        <p className="mb-2 text-xs text-gray-400">{modeLabel(kbMode)} · {t(lang, 'documentCount', { n: documents.length })}</p>
        {documents.length > 0 && (
          <div className="mb-2 flex items-center gap-2 text-xs">
            <button type="button" onClick={() => setSelectedDocIds(new Set(documents.map(d => d.id).filter(Boolean)))} className="text-blue-600 hover:underline">{t(lang, 'selectAll')}</button>
            <button type="button" onClick={() => setSelectedDocIds(new Set())} className="text-gray-500 hover:underline">{t(lang, 'clearSelection')}</button>
            <span className="ml-auto text-gray-400">{t(lang, 'selectedCount', { n: selectedCount })}</span>
          </div>
        )}

        {docCategories.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setSelectedDocIds(new Set())}
              className={selectedCount === 0
                ? 'rounded-full border border-blue-300 bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700'
                : 'rounded-full border border-gray-200 px-2 py-0.5 text-[11px] font-medium text-gray-500 hover:border-blue-300 hover:text-blue-600'}
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
                    ? 'rounded-full border border-blue-600 bg-blue-600 px-2 py-0.5 text-[11px] font-medium text-white'
                    : 'rounded-full border border-gray-200 px-2 py-0.5 text-[11px] font-medium text-gray-500 hover:border-blue-300 hover:text-blue-600'}
                >
                  {c === 'default' ? t(lang, 'categoryDefault') : c}
                </button>
              )
            })}
          </div>
        )}

        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {docLoading && <div className="flex items-center gap-2 text-sm text-gray-400"><Loader2 className="h-4 w-4 animate-spin" />{t(lang, 'loadingDocs')}</div>}
          {!docLoading && documents.length === 0 && <div className="p-2 text-sm text-gray-400">{t(lang, 'noDocuments')}</div>}
          {documents.map((doc, index) => (
            <div key={doc.id != null ? `doc-${doc.id}` : `${doc.filename}-${index}`} className="group flex items-start gap-1.5 rounded p-1.5 hover:bg-gray-50">
              <button type="button" aria-label="select" onClick={() => {
                setSelectedDocIds(prev => { const next = new Set(prev); next.has(doc.id) ? next.delete(doc.id) : next.add(doc.id); return next })
              }} className="mt-0.5 shrink-0">
                {doc.id != null && selectedDocIds.has(doc.id) ? <CheckSquare className="h-4 w-4 text-blue-600" /> : <Square className="h-4 w-4 text-gray-400" />}
              </button>
              <button type="button" onClick={() => openDocument(doc)} className="min-w-0 flex-1 text-left">
                <div className="truncate text-sm text-gray-700 group-hover:text-blue-700">{doc.filename}</div>
                <div className="text-xs text-gray-400">{t(lang, 'chunkCount', { n: doc.chunk_count })} · <span className={doc.status === 'failed' ? 'text-red-500' : doc.status === 'ready' ? 'text-green-500' : 'text-yellow-500'}>{statusLabel(doc.status)}</span></div>
              </button>
            </div>
          ))}
        </div>
        {conversations.length > 0 && (
          <div className="mt-3 max-h-44 min-h-0 overflow-y-auto border-t pt-2">
            <div className="mb-1 flex items-center justify-between px-1">
              <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400">{t(lang, 'sessionHistory')}</span>
              {conversationLoading && <Loader2 className="h-3 w-3 animate-spin text-gray-400" />}
            </div>
            <div className="space-y-0.5">
              {conversations.map(conv => (
                <div key={conv.id} onClick={() => openConversation(conv)} className={`group flex cursor-pointer items-center gap-1 rounded px-1.5 py-1 ${activeConversationId === conv.id ? 'bg-slate-100' : 'hover:bg-gray-50'}`}>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium text-gray-700">{conv.title}</div>
                    <div className="text-[10px] text-gray-400">{conv.message_count} msg · {formatSessionTime(conv.updated_at || conv.created_at)}</div>
                  </div>
                  <button type="button" onClick={(e) => removeConversation(conv, e)} className="shrink-0 rounded p-1 text-gray-300 opacity-0 transition group-hover:opacity-100 hover:bg-red-50 hover:text-red-500" aria-label="Delete">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
        {uploadNote() && <div className="mt-3 border-t pt-3 text-xs whitespace-normal text-gray-500">{uploadNote()}</div>}
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b bg-white p-4">
          <div>
            <h1 className="text-xl font-bold text-gray-800">{t(lang, 'productName')}</h1>
            <p className="text-sm text-gray-500">{selectedCount > 0 ? t(lang, 'queryingDocs', { a: selectedCount, b: documents.length }) : t(lang, 'noDocsQuery')}</p>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={toggleLang} className="rounded-full border border-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50">{lang === 'zh' ? '中 / EN' : 'EN / 中'}</button>
            <GuideModal lang={lang} />
            <button type="button" onClick={clearChat} className="flex items-center gap-1 rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" />{t(lang, 'newChat')}</button>
            <button type="button" onClick={() => setIsDrawerOpen(prev => !prev)} className="flex items-center gap-1 rounded-full border border-gray-200 px-2.5 py-1 text-xs text-gray-600 hover:bg-blue-50 hover:text-blue-700">
              {isDrawerOpen ? t(lang, 'hideSidebar') : t(lang, 'showSidebar')}
            </button>
            <a href="/dashboard" className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm text-gray-500 transition-colors hover:bg-blue-50 hover:text-blue-700"><BarChart3 className="h-4 w-4" />{t(lang, 'dashboard')}</a>
          </div>
        </header>

        <main className="flex-1 space-y-4 overflow-y-auto p-4">
          {messages.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center py-8">
              <BookOpen className="mb-4 h-12 w-12 opacity-40" />
              <p className="mb-6 max-w-xl text-center text-sm text-gray-500">{documents.length ? t(lang, 'startTitle') : t(lang, 'noDocumentsHint')}</p>
              <div className="grid w-full max-w-2xl gap-3 sm:grid-cols-3">
                {[1, 2, 3].map(n => (
                  <button key={n} type="button" onClick={() => ask(t(lang, 'starter' + n), n === 3 ? 'prd_review' : null)} className="rounded-lg border border-gray-200 bg-white p-3 text-left text-sm text-gray-700 shadow-sm transition hover:border-blue-300 hover:shadow">
                    <span className="mb-1 block text-[11px] font-medium uppercase text-gray-400">{t(lang, 'quickStartLabel')} {n}</span>
                    <span className="line-clamp-3 leading-relaxed">{t(lang, 'starter' + n)}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={msg.id || i} className={msg.role === 'user' ? 'ml-auto max-w-[85%] rounded-lg bg-blue-600 p-3 text-white' : 'max-w-[85%] rounded-lg border border-gray-200 bg-white p-3 shadow-sm'}>
              {msg.role === 'user' ? <div className="whitespace-pre-wrap break-words">{msg.content}</div> : (
                <div className="prose prose-sm max-w-none leading-relaxed text-slate-800">
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
                              className="mx-0.5 inline-block cursor-pointer rounded bg-slate-100 px-1 py-0.5 font-mono text-xs text-slate-600 transition hover:bg-blue-100 hover:text-blue-600"
                            >
                              [{num}]
                            </button>
                          )
                        }
                        return <a {...props} className="text-blue-600 hover:underline" />
                      },
                    }}
                  >
                    {enhanceCitations(msg.content)}
                  </ReactMarkdown>
                  {msg.meta && (
                    <div className="mt-2 border-t border-gray-100 pt-1.5 text-[11px] text-gray-400">
                      {msg.meta.refusal ? t(lang, 'refusalBadge', { ms: msg.meta.latency_ms || 0 }) : t(lang, 'performance', { ret: msg.meta.retrieve_ms || 0, ttft: msg.meta.first_token_ms || 0, tokens: msg.meta.total_tokens || 0 })}
                    </div>
                  )}
                  <div className="mt-2 flex items-center gap-1 border-t border-gray-100 pt-1.5">
                    <button type="button" onClick={() => submitRating(msg, 1)} className={feedbackByMsg[msg.id]?.thumbs === 1 ? 'rounded p-1 text-green-600' : 'rounded p-1 text-gray-300 hover:text-green-600'} aria-label={t(lang, 'good')}><ThumbsUp className="h-3.5 w-3.5" /></button>
                    <button type="button" onClick={() => submitRating(msg, -1, feedbackByMsg[msg.id]?.thumbs === -1 ? feedbackByMsg[msg.id].reasons || [] : [])} className={feedbackByMsg[msg.id]?.thumbs === -1 ? 'rounded p-1 text-red-600' : 'rounded p-1 text-gray-300 hover:text-red-600'} aria-label={t(lang, 'bad')}><ThumbsDown className="h-3.5 w-3.5" /></button>
                    {feedbackByMsg[msg.id]?.thumbs === -1 && !feedbackByMsg[msg.id].reasons?.length && <span className="ml-1 text-[11px] text-gray-400">{t(lang, 'feedbackReason')}</span>}
                  </div>
                  {feedbackByMsg[msg.id]?.thumbs === -1 && !feedbackByMsg[msg.id].reasons?.length && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {REASON_IDS.map(id => <button key={id} type="button" onClick={() => submitRating(msg, -1, [id])} className="rounded-full border border-red-100 bg-red-50 px-2 py-0.5 text-[11px] text-red-600 hover:bg-red-100">{t(lang, 'reason_' + id)}</button>)}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {isLoading && messages[messages.length - 1]?.role === 'user' && (
            <div className="max-w-[85%] rounded-lg border border-gray-200 bg-white p-3 shadow-sm"><Loader2 className="h-5 w-5 animate-spin text-gray-400" /></div>
          )}
          <div ref={messagesEndRef} />
        </main>
        <footer className="border-t bg-white p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg bg-gray-100 p-0.5">
              {strategies.map(s => <button key={s} type="button" onClick={() => setStrategy(s)} className={`rounded px-2 py-1 text-xs transition-colors ${strategy === s ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>{strategyLabel(s)}</button>)}
            </div>
            <div className="mx-1 hidden h-4 w-px bg-gray-200 sm:block" />
            <button type="button" onClick={() => setActivePreset(null)} className={`rounded-md px-2 py-1 text-xs ${!activePreset ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-blue-50'}`}>{t(lang, 'preset_none')}</button>
            {presets.map(p => <button key={p.id} type="button" onClick={() => setActivePreset(activePreset === p.id ? null : p.id)} className={`rounded-md px-2 py-1 text-xs ${activePreset === p.id ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-blue-50'}`}>{presetLabel(p.id)}</button>)}
          </div>
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input type="text" value={input} onChange={(e) => setInput(e.target.value)} placeholder={t(lang, 'inputPlaceholder')} disabled={isLoading} className="flex-1 rounded-lg border border-gray-300 p-2.5 text-gray-800 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <button type="submit" disabled={isLoading || !input.trim()} className="rounded-lg bg-blue-600 p-2.5 text-white transition-colors hover:bg-blue-700 disabled:opacity-50">{isLoading ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}</button>
          </form>
        </footer>
      </section>

      {isDrawerOpen && (
        <aside className="hidden w-80 shrink-0 flex-col border-l bg-white md:flex">
          <div className="flex items-center justify-between border-b px-3 py-2.5">
            <div className="flex gap-1 rounded-lg bg-gray-100 p-0.5">
              <button type="button" onClick={() => setRightTab('sources')} className={`rounded px-2 py-1 text-xs ${rightTab === 'sources' ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-gray-500'}`}><BookOpen className="mr-1 inline h-3.5 w-3.5" />{t(lang, 'sources')}</button>
              <button type="button" onClick={() => setRightTab('viewer')} className={`rounded px-2 py-1 text-xs ${rightTab === 'viewer' ? 'bg-white font-medium text-blue-700 shadow-sm' : 'text-gray-500'}`}><FileText className="mr-1 inline h-3.5 w-3.5" />{t(lang, 'documentViewer')}</button>
            </div>
            <button type="button" onClick={() => setIsDrawerOpen(false)} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-3">
            {rightTab === 'sources' && (
              <div className="space-y-3">
                {sources.length === 0 && <div className="p-3 text-sm text-gray-400">{t(lang, 'noSources')}</div>}
                {sources.map((source, idx) => (
                  <div key={idx} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                    <div className="mb-1 truncate font-mono text-xs font-medium text-gray-700">{source.source}</div>
                    <p className="mb-1 line-clamp-3 text-xs text-gray-600">{source.excerpt}</p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-blue-600">{Math.round((source.score || 0) * 100)}%</span>
                      <button type="button" onClick={() => locateSource(source)} className="rounded px-1.5 py-0.5 text-[11px] text-gray-500 hover:bg-blue-50 hover:text-blue-700">{t(lang, 'locateOriginal')}</button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {rightTab === 'viewer' && (
              <div>
                {viewerLoading && <div className="p-3 text-sm text-gray-400">{t(lang, 'loadingViewer')}</div>}
                {!viewerLoading && !viewerDoc && <div className="p-3 text-sm text-gray-400">{t(lang, 'chooseDocument')}</div>}
                {!viewerLoading && viewerDoc && (
                  <div>
                    <h3 className="mb-2 border-b pb-2 text-sm font-semibold text-gray-800">{viewerDoc.filename}</h3>
                    <Markdown content={viewerDoc.content || ''} highlightText={highlightText} onCitationClick={null} />
                  </div>
                )}
              </div>
            )}
          </div>
        </aside>
      )}

      {profileOpen && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4">
          <div className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-5 shadow-lg">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold text-gray-800">{t(lang, 'profileTitle')}</h3>
              <button type="button" onClick={() => setProfileOpen(false)} className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></button>
            </div>
            <label className="mb-1 block text-xs text-gray-500">{t(lang, 'nickname')}</label>
            <input className="mb-3 w-full rounded-lg border border-gray-300 p-2 text-sm" value={profileDraft?.name || ''} onChange={e => setProfileDraft({ ...profileDraft, name: e.target.value })} placeholder="Guest_01" />
            <label className="mb-1 block text-xs text-gray-500">{t(lang, 'apiKey')}</label>
            <input type="password" className="mb-3 w-full rounded-lg border border-gray-300 p-2 text-sm" value={profileDraft?.apiKey || ''} onChange={e => setProfileDraft({ ...profileDraft, apiKey: e.target.value })} placeholder="sk-..." />
            <label className="mb-1 block text-xs text-gray-500">{t(lang, 'baseUrl')}</label>
            <input className="mb-3 w-full rounded-lg border border-gray-300 p-2 text-sm" value={profileDraft?.baseUrl || ''} onChange={e => setProfileDraft({ ...profileDraft, baseUrl: e.target.value })} placeholder="https://api.openai.com/v1" />
            <label className="mb-1 block text-xs text-gray-500">{t(lang, 'model')}</label>
            <input className="mb-4 w-full rounded-lg border border-gray-300 p-2 text-sm" value={profileDraft?.model || ''} onChange={e => setProfileDraft({ ...profileDraft, model: e.target.value })} placeholder="gpt-4o-mini" />
            <div className="flex gap-2">
              <button type="button" onClick={saveProfile} className="flex-1 rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700">{t(lang, 'saveProfile')}</button>
              <button type="button" onClick={resetProfile} className="flex-1 rounded-lg border border-gray-200 py-2 text-sm text-gray-600 hover:bg-gray-50">{t(lang, 'logout')}</button>
            </div>
            <p className="mt-3 text-[11px] text-gray-400">{t(lang, 'profile')}: {profile.userId} · {t(lang, 'language')}: {lang.toUpperCase()}</p>
          </div>
        </div>
      )}
    </div>
  )
}
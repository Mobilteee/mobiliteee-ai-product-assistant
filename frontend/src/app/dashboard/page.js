'use client'

import { useState, useEffect, useRef } from 'react'
import { 
  ArrowLeft, BarChart3, ThumbsUp, ThumbsDown, Activity, 
  FileText, Loader2, GripHorizontal, Sparkles, Zap, 
  ShieldCheck, Target, Clock, Layers
} from 'lucide-react'
import { getMetricsOverview } from '../../lib/api'
import { t, resolveLang } from '../../lib/i18n'

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lang, setLang] = useState('zh')
  const [navTab, setNavTab] = useState('dashboard')
  const [isFading, setIsFading] = useState(false) // 新增：全局渐隐渐现状态
  const [mousePos, setMousePos] = useState({ x: 0, y: 0, cx: -999, cy: -999 })

  // 拖拽悬浮按钮状态
  const [fabPos, setFabPos] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragRef = useRef(null)

  // ==========================================
  // 新增：丝滑过渡的切换逻辑
  // ==========================================
  const handleTabChange = (targetTab) => {
    if (targetTab === navTab) return;
    
    // 1. 触发渐隐动画
    setIsFading(true);
    
    // 2. 等待动画执行到一半 (300ms) 时，触发跳转
    setTimeout(() => {
      if (targetTab === 'gallery') {
        window.location.href = '/pancake?tab=gallery';
      } else if (targetTab === 'workspace') {
        window.location.href = '/pancake?tab=workspace';
      } else {
        setNavTab(targetTab);
        requestAnimationFrame(() => {
          setIsFading(false);
        });
      }
    }, 300);
  }

  const handleMouseMove = (e) => {
    // 鼠标全局视差计算
    const { innerWidth, innerHeight } = window
    const x = (e.clientX / innerWidth - 0.5) * 40
    const y = (e.clientY / innerHeight - 0.5) * 40
    setMousePos({ x, y, cx: e.clientX, cy: e.clientY })

    // FAB 拖拽逻辑
    if (isDragging && dragRef.current) {
      setFabPos({
        x: e.clientX - dragRef.current.startX,
        y: e.clientY - dragRef.current.startY,
      })
    }
  }

  const handleFabMouseDown = (e) => {
    setIsDragging(true)
    dragRef.current = {
      startX: e.clientX - fabPos.x,
      startY: e.clientY - fabPos.y,
    }
  }

  useEffect(() => {
    const handleMouseUp = () => setIsDragging(false)
    if (isDragging) {
      window.addEventListener('mouseup', handleMouseUp)
    }
    return () => {
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDragging])

  useEffect(() => {
    setLang(resolveLang())
  }, [])

  useEffect(() => {
    let userId = 1
    try {
      const profile = JSON.parse(window.localStorage.getItem('rag_profile_v1') || 'null')
      userId = profile && profile.userId ? profile.userId : 1
    } catch (err) {}
    getMetricsOverview(userId)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const tr = (key, vars) => t(lang, key, vars)

  const evalRows = data?.eval_results?.metrics || []
  const generation = data?.eval_results?.generation
  const strategyRows = data?.query_metrics?.by_strategy || {}
  const feedback = data?.feedback || { total: 0, up: 0, down: 0 }
  const reasons = data?.reason_distribution || {}
  const retrievalSeries = [
    { key: 'hit_at_1', label: tr('thHit1'), color: 'bg-orange-500' },
    { key: 'hit_at_4', label: tr('thHit'), color: 'bg-emerald-500' },
    { key: 'mrr', label: tr('thMrr'), color: 'bg-sky-500' },
  ]
  const generationSeries = generation ? [
    { key: 'answer_correctness', label: tr('answerCorrectness'), color: 'bg-emerald-500' },
    { key: 'faithfulness', label: tr('faithfulness'), color: 'bg-orange-500' },
    { key: 'answer_relevance', label: tr('answerRelevance'), color: 'bg-sky-500' },
    { key: 'citation_accuracy', label: tr('citationAccuracy'), color: 'bg-violet-500' },
    { key: 'citation_coverage', label: tr('citationCoverage'), color: 'bg-fuchsia-500' },
    { key: 'refusal_recall', label: tr('refusalRecall'), color: 'bg-rose-500' },
  ] : []

  // 复用抽离出来的三段式导航控件（带有更平滑的 cubic-bezier 缓动动画）
  const navSwitcher = (
    <div className="flex items-center rounded-full bg-white/30 p-1 backdrop-blur-md border border-white/50 shadow-[0_8px_32px_rgba(31,38,135,0.1)]">
      <div className="relative flex items-center">
        <div 
          className="absolute inset-y-0 left-0 rounded-full bg-white shadow-sm transition-transform duration-500 ease-[cubic-bezier(0.23,1,0.32,1)]"
          style={{
            width: '33.33%',
            transform: `translateX(${navTab === 'gallery' ? '0%' : navTab === 'workspace' ? '100%' : '200%'})`
          }}
        />
        <button onClick={() => handleTabChange('gallery')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'gallery' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800 hover:text-white/80'}`}>展示页</button>
        <button onClick={() => handleTabChange('workspace')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'workspace' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800 hover:text-white/80'}`}>主页面</button>
        <button onClick={() => handleTabChange('dashboard')} className={`relative z-10 w-20 md:w-24 py-1.5 md:py-2 text-xs font-bold transition-colors duration-300 ${navTab === 'dashboard' ? 'text-slate-800' : 'text-slate-600 hover:text-slate-800 hover:text-white/80'}`}>Dashboard</button>
      </div>
    </div>
  )

  return (
    <div 
      onMouseMove={handleMouseMove}
      className="relative min-h-screen w-full overflow-hidden bg-gradient-to-tr from-[#68c5ff] via-[#d6b7ff] to-[#fed39f] bg-[length:200%_200%] animate-[fluid-bg_15s_ease-in-out_infinite] font-sans text-slate-800 selection:bg-orange-200 selection:text-orange-900 antialiased"
    >
      <style>{`
        @keyframes fluid-bg {
          0% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
          100% { background-position: 0% 50%; }
        }
      `}</style>

      {/* 物理视差模糊光晕 (Parallax Glow Orbs) - 保持在绝对底层不动 */}
      <div 
        className="pointer-events-none absolute -top-40 -left-40 h-[45rem] w-[45rem] rounded-full bg-sky-300/35 blur-[130px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${mousePos.x * 1.5}px,${mousePos.y * 1.5}px, 0)` }}
      />
      <div 
        className="pointer-events-none absolute -bottom-40 -right-20 h-[50rem] w-[50rem] rounded-full bg-amber-300/35 blur-[140px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${-mousePos.x * 1.8}px,${-mousePos.y * 1.8}px, 0)` }}
      />
      <div 
        className="pointer-events-none absolute top-1/3 left-1/3 h-[35rem] w-[35rem] rounded-full bg-purple-300/25 blur-[130px] transition-transform duration-700 ease-out"
        style={{ transform: `translate3d(${mousePos.x * 0.8}px,${mousePos.y * 0.8}px, 0)` }}
      />

      {/* 划开水面的流光跟随层 */}
      <div 
        className="pointer-events-none fixed rounded-full bg-white/40 blur-[100px] transition-all duration-500 ease-out mix-blend-overlay z-0"
        style={{
          width: '800px',
          height: '800px',
          left: mousePos.cx !== -999 ? mousePos.cx - 400 : -999,
          top: mousePos.cy !== -999 ? mousePos.cy - 400 : -999,
        }}
      />

      {/* ========================================================================= */}
      {/* 内容容器：带渐隐渐现和微缩放的丝滑过渡 */}
      {/* ========================================================================= */}
      <div 
        className={`absolute inset-0 w-full h-full overflow-y-auto transition-all duration-400 ease-in-out ${
          isFading ? 'opacity-0 scale-[0.98] blur-[2px]' : 'opacity-100 scale-100 blur-0'
        }`}
      >
        {/* 顶部三段式滑动导航栏 */}
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50">
          {navSwitcher}
        </div>

        {/* 拖拽悬浮胶囊栏 (Draggable Floating Action Island) */}
        <div 
          className="fixed z-50 flex items-center gap-2 rounded-full border border-white/80 bg-white/75 p-2 shadow-[0_16px_40px_rgba(0,0,0,0.08)] backdrop-blur-2xl transition-shadow hover:shadow-[0_20px_50px_rgba(249,115,22,0.15)]"
          style={{ 
            right: '32px', 
            bottom: '32px',
            transform: `translate(${fabPos.x}px, ${fabPos.y}px)`,
            cursor: isDragging ? 'grabbing' : 'grab'
          }}
        >
          <div 
            onMouseDown={handleFabMouseDown}
            className="p-1.5 text-slate-400 hover:text-slate-700 cursor-grab active:cursor-grabbing transition-colors"
            title="Drag control island"
          >
            <GripHorizontal className="h-4 w-4" />
          </div>
          <div className="h-4 w-px bg-slate-300/60 mx-0.5" />
          
          <button 
            type="button" 
            onClick={() => { 
              const next = lang === 'zh' ? 'en' : 'zh'
              setLang(next)
              try { window.localStorage.setItem('rag_lang', next) } catch (err) {} 
            }} 
            className="rounded-full px-3 py-1.5 text-xs font-black text-slate-600 hover:bg-white/80 hover:text-orange-600 transition-all"
          >
            {lang === 'zh' ? 'EN' : '中'}
          </button>

          {/* 也为返回按钮接入渐现动画跳转 */}
          <a 
            href="/pancake?tab=workspace" 
            onClick={(e) => {
              e.preventDefault();
              handleTabChange('workspace');
            }}
            className="flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2 text-xs font-extrabold text-white shadow-md transition-all hover:bg-slate-800 hover:scale-105 active:scale-95"
          >
            <ArrowLeft className="h-3.5 w-3.5" /> 
            <span>{tr('backToCopilot')}</span>
          </a>
        </div>

        {/* 顶部通栏刊头 */}
        <header className="relative z-10 px-6 py-6 md:px-12 md:py-8 max-w-7xl mx-auto flex items-center justify-between pt-24">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-[1.4rem] bg-white/80 text-orange-500 shadow-md shadow-orange-500/10 border border-white/80 backdrop-blur-md">
              <BarChart3 className="h-6 w-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="font-serif text-2xl md:text-3xl font-bold tracking-tight text-white drop-shadow-sm">
                  {tr('dashboardTitle')}
                </h1>
                <span className="rounded-full bg-white/30 border border-white/40 px-2.5 py-0.5 text-[10px] font-black uppercase tracking-wider text-white backdrop-blur-md">
                  Telemetry
                </span>
              </div>
              <p className="mt-1 text-xs md:text-sm font-medium text-white/90 drop-shadow-xs">
                {tr('dashboardDesc')}
              </p>
            </div>
          </div>

          <div className="hidden sm:flex items-center gap-2 rounded-full border border-white/60 bg-white/30 px-4 py-1.5 text-xs font-bold text-white shadow-xs backdrop-blur-md">
            <Sparkles className="h-3.5 w-3.5 text-amber-300" />
            <span>Evaluation Benchmark Suite</span>
          </div>
        </header>

        {/* 主数据区 */}
        <main className="relative z-10 max-w-7xl mx-auto px-6 md:px-12 space-y-8 pb-32">
          {loading && (
            <div className="flex items-center gap-3 text-white py-24 justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-white" /> 
              <span className="text-base font-bold tracking-wide animate-pulse">
                {tr('loadingMetrics')}
              </span>
            </div>
          )}

          {error && (
            <div className="rounded-[2rem] border border-rose-200 bg-rose-50/80 p-6 text-sm font-bold text-rose-700 shadow-sm backdrop-blur-md">
              {error}
            </div>
          )}
          
          {data && (
            <>
              {/* 四项核心统计大卡片 */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-5">
                
                <div className="group rounded-[2rem] border border-white/70 bg-white/65 p-6 shadow-[0_8px_30px_rgba(0,0,0,0.03)] backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[11px] font-black uppercase tracking-widest text-slate-400">{tr('feedbackTotal')}</span>
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-orange-100 text-orange-600">
                      <Activity className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="font-serif text-4xl font-normal tracking-tight text-slate-900">{feedback.total || 0}</div>
                </div>

                <div className="group rounded-[2rem] border border-white/70 bg-white/65 p-6 shadow-[0_8px_30px_rgba(0,0,0,0.03)] backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[11px] font-black uppercase tracking-widest text-slate-400">{tr('feedbackGood')}</span>
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
                      <ThumbsUp className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="font-serif text-4xl font-normal tracking-tight text-emerald-700">{feedback.up || 0}</div>
                </div>

                <div className="group rounded-[2rem] border border-white/70 bg-white/65 p-6 shadow-[0_8px_30px_rgba(0,0,0,0.03)] backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[11px] font-black uppercase tracking-widest text-slate-400">{tr('feedbackBad')}</span>
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-rose-100 text-rose-600">
                      <ThumbsDown className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="font-serif text-4xl font-normal tracking-tight text-rose-700">{feedback.down || 0}</div>
                </div>

                <div className="group rounded-[2rem] border border-white/70 bg-white/65 p-6 shadow-[0_8px_30px_rgba(0,0,0,0.03)] backdrop-blur-2xl transition-all duration-300 hover:-translate-y-1 hover:bg-white/80 hover:shadow-lg">
                  <div className="mb-3 flex items-center justify-between">
                    <span className="text-[11px] font-black uppercase tracking-widest text-slate-400">{tr('queriesLogged')}</span>
                    <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-sky-100 text-sky-600">
                      <FileText className="h-4 w-4" />
                    </div>
                  </div>
                  <div className="font-serif text-4xl font-normal tracking-tight text-slate-900">{data.query_metrics?.total || 0}</div>
                </div>
              </div>

              {/* 金集基准评测表格 (Goldset Benchmark Table) */}
              <div className="overflow-hidden rounded-[2.2rem] border border-white/70 bg-white/65 shadow-[0_8px_32px_rgba(0,0,0,0.04)] backdrop-blur-2xl">
                <div className="flex items-center justify-between border-b border-white/60 px-8 py-5">
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-orange-100 text-orange-600">
                      <Target className="h-4 w-4" />
                    </div>
                    <h2 className="font-serif text-lg font-bold tracking-tight text-slate-900">
                      {tr('goldsetEvalTitle')}
                    </h2>
                  </div>
                  <span className="text-[11px] font-bold text-slate-400 uppercase tracking-wider">Hit Rate & Scoring</span>
                </div>
                
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-white/50 bg-white/30 text-left text-slate-500 font-extrabold text-[11px] uppercase tracking-wider">
                        <th className="px-8 py-4">{tr('thStrategy')}</th>
                        <th className="px-8 py-4">{tr('thHit1')}</th>
                        <th className="px-8 py-4">{tr('thHit')}</th>
                        <th className="px-8 py-4">{tr('thMrr')}</th>
                        <th className="px-8 py-4">{tr('thAvgLatency')}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/40">
                      {evalRows.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-8 py-12 text-center text-xs font-bold text-slate-400">
                            {tr('noGoldsetData')}
                          </td>
                        </tr>
                      )}
                      {evalRows.map(r => (
                        <tr key={r.strategy} className="transition-colors hover:bg-white/40">
                          <td className="px-8 py-4 font-extrabold text-slate-800">
                            <span className="inline-block rounded-full bg-white/80 px-3 py-1 shadow-xs border border-white/60">
                              {tr('strategy_' + r.strategy)}
                            </span>
                          </td>
                          <td className="px-8 py-4 font-black text-slate-700">
                            {((r.hit_at_1 ?? 0) * 100).toFixed(0)}%
                          </td>
                          <td className="px-8 py-4 font-black text-emerald-700">
                            {((r.hit_at_4 ?? 0) * 100).toFixed(0)}%
                          </td>
                          <td className="px-8 py-4 font-mono font-bold text-slate-700">
                            {r.mrr ?? 0}
                          </td>
                          <td className="px-8 py-4 font-mono text-slate-600">
                            {r.avg_retrieve_ms}ms
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="border-t border-white/50 px-8 py-7">
                  <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center gap-3">
                      <div className="flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-sky-700">
                        <BarChart3 className="h-4 w-4" />
                      </div>
                      <div>
                        <h3 className="font-serif text-base font-bold text-slate-900">{tr('retrievalChartTitle')}</h3>
                        <p className="text-xs font-medium text-slate-500">{tr('retrievalChartDesc')}</p>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-4">
                      {retrievalSeries.map(series => (
                        <span key={series.key} className="flex items-center gap-2 text-[11px] font-bold text-slate-500">
                          <span className={`h-2.5 w-2.5 rounded-sm ${series.color}`} />
                          {series.label}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="mt-7 grid grid-cols-3 gap-3 md:gap-8">
                    {evalRows.map(row => (
                      <div key={row.strategy} className="flex min-w-0 flex-col items-center">
                        <div className="flex h-52 w-full max-w-[170px] items-end justify-center gap-1.5 md:gap-2">
                          {retrievalSeries.map(series => {
                            const value = Math.max(0, Math.min(1, Number(row[series.key]) || 0))
                            return (
                              <div key={series.key} className="flex h-full flex-1 flex-col items-center justify-end">
                                <span className="mb-1 text-[10px] font-bold text-slate-500">
                                  {(value * 100).toFixed(0)}%
                                </span>
                                <div
                                  className={`w-full rounded-t-md ${series.color} shadow-sm`}
                                  style={{ height: `${Math.max(3, value * 100)}%` }}
                                  title={`${tr('strategy_' + row.strategy)} · ${series.label}: ${(value * 100).toFixed(1)}%`}
                                />
                              </div>
                            )
                          })}
                        </div>
                        <div className="mt-3 w-full border-t border-slate-200/80 pt-3 text-center">
                          <div className="truncate text-xs font-black text-slate-800">{tr('strategy_' + row.strategy)}</div>
                          <div className="mt-1 font-mono text-[10px] font-bold text-slate-400">{row.avg_retrieve_ms}ms</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* 左右分栏：归因分析与在线查询耗时 */}
              <div className="grid md:grid-cols-2 gap-6">
                
                {/* 反馈归因分布 */}
                <div className="rounded-[2.2rem] border border-white/70 bg-white/65 p-7 shadow-[0_8px_32px_rgba(0,0,0,0.04)] backdrop-blur-2xl">
                  <div className="mb-6 flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-100 text-rose-600">
                        <ShieldCheck className="h-4 w-4" />
                      </div>
                      <h2 className="font-serif text-base font-bold tracking-tight text-slate-900">
                        {tr('feedbackReasonsTitle')}
                      </h2>
                    </div>
                    <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest">Quality Audit</span>
                  </div>

                  {Object.keys(reasons).length === 0 && (
                    <p className="py-6 text-center text-xs font-bold text-slate-400">
                      {tr('noDownvotes')}
                    </p>
                  )}

                  <div className="space-y-2.5">
                    {Object.entries(reasons).map(([key, count]) => (
                      <div key={key} className="flex items-center justify-between rounded-2xl border border-white/60 bg-white/50 p-3.5 transition-all hover:bg-white/80 hover:shadow-xs">
                        <span className="text-xs font-bold text-slate-700">{tr('reason_' + key)}</span>
                        <span className="rounded-full bg-rose-100 px-3 py-1 font-mono text-xs font-black text-rose-700">
                          {count}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                
                {/* 在线策略检索表现 */}
                <div className="rounded-[2.2rem] border border-white/70 bg-white/65 p-7 shadow-[0_8px_32px_rgba(0,0,0,0.04)] backdrop-blur-2xl">
                  <div className="mb-6 flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-sky-100 text-sky-600">
                        <Layers className="h-4 w-4" />
                      </div>
                      <h2 className="font-serif text-base font-bold tracking-tight text-slate-900">
                        {tr('liveMetricsTitle')}
                      </h2>
                    </div>
                    <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-widest">Latency Spectrum</span>
                  </div>

                  {Object.keys(strategyRows).length === 0 && (
                    <p className="py-6 text-center text-xs font-bold text-slate-400">
                      {tr('noLiveMetrics')}
                    </p>
                  )}

                  <div className="space-y-3">
                    {Object.entries(strategyRows).map(([key, row]) => (
                      <div key={key} className="rounded-2xl border border-white/60 bg-white/50 p-4 transition-all hover:bg-white/80 hover:shadow-xs">
                        <div className="mb-2.5 flex items-center justify-between">
                          <span className="text-xs font-black text-slate-800">{tr('strategy_' + key)}</span>
                          <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-[10px] font-extrabold text-slate-600">
                            {row.count} {tr('queriesCount')}
                          </span>
                        </div>
                        
                        <div className="flex flex-wrap gap-2 text-[10.5px] font-bold text-slate-500">
                          <span className="rounded-lg bg-white/80 px-2.5 py-1 shadow-2xs">
                            {tr('retrieve')} <span className="text-slate-900 ml-1 font-mono">{row.retrieve_ms}ms</span>
                          </span>
                          <span className="rounded-lg bg-white/80 px-2.5 py-1 shadow-2xs">
                            {tr('firstToken')} <span className="text-slate-900 ml-1 font-mono">{row.first_token_ms}ms</span>
                          </span>
                          {row.refusals > 0 && (
                            <span className="rounded-lg bg-rose-100/80 text-rose-700 px-2.5 py-1 shadow-2xs">
                              {row.refusals} {tr('refusals')}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* LLM 生成忠实度与综合评测大横幅 */}
              {data.eval_results?.generation && (
                <div className="rounded-[2.5rem] border border-white/80 bg-gradient-to-r from-white/80 via-white/60 to-white/40 p-8 shadow-[0_12px_40px_rgba(31,38,135,0.06)] backdrop-blur-2xl">
                  <div className="mb-6 flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-orange-500 text-white shadow-md shadow-orange-500/30">
                      <Sparkles className="h-4 w-4" />
                    </div>
                    <div>
                      <h2 className="font-serif text-lg font-bold tracking-tight text-slate-900">
                        {tr('llmTitle')}
                      </h2>
                      <p className="text-xs font-medium text-slate-500">
                        {data.eval_results.generation.sample_size} cases · Correctness, grounding, citations & refusal
                      </p>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('answerCorrectness')}</div>
                      <div className="font-serif text-3xl font-bold text-emerald-700">
                        {((data.eval_results.generation.answer_correctness ?? 0) * 100).toFixed(0)}%
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('faithfulness')}</div>
                      <div className="font-serif text-3xl font-bold text-orange-600">
                        {((data.eval_results.generation.faithfulness ?? 0) * 100).toFixed(0)}%
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('answerRelevance')}</div>
                      <div className="font-serif text-3xl font-bold text-sky-700">
                        {((data.eval_results.generation.answer_relevance ?? 0) * 100).toFixed(0)}%
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('citationAccuracy')}</div>
                      <div className="font-serif text-3xl font-bold text-violet-700">
                        {((data.eval_results.generation.citation_accuracy ?? 0) * 100).toFixed(0)}%
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('refusalRecall')}</div>
                      <div className="font-serif text-3xl font-bold text-rose-700">
                        {((data.eval_results.generation.refusal_recall ?? 0) * 100).toFixed(0)}%
                      </div>
                    </div>

                    <div className="rounded-2xl border border-white/70 bg-white/70 p-5 shadow-xs">
                      <div className="mb-1 text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('avgTtft')}</div>
                      <div className="font-mono text-3xl font-bold text-slate-800">
                        {data.eval_results.generation.avg_ttft_ms ?? 0}
                        <span className="ml-1 font-sans text-xs text-slate-400">ms</span>
                      </div>
                    </div>
                  </div>

                  <div className="mt-8 grid gap-8 border-t border-white/60 pt-7 lg:grid-cols-[1.5fr_0.8fr] lg:gap-10">
                    <div>
                      <div className="flex items-center justify-between gap-4">
                        <div>
                          <h3 className="font-serif text-base font-bold text-slate-900">{tr('generationChartTitle')}</h3>
                          <p className="mt-1 text-xs font-medium text-slate-500">{tr('generationChartDesc')}</p>
                        </div>
                        <span className="rounded-full bg-white/80 px-3 py-1 font-mono text-[10px] font-black text-slate-500">
                          {generation.scored_sample_size ?? 0}/{generation.known_sample_size ?? 0}
                        </span>
                      </div>

                      <div className="mt-6 space-y-4">
                        {generationSeries.map(series => {
                          const value = Math.max(0, Math.min(1, Number(generation[series.key]) || 0))
                          return (
                            <div key={series.key} className="grid grid-cols-[minmax(92px,0.8fr)_minmax(120px,2fr)_52px] items-center gap-3">
                              <span className="truncate text-xs font-bold text-slate-600">{series.label}</span>
                              <div className="h-3 overflow-hidden rounded-full bg-white/80 ring-1 ring-slate-200/70">
                                <div
                                  className={`h-full rounded-full ${series.color}`}
                                  style={{ width: `${Math.max(2, value * 100)}%` }}
                                />
                              </div>
                              <span className="text-right font-mono text-xs font-black text-slate-800">
                                {(value * 100).toFixed(0)}%
                              </span>
                            </div>
                          )
                        })}
                      </div>
                    </div>

                    <div className="lg:border-l lg:border-white/70 lg:pl-8">
                      <div className="text-[10px] font-black uppercase tracking-widest text-slate-400">{tr('evalComposition')}</div>
                      <dl className="mt-4 space-y-3 text-xs">
                        <div className="flex items-center justify-between gap-4 border-b border-white/60 pb-3">
                          <dt className="font-bold text-slate-500">{tr('knownCases')}</dt>
                          <dd className="font-mono font-black text-emerald-700">{generation.known_sample_size ?? 0}</dd>
                        </div>
                        <div className="flex items-center justify-between gap-4 border-b border-white/60 pb-3">
                          <dt className="font-bold text-slate-500">{tr('noAnswerCases')}</dt>
                          <dd className="font-mono font-black text-rose-700">{generation.negative_sample_size ?? 0}</dd>
                        </div>
                        <div className="flex items-center justify-between gap-4 border-b border-white/60 pb-3">
                          <dt className="font-bold text-slate-500">{tr('flaggedCases')}</dt>
                          <dd className="font-mono font-black text-orange-700">{generation.failures?.length ?? 0}</dd>
                        </div>
                        <div className="flex items-start justify-between gap-4 border-b border-white/60 pb-3">
                          <dt className="font-bold text-slate-500">{tr('generatorModel')}</dt>
                          <dd className="max-w-[150px] truncate text-right font-mono font-black text-slate-700">{generation.generator_model || '—'}</dd>
                        </div>
                        <div className="flex items-start justify-between gap-4">
                          <dt className="font-bold text-slate-500">{tr('judgeModel')}</dt>
                          <dd className="max-w-[150px] truncate text-right font-mono font-black text-slate-700">{generation.judge_model || '—'}</dd>
                        </div>
                      </dl>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  )
}
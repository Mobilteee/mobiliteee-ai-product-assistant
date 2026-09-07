'use client'

import { useEffect, useState } from 'react'
import { BookOpen, X } from 'lucide-react'
import { t } from '../lib/i18n'

// Bilingual demo guide content (kept local so it follows the app's language state).
const CONTENT = {
  zh: [
    {
      emoji: '⚡',
      title: '极速体验',
      lines: [
        '进入首页后，点击三张「推荐问题」预设卡片即可直接查看回答——这些问题已内置静态答案缓存，秒开且不消耗任何 Token。',
        '也可以直接在输入框里提问（检索 + 生成走实时链路）。',
      ],
    },
    {
      emoji: '🎯',
      title: '检索过滤 · 作用域隔离',
      lines: [
        '点击左侧「业务分类」标签（智能客服 / 电商售后 / 架构权限 / 产品综合）可一键勾选，或通过「全库检索」取消筛选。',
        '勾选后后端会先按 Metadata 做前置硬过滤，只在所选分类/文档内检索，避免跨领域噪声与误召回。',
      ],
    },
    {
      emoji: '🛡️',
      title: '体验配额与限流',
      lines: [
        '系统向所有访客开放免费提问：全局限速（每分钟共享的真实调用数）+ 单 IP 频次保护（每小时自定义提问上限）。',
        '若返回 429“频次已达上限”，稍等片刻再试即可；推荐预设问题命中缓存，不计入配额。',
      ],
    },
    {
      emoji: '🔑',
      title: '深度压测 · BYOK',
      lines: [
        '如需大批量自定义提问或更深度测试：点右上角「个人设置」，填入你自己的 API Key（仅存于本机浏览器，不上传服务器）。',
        '填入后系统将优先使用你的 Key 并解锁无限调用，同时支持自定义 Base URL 与模型。',
      ],
    },
  ],
  en: [
    {
      emoji: '⚡',
      title: 'Instant demo',
      lines: [
        'Click any of the three recommended starter cards on the home screen to see an answer instantly — these come from a built-in static answer cache, so no tokens are spent.',
        'You can also type any question below; that path runs live retrieval + generation.',
      ],
    },
    {
      emoji: '🎯',
      title: 'Scope filter · metadata isolation',
      lines: [
        'Click a business-category chip on the left (Intelligent CS / E-commerce After-sales / Architecture & Permissions / General) to select it, or choose “All” to clear the scope.',
        'Once selected, the backend hard pre-filters by metadata so retrieval only ranks inside those categories/docs — no cross-domain noise.',
      ],
    },
    {
      emoji: '🛡️',
      title: 'Fair-use quota & rate limits',
      lines: [
        'Free questions are open to all visitors: a shared global per-minute cap plus a per-IP hourly cap on custom questions.',
        'If you get a 429 “rate limit reached”, just try again shortly. Recommended presets hit the cache and don’t count toward the quota.',
      ],
    },
    {
      emoji: '🔑',
      title: 'Deep testing · BYOK',
      lines: [
        'For heavy custom usage, open “Profile” in the top-right and enter your own API key (stored locally only, never uploaded).',
        'With your key set, the backend uses it first and lifts the demo limits; custom Base URL and model are also supported.',
      ],
    },
  ],
}

export default function GuideModal({ lang = 'zh' }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const items = CONTENT[lang] || CONTENT.zh

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t(lang, 'guideOpen')}
        title={t(lang, 'guideOpen')}
        className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-slate-600 shadow-sm ring-1 ring-gray-900/5 transition hover:text-orange-500 hover:ring-orange-300"
      >
        <BookOpen className="h-4 w-4" />
        <span className="hidden sm:inline">{t(lang, 'guideOpen')}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-[90] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-sm"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="max-h-[82vh] w-full max-w-lg overflow-y-auto rounded-3xl border border-white/70 bg-white/90 p-6 shadow-2xl backdrop-blur-xl"
          >
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="font-serif text-xl font-bold tracking-tight text-slate-900">{t(lang, 'guideOpen')}</h2>
                <p className="mt-0.5 text-xs font-medium text-slate-500">
                  {lang === 'zh' ? 'AI 产品知识助手 · 4 步上手' : 'AI Product Knowledge Assistant · Get started in 4 steps'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close"
                className="rounded-full bg-slate-100 p-1.5 text-slate-500 transition hover:bg-slate-200 hover:text-slate-800"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3">
              {items.map((sec, idx) => (
                <section key={idx} className="rounded-2xl border border-white/70 bg-white/70 p-4 shadow-[0_2px_12px_rgba(0,0,0,0.04)]">
                  <h3 className="mb-1.5 flex items-center gap-2 text-sm font-bold text-slate-800">
                    <span className="text-base leading-none">{sec.emoji}</span>
                    {sec.title}
                  </h3>
                  <ul className="space-y-1.5">
                    {sec.lines.map((line, j) => (
                      <li key={j} className="flex gap-2 text-[13px] font-medium leading-relaxed text-slate-600">
                        <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-300" />
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>

            <p className="mt-4 rounded-2xl bg-slate-50 p-3 text-center text-[11px] font-medium text-slate-500">
              {lang === 'zh'
                ? '📊 后端透明观看：右上角「Dashboard」实时展示金标评测命中率 / MRR、线上查询耗时与差评归因。'
                : '📊 Transparent backend view: the “Dashboard” (top-right) shows goldset hit-rate / MRR, live latency, and downvote attribution.'}
            </p>
          </div>
        </div>
      )}
    </>
  )
}

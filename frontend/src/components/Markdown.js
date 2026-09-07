'use client'

import { useState, useMemo } from 'react'
import { Check, Copy } from 'lucide-react'

const TABLE_SEP = /^\|?[\s:|-]+\|?$/;
const HEAD_RE = /^(#{1,3})\s+(.*)$/;
const LIST_RE = /^\s*(?:[-*]|\d+\.)\s+(.*)$/;

function parseBlocks(src) {
  const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  const pushParagraph = (accum) => {
    if (accum.length) {
      blocks.push({ type: 'p', text: accum.join(' ').trim() });
    }
  };
  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('```')) {
      const parts = [];
      const lang = line.slice(3).trim();
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) { parts.push(lines[i]); i++; }
      i++;
      blocks.push({ type: 'code', lang, text: parts.join('\n') });
      continue;
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1].trim())) {
      const rows = [line];
      i++;
      while (i < lines.length && lines[i].trim().includes('|')) { rows.push(lines[i]); i++; }
      const parsed = rows.map(r => r.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim()));
      if (parsed.length) {
        blocks.push({ type: 'table', header: parsed[0] || [], rows: parsed.slice(2) || [] });
      }
      continue;
    }
    const head = line.match(HEAD_RE);
    if (head) {
      pushParagraph([]);
      blocks.push({ type: 'h', level: head[1].length, text: head[2] });
      i++;
      continue;
    }
    const listItem = line.match(LIST_RE);
    if (listItem) {
      pushParagraph([]);
      const items = [listItem[1]];
      i++;
      while (i < lines.length) {
        const m = lines[i].match(LIST_RE);
        if (m) { items.push(m[1]); i++; }
        else if (lines[i].trim() === '') { i++; break; }
        else break;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }
    const paragraphAcc = [];
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].startsWith('```') && !HEAD_RE.test(lines[i]) && !lines[i].match(LIST_RE) && !(lines[i].includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i+1].trim()))) {
      paragraphAcc.push(lines[i]); i++;
    }
    pushParagraph(paragraphAcc);
    if (i < lines.length && lines[i].trim() === '') i++;
  }
  return blocks;
}

function renderInlineText(text, keyBase, onCitationClick) {
  const patterns = [
    { type: 'code', re: /`([^`]+)`/ },
    { type: 'strong', re: /\*\*([^*]+)\*\*/ },
    { type: 'em', re: /\*([^*\n]+)\*/ },
    { type: 'citeSource', re: /\[Source\s+(\d+)\]/i },
    { type: 'cite', re: /\[(\d+)\]/ }
  ];
  const out = [];
  let rest = String(text || '');
  let keyIdx = 0;
  while (rest) {
    let best = null;
    for (const p of patterns) {
      const m = rest.match(p.re);
      if (m && (best === null || m.index < best.index)) {
        best = { p, m };
      }
    }
    if (!best || best.index === undefined) {
      out.push(<span key={`${keyBase}-${keyIdx++}`}>{rest}</span>);
      break;
    }
    const { p, m } = best;
    if (m.index > 0) out.push(<span key={`${keyBase}-${keyIdx++}`}>{rest.slice(0, m.index)}</span>);
    if (p.type === 'code') {
      out.push(<code key={`${keyBase}-${keyIdx++}`} className="mx-0.5 rounded bg-slate-100 px-1.5 py-0.5 text-xs font-mono text-slate-700">{m[1]}</code>);
    } else if (p.type === 'strong') {
      out.push(<strong key={`${keyBase}-${keyIdx++}`} className="font-semibold text-slate-900">{renderInlineText(m[1], `${keyBase}-s${keyIdx}`, onCitationClick)}</strong>);
    } else if (p.type === 'em') {
      out.push(<em key={`${keyBase}-${keyIdx++}`} className="text-sm italic text-slate-500">{m[1]}</em>);
    } else if (p.type === 'citeSource' || p.type === 'cite') {
      const n = Number(m[1]);
      out.push(
        <button
          key={`${keyBase}-${keyIdx++}`}
          type="button"
          onClick={(e) => { e.stopPropagation(); onCitationClick && onCitationClick(n); }}
          className="mx-0.5 inline-block cursor-pointer rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600 transition hover:bg-blue-50 hover:text-blue-600"
        >
          [{n}]
        </button>
      );
    }
    rest = rest.slice(m.index + m[0].length);
  }
  return out;
}

function BlockBody({ block, onCitationClick, highlightText, blockNo }) {
  const rawText = block.text || block.content || '';
  const high = highlightText && rawText.toLowerCase().includes(String(highlightText).toLowerCase());
  if (block.type === 'h') {
    const Tag = block.level === 1 ? 'h3' : block.level === 2 ? 'h4' : 'h5';
    return <Tag className="mt-4 mb-2 font-semibold text-gray-800">{renderInlineText(rawText, `h${blockNo}`, onCitationClick)}</Tag>;
  }
  if (block.type === 'code') {
    return <CodeBlock block={block} blockNo={blockNo} />;
  }
  if (block.type === 'table') {
    return (
      <div className="overflow-x-auto my-3">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              {(block.header || []).map((cell, c) => <th key={c} className="border border-slate-200 bg-slate-100 px-2 py-1.5 text-left font-medium text-slate-700">{renderInlineText(cell, `th${blockNo}-${c}`, onCitationClick)}</th>)}
            </tr>
          </thead>
          <tbody>
            {(block.rows || []).map((row, r) => (
              <tr key={r} className={r % 2 ? 'bg-slate-50' : ''}>
                {row.map((cell, c) => <td key={c} className="border border-slate-200 px-2 py-1.5 text-slate-700">{renderInlineText(cell, `td${blockNo}-${r}-${c}`, onCitationClick)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (block.type === 'ul') {
    return (
      <ul className="my-2 list-disc space-y-0 pl-5">
        {(block.items || []).map((item, idx) => <li key={idx} className="my-1.5 leading-relaxed text-slate-800">{renderInlineText(item, `li${blockNo}-${idx}`, onCitationClick)}</li>)}
      </ul>
    );
  }
  const cls = high ? 'rag-highlight my-3 rounded-md border-l-4 border-yellow-500 bg-yellow-50 p-3 text-slate-800 transition-colors' : 'my-3 leading-relaxed text-slate-800';
  if (high) {
    const lower = String(highlightText);
    const at = rawText.toLowerCase().indexOf(lower.toLowerCase());
    if (at >= 0) {
      const before = rawText.slice(0, at);
      const hit = rawText.slice(at, at + lower.length);
      const after = rawText.slice(at + lower.length);
      return (
        <div className={cls}>
          {renderInlineText(before, `ph${blockNo}-b`, onCitationClick)}
          <mark className="rounded bg-yellow-200 px-0.5 text-slate-900">{hit}</mark>
          {renderInlineText(after, `ph${blockNo}-a`, onCitationClick)}
        </div>
      );
    }
  }
  return <div className={cls}>{renderInlineText(rawText, `p${blockNo}`, onCitationClick)}</div>;
}

function CodeBlock({ block, blockNo }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(block.text || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch (err) {
      // clipboard unavailable in insecure contexts
    }
  };
  return (
    <div className="my-3 overflow-hidden rounded-lg bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-700 px-3 py-1.5">
        <span className="font-mono text-xs text-slate-400">{block.lang || 'code'}</span>
        <button type="button" onClick={handleCopy} className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-slate-300 hover:bg-slate-700">
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-sm text-slate-100"><code>{block.text}</code></pre>
    </div>
  );
}

export default function Markdown({ content, onCitationClick, highlightText }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  return (
    <div className="min-w-0">
      {blocks.map((block, i) => <BlockBody key={i} block={block} onCitationClick={onCitationClick} highlightText={highlightText} blockNo={i} />)}
    </div>
  );
}

import React from 'react';

/**
 * Safe, dependency-free rich-text renderer for agent replies.
 *
 * It supports the small Markdown subset the assistant is instructed to use
 * (bold, italic, inline code, fenced code, links, lists, quotes, headings) and
 * lightweight LaTeX delimiters. Everything becomes React elements; raw HTML is
 * never injected.
 */

type InlineToken =
  | { type: 'text'; value: string }
  | { type: 'bold'; value: string }
  | { type: 'italic'; value: string }
  | { type: 'code'; value: string }
  | { type: 'math'; value: string }
  | { type: 'link'; value: string; href: string };

const INLINE_PATTERN =
  /(\*\*[^*\n]+?\*\*|__[^_\n]+?__|~~[^~\n]+?~~|`[^`\n]+?`|\$[^$\n]+?\$|\\\([\s\S]+?\\\)|\[([^\]]+)\]\(([^)]+)\)|\*[^*\n]+?\*|_[^_\n]+?_)/g;

const LATEX_SYMBOLS: Array<[RegExp, string]> = [
  [/\\times/g, '×'],
  [/\\cdot/g, '·'],
  [/\\pm/g, '±'],
  [/\\leq?/g, '≤'],
  [/\\geq?/g, '≥'],
  [/\\neq/g, '≠'],
  [/\\approx/g, '≈'],
  [/\\to/g, '→'],
  [/\\rightarrow/g, '→'],
  [/\\infty/g, '∞'],
  [/\\pi/g, 'π'],
  [/\\alpha/g, 'α'],
  [/\\beta/g, 'β'],
  [/\\gamma/g, 'γ'],
  [/\\theta/g, 'θ'],
  [/\\Delta/g, 'Δ'],
  [/\\sum/g, 'Σ'],
  [/\\sqrt\{([^{}]+)\}/g, '√($1)'],
  [/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, '($1)/($2)'],
  [/\\left|\\right/g, ''],
  [/\\[,;:!]/g, ' '],
];

function cleanMath(value: string): string {
  let out = value
    .replace(/^\$\$?|\$\$?$/g, '')
    .replace(/^\\\(|\\\)$/g, '')
    .replace(/^\\\[|\\\]$/g, '')
    .trim();
  for (const [pattern, replacement] of LATEX_SYMBOLS) {
    out = out.replace(pattern, replacement);
  }
  return out.replace(/[{}]/g, '');
}

function tokenizeInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  let cursor = 0;
  for (const match of text.matchAll(INLINE_PATTERN)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      tokens.push({ type: 'text', value: text.slice(cursor, index) });
    }
    const raw = match[0];
    if (raw.startsWith('**') || raw.startsWith('__')) {
      tokens.push({ type: 'bold', value: raw.slice(2, -2) });
    } else if (raw.startsWith('~~')) {
      tokens.push({ type: 'italic', value: raw.slice(2, -2) });
    } else if (raw.startsWith('`')) {
      tokens.push({ type: 'code', value: raw.slice(1, -1) });
    } else if (raw.startsWith('$')) {
      tokens.push({ type: 'math', value: cleanMath(raw) });
    } else if (raw.startsWith('\\(')) {
      tokens.push({ type: 'math', value: cleanMath(raw) });
    } else if (raw.startsWith('[')) {
      tokens.push({ type: 'link', value: match[1] || '', href: match[2] || '' });
    } else if (raw.startsWith('*')) {
      tokens.push({ type: 'italic', value: raw.slice(1, -1) });
    } else if (raw.startsWith('_')) {
      tokens.push({ type: 'italic', value: raw.slice(1, -1) });
    } else {
      tokens.push({ type: 'text', value: raw });
    }
    cursor = index + raw.length;
  }
  if (cursor < text.length) {
    tokens.push({ type: 'text', value: text.slice(cursor) });
  }
  return tokens;
}

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  return tokenizeInline(text).map((token, index) => {
    const key = `${keyPrefix}-${index}`;
    switch (token.type) {
      case 'bold':
        return <strong key={key} className="font-extrabold text-ink">{token.value}</strong>;
      case 'italic':
        return <em key={key}>{token.value}</em>;
      case 'code':
        return (
          <code
            key={key}
            dir="ltr"
            className="inline-block rounded bg-surface-muted px-1 py-0.5 font-mono text-[0.9em] text-ink-soft"
          >
            {token.value}
          </code>
        );
      case 'math':
        return (
          <span
            key={key}
            dir="ltr"
            className="inline-block rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[0.88em] text-primary-deep"
            title="فرمول"
          >
            {token.value}
          </span>
        );
      case 'link': {
        const safe = /^https?:\/\//i.test(token.href);
        return safe ? (
          <a
            key={key}
            href={token.href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline decoration-dotted"
          >
            {token.value}
          </a>
        ) : (
          <span key={key}>{token.value}</span>
        );
      }
      default:
        return <React.Fragment key={key}>{token.value}</React.Fragment>;
    }
  });
}

function renderTextBlocks(text: string, keyPrefix: string): React.ReactNode[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: React.ReactNode[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  let blockIndex = 0;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const value = paragraph.join(' ').trim();
    paragraph = [];
    if (!value) return;
    const key = `${keyPrefix}-p-${blockIndex++}`;
    blocks.push(
      <p key={key} className="leading-7">
        {renderInline(value, key)}
      </p>
    );
  };

  const flushList = () => {
    if (!list) return;
    const current = list;
    list = null;
    const key = `${keyPrefix}-list-${blockIndex++}`;
    const items = current.items.map((item, index) => (
      <li key={`${key}-${index}`} className="leading-7">
        {renderInline(item, `${key}-${index}`)}
      </li>
    ));
    blocks.push(
      current.ordered ? (
        <ol key={key} className="list-decimal pr-5 space-y-0.5">{items}</ol>
      ) : (
        <ul key={key} className="list-disc pr-5 space-y-0.5">{items}</ul>
      )
    );
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }

    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      const key = `${keyPrefix}-h-${blockIndex++}`;
      const content = renderInline(heading[2], key);
      blocks.push(
        <div
          key={key}
          className="font-extrabold text-ink text-[1.02em] mt-1"
          role="heading"
          aria-level={Math.min(heading[1].length + 2, 6)}
        >
          {content}
        </div>
      );
      continue;
    }

    const quote = /^>\s?(.*)$/.exec(trimmed);
    if (quote) {
      flushParagraph();
      flushList();
      const key = `${keyPrefix}-q-${blockIndex++}`;
      blocks.push(
        <blockquote
          key={key}
          className="border-r-2 border-primary-line pr-2.5 text-ink-soft leading-7"
        >
          {renderInline(quote[1], key)}
        </blockquote>
      );
      continue;
    }

    const listItem = /^([-*•]|\d+[.)])\s+(.*)$/.exec(trimmed);
    if (listItem) {
      flushParagraph();
      const ordered = /^\d/.test(listItem[1]);
      if (!list || list.ordered !== ordered) {
        flushList();
        list = { ordered, items: [] };
      }
      list.items.push(listItem[2]);
      continue;
    }

    flushList();
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  return blocks;
}

export const AgentRichText: React.FC<{ content: string; className?: string }> = ({
  content,
  className = '',
}) => {
  const nodes: React.ReactNode[] = [];
  const parts = content.replace(/\r\n/g, '\n').split(/```([\w-]*)\n?([\s\S]*?)```/g);
  // String.split with capture groups yields: text, lang, code, text, lang, code...
  for (let index = 0; index < parts.length; index += 3) {
    const text = parts[index] || '';
    if (text.trim()) {
      nodes.push(...renderTextBlocks(text, `t-${index}`));
    }
    const language = parts[index + 1];
    const code = parts[index + 2];
    if (code !== undefined) {
      nodes.push(
        <pre
          key={`code-${index}`}
          dir="ltr"
          className="overflow-x-auto rounded-[3px] bg-code-bg px-3 py-2 text-left font-mono text-[0.82em] leading-6 text-code-text"
        >
          <code>{code.replace(/\n$/, '')}</code>
          {language ? <span className="sr-only">{language}</span> : null}
        </pre>
      );
    }
  }

  return <div className={`space-y-1.5 ${className}`}>{nodes}</div>;
};

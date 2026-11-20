import React from 'react';
import { Check } from 'lucide-react';

interface FlowSectionProps {
  id: string;
  title: string;
  /** Chosen value, shown on the collapsed header. */
  summary?: string | null;
  /** Muted hint shown instead of a summary (e.g. what must be chosen first). */
  hint?: string;
  isOpen: boolean;
  isDone: boolean;
  isLast?: boolean;
  disabled?: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

export const FOCUS_RING =
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary';

/** One step of the booking timeline: collapses to a one-line summary once done. */
export const FlowSection: React.FC<FlowSectionProps> = ({
  id,
  title,
  summary,
  hint,
  isOpen,
  isDone,
  isLast = false,
  disabled = false,
  onToggle,
  children,
}) => (
  <section className="relative">
    {!isLast && (
      <span
        aria-hidden="true"
        className="absolute start-[13px] top-10 bottom-0 w-px bg-line"
      />
    )}
    <h4>
      <button
        type="button"
        id={`${id}-header`}
        aria-expanded={isOpen}
        aria-controls={`${id}-panel`}
        disabled={disabled}
        onClick={onToggle}
        className={`flex w-full items-center gap-3 rounded-[10px] py-2.5 text-start disabled:cursor-not-allowed ${FOCUS_RING}`}
      >
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition-colors ${
            isDone
              ? 'border-primary bg-primary text-on-accent'
              : isOpen
              ? 'border-primary bg-surface'
              : 'border-line bg-surface'
          }`}
        >
          {isDone ? (
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          ) : isOpen ? (
            <span className="h-2 w-2 rounded-full bg-primary" />
          ) : null}
        </span>
        <span className={`text-lead font-bold ${disabled ? 'text-faint' : 'text-ink'}`}>
          {title}
        </span>
        {!isOpen && summary && (
          <span className="min-w-0 flex-1 truncate text-small text-muted">{summary}</span>
        )}
        {!isOpen && !summary && hint && (
          <span className="min-w-0 flex-1 truncate text-small text-faint">{hint}</span>
        )}
        {!isOpen && isDone && !disabled && (
          <span className="ms-auto shrink-0 text-small font-semibold text-primary">تغییر</span>
        )}
      </button>
    </h4>
    {isOpen && (
      <div id={`${id}-panel`} role="region" aria-labelledby={`${id}-header`} className="d-fade pb-5 ps-10">
        {children}
      </div>
    )}
  </section>
);

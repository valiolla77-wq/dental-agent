import React, { useState } from 'react';
import { CheckCircle2, Flag, Lightbulb, Send, X } from 'lucide-react';
import { useClinic } from '../../context/ClinicContext';
import type { UIChatMessage } from '../../context/ClinicContext';

/**
 * Per-message feedback controls. An error report submits the message text and
 * the server-captured recent application logs; a suggestion stores the text as
 * product feedback. Both are authenticated and scoped server-side.
 */
export const AgentMessageActions: React.FC<{
  message: UIChatMessage;
  compact?: boolean;
}> = ({ message, compact = false }) => {
  const { submitMessageFeedback } = useClinic();
  const [mode, setMode] = useState<'error' | 'suggestion' | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isAgent = message.sender === 'agent';

  const close = () => {
    setMode(null);
    setNote('');
    setError(null);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!mode) return;
    const trimmed = note.trim();
    if (mode === 'suggestion' && trimmed.length < 3) {
      setError('پیشنهاد خود را کمی کامل‌تر بنویسید.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const feedbackMessage =
        mode === 'error'
          ? [
              `گزارش خطا برای پیام ${isAgent ? 'دستیار' : 'کاربر'}:`,
              message.content.slice(0, 2500),
              trimmed ? `توضیح کاربر: ${trimmed}` : '',
            ]
              .filter(Boolean)
              .join('\n')
          : trimmed;
      const result = await submitMessageFeedback({
        category: mode,
        message: feedbackMessage,
        assistantMessage: isAgent ? message.content : null,
        requestId: isAgent ? message.request_id ?? null : null,
      });
      setSuccess(result.message);
      setMode(null);
      setNote('');
    } catch (err: any) {
      setError(err?.message || 'ارسال بازخورد ناکام ماند.');
    } finally {
      setBusy(false);
    }
  };

  if (success) {
    return (
      <div className="mt-1.5 flex items-center gap-1.5 text-caption text-primary-deep">
        <CheckCircle2 className="w-3 h-3 shrink-0" />
        <span>{success}</span>
      </div>
    );
  }

  return (
    <div className={compact ? 'mt-1' : 'mt-1.5'}>
      {mode === null ? (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => {
              setMode('error');
              setSuccess(null);
              setError(null);
            }}
            className="inline-flex items-center gap-1 rounded-[3px] px-1.5 py-0.5 text-caption text-faint hover:text-danger hover:bg-danger-soft transition"
            title="ارسال این پیام همراه با لاگ‌های اخیر سرور"
          >
            <Flag className="w-3 h-3" />
            گزارش خطا
          </button>
          <button
            type="button"
            onClick={() => {
              setMode('suggestion');
              setSuccess(null);
              setError(null);
            }}
            className="inline-flex items-center gap-1 rounded-[3px] px-1.5 py-0.5 text-caption text-faint hover:text-primary hover:bg-primary-soft transition"
          >
            <Lightbulb className="w-3 h-3" />
            پیشنهاد
          </button>
        </div>
      ) : (
        <form
          onSubmit={submit}
          className="rounded-[3px] border border-line bg-surface-muted p-2 space-y-1.5"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-caption font-bold text-ink">
              {mode === 'error' ? 'گزارش خطا برای این پیام' : 'ثبت پیشنهاد'}
            </span>
            <button
              type="button"
              onClick={close}
              className="p-0.5 rounded text-faint hover:text-danger"
              aria-label="بستن"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            maxLength={1200}
            placeholder={
              mode === 'error'
                ? 'توضیح کوتاه (اختیاری): چه چیزی اشتباه بود؟'
                : 'پیشنهاد شما برای بهترشدن این بخش...'
            }
            className="d-input min-h-[52px] resize-y text-caption leading-5"
          />
          {mode === 'error' && (
            <p className="text-caption leading-4 text-faint">
              متن پیام و لاگ‌های اخیر سرور به‌صورت خودکار ارسال می‌شوند.
            </p>
          )}
          {error && <p className="text-caption leading-4 text-danger">{error}</p>}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-[3px] bg-primary px-2 py-1 text-caption font-bold text-on-accent disabled:opacity-60"
            >
              <Send className="w-3 h-3" />
              {busy ? 'در حال ارسال…' : 'ارسال'}
            </button>
          </div>
        </form>
      )}
    </div>
  );
};

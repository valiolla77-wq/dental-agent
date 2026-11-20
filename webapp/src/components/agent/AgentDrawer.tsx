import React, { useEffect, useRef, useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { AgentConfirmationCard } from './AgentConfirmationCard';
import { AgentMessageActions } from './AgentMessageActions';
import { AgentOptionCards } from './AgentOptionCards';
import { AgentRecordForm } from './AgentRecordForm';
import { AgentRichText } from './AgentRichText';
import { repeatsConfirmationPrompt } from '../../utils/agentMessages';
import { Button } from '../common/Button';
import {
  AlertCircle,
  Bot,
  Clock,
  RotateCcw,
  Send,
  Sparkles,
  User,
  UserPlus,
  X,
} from 'lucide-react';

/**
 * Quick-access agent drawer. It uses the same server-persisted chat session as
 * the full workspace, so nothing is duplicated or simulated locally.
 */
export const AgentDrawer: React.FC = () => {
  const {
    agentDrawerOpen,
    setAgentDrawerOpen,
    chatMessages,
    isAgentTyping,
    sendAgentMessage,
    retryLastAgentMessage,
    confirmAgentAction,
    clearAgentChat,
    sessionId,
    conversationTitle,
    recordFormRequired,
    openSelfRecordForm,
    closeSelfRecordForm,
  } = useClinic();
  const { currentUser } = useAuth();
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!agentDrawerOpen) return;
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, isAgentTyping, agentDrawerOpen]);

  useEffect(() => {
    if (agentDrawerOpen) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [agentDrawerOpen]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && agentDrawerOpen) setAgentDrawerOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [agentDrawerOpen, setAgentDrawerOpen]);

  if (!agentDrawerOpen) return null;

  const handleSubmit = (event?: React.FormEvent) => {
    if (event) event.preventDefault();
    if (!input.trim() || isAgentTyping) return;
    if (chatBlocked) return;
    const text = input;
    setInput('');
    sendAgentMessage(text);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      handleSubmit();
    }
  };

  const quickPrompts =
    currentUser?.role === 'patient'
      ? ['نوبت‌های من', 'رزرو نوبت جرم‌گیری', 'تغییر زمان نوبت']
      : ['نوبت‌های امروز', 'زمان‌های خالی فردا', 'گزارش این هفته'];
  const hasPatientRecord =
    (currentUser?.patients?.length ?? 0) > 0 || !!currentUser?.patient;
  const registrationRequired =
    currentUser?.role === 'patient' && !hasPatientRecord;
  const chatBlocked = registrationRequired || recordFormRequired;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden" role="dialog" aria-modal="true" aria-label="دستیار هوشمند">
      <div
        className="fixed inset-0 bg-ink-deep/45 backdrop-blur-[2px] d-fade"
        onClick={() => setAgentDrawerOpen(false)}
        aria-hidden="true"
      />

      <div className="fixed inset-y-0 left-0 max-w-full flex">
        <div className="w-screen max-w-[440px] bg-surface shadow-[24px_0_80px_-24px_rgba(23,43,71,0.35)] border-r border-line flex flex-col">
          {/* Header */}
          <div className="px-4 py-4 border-b border-line-soft flex items-center justify-between gap-3 bg-surface">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="relative w-9 h-9 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4" />
                <span className="absolute -bottom-0.5 -left-0.5 w-2.5 h-2.5 rounded-full bg-primary border-2 border-surface" />
              </div>
              <div className="min-w-0">
                <h3 className="text-small font-bold text-ink flex items-center gap-1.5">
                  دستیار Dental Agent
                  <Sparkles className="w-3 h-3 text-ai" />
                </h3>
                <p className="text-caption text-faint truncate mt-0.5">
                  {conversationTitle?.trim()
                    ? conversationTitle
                    : sessionId
                    ? `جلسه ${sessionId.slice(0, 14)}…`
                    : 'گفتگوی جدید'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-0.5">
              {currentUser?.role === 'patient' && hasPatientRecord && (
                <button
                  type="button"
                  onClick={() =>
                    recordFormRequired ? closeSelfRecordForm() : openSelfRecordForm()
                  }
                  title={recordFormRequired ? 'بستن فرم بیمار' : 'افزودن بیمار'}
                  className="p-2 text-primary hover:bg-primary-soft rounded-[8px] transition-colors"
                >
                  <UserPlus className="w-3.5 h-3.5" />
                </button>
              )}
              <button
                type="button"
                onClick={clearAgentChat}
                title="شروع مجدد گفتگو"
                className="p-2 text-faint hover:text-ink hover:bg-canvas rounded-[8px] transition-colors"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => setAgentDrawerOpen(false)}
                className="p-2 text-faint hover:text-ink hover:bg-canvas rounded-[8px] transition-colors"
                aria-label="بستن دستیار"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-3.5 py-4 space-y-3.5 bg-surface-muted">
            {chatMessages.length === 0 && !isAgentTyping && (
              <div className="d-card p-4 text-center">
                <div className="w-11 h-11 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center mx-auto mb-3">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div className="text-small font-bold text-ink">
                  چه کاری می‌توانم برایتان انجام دهم؟
                </div>
                <p className="text-caption text-muted mt-1.5 leading-5">
                  نوبت‌ها، زمان‌های خالی و پرونده‌ها را از سرور بررسی می‌کنم و پیش از هر تغییر از
                  شما تأیید می‌گیرم.
                </p>
              </div>
            )}

            {chatMessages.map((message) => {
              const isUser = message.sender === 'user';
              return (
                <div
                  key={message.id}
                  className={`flex items-start gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
                >
                  <div
                    className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 border ${
                      isUser
                        ? 'bg-ink border-ink text-on-accent'
                        : 'bg-ai-soft border-ai-line text-ai'
                    }`}
                  >
                    {isUser ? <User className="w-3 h-3" /> : <Bot className="w-3 h-3" />}
                  </div>

                  <div
                    className={`max-w-[86%] px-3 py-2.5 text-caption leading-6 ${
                      isUser ? 'd-chat-bubble-user' : 'd-chat-bubble-agent'
                    }`}
                  >
                    {message.error && (
                      <div className="mb-2 px-2 py-1.5 rounded-[7px] bg-danger-soft border border-danger-line text-caption text-danger flex items-start gap-1.5">
                        <AlertCircle className="w-3 h-3 shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <span>{message.error}</span>
                          {message.retryable && (
                            <button
                              type="button"
                              onClick={() => retryLastAgentMessage()}
                              disabled={isAgentTyping}
                              className="mt-1.5 inline-flex items-center gap-1 rounded-[6px] border border-danger-line bg-surface px-2 py-1 text-caption font-semibold text-danger-deep hover:bg-danger-soft disabled:opacity-50"
                            >
                              <RotateCcw className="w-2.5 h-2.5" />
                              تلاش دوباره
                            </button>
                          )}
                        </div>
                      </div>
                    )}

                    {isUser ? (
                      <div className="whitespace-pre-wrap">{message.content}</div>
                    ) : (
                      !repeatsConfirmationPrompt(
                        message.content,
                        message.confirmation_prompt,
                        Boolean(message.confirmation_required && message.confirmation_token)
                      ) && <AgentRichText content={message.content} />
                    )}

                    {message.options && message.options.length > 0 && (
                      <AgentOptionCards
                        options={message.options}
                        disabled={isAgentTyping}
                        onSelect={(numericMessage) => sendAgentMessage(numericMessage)}
                        compact
                      />
                    )}

                    {message.confirmation_required && message.confirmation_token && (
                      <div className="mt-2.5">
                        <AgentConfirmationCard
                          token={message.confirmation_token}
                          promptText={
                            message.confirmation_prompt ||
                            'آیا اجرای این عملیات را تأیید می‌فرمایید؟'
                          }
                          suggestedAppointments={message.suggested_appointments}
                          confirmed={message.confirmed}
                        outcomeUnknown={message.outcomeUnknown}
                          rejected={message.rejected}
                          onConfirm={(token) => confirmAgentAction(token, 'approved')}
                          onReject={(token) => confirmAgentAction(token, 'rejected')}
                        />
                      </div>
                    )}

                    <div
                      className={`text-caption mt-1.5 flex items-center gap-1 ${
                        isUser ? 'text-on-accent/60 justify-end' : 'text-faint'
                      }`}
                    >
                      <Clock className="w-2.5 h-2.5" />
                      {new Date(message.timestamp).toLocaleTimeString('fa-IR', {
                        hour: '2-digit',
                        minute: '2-digit',
                      })}
                    </div>

                    <div className={isUser ? 'text-on-accent/80' : ''}>
                      <AgentMessageActions message={message} compact />
                    </div>
                  </div>
                </div>
              );
            })}

            {registrationRequired && (
              <div className="d-card border-primary-line bg-surface-muted p-3 text-caption leading-5 text-primary-deep flex items-start gap-2">
                <UserPlus className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <span>
                  برای شروع گفتگو، ابتدا پرونده بیمار را ثبت کنید. پس از ثبت، دستیار فعال می‌شود.
                </span>
              </div>
            )}

            <AgentRecordForm compact />

            {isAgentTyping && (
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center shrink-0">
                  <Bot className="w-3 h-3 animate-pulse" />
                </div>
                <div className="d-chat-bubble-agent px-3 py-2 flex items-center gap-2 text-caption text-muted">
                  <span className="inline-flex gap-1">
                    <span className="w-1 h-1 bg-ai rounded-full animate-bounce [animation-delay:-0.3s]" />
                    <span className="w-1 h-1 bg-ai rounded-full animate-bounce [animation-delay:-0.15s]" />
                    <span className="w-1 h-1 bg-ai rounded-full animate-bounce" />
                  </span>
                  در حال بررسی…
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {!chatBlocked ? (
            <>
              {/* Quick prompts */}
              <div className="px-3 py-2 bg-surface border-t border-line-soft flex items-center gap-1.5 overflow-x-auto no-scrollbar">
                {quickPrompts.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => sendAgentMessage(chip)}
                    disabled={isAgentTyping}
                    className="d-chip shrink-0 !h-8 !text-caption"
                  >
                    {chip}
                  </button>
                ))}
              </div>

              {/* Composer */}
              <form
                onSubmit={handleSubmit}
                className="p-3 bg-surface border-t border-line-soft flex items-end gap-2"
              >
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="پیام یا دستور خود را بنویسید…"
                  rows={1}
                  className="flex-1 resize-none bg-surface-muted border border-line rounded-[10px] text-caption text-ink placeholder:text-faint px-3 py-2.5 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 min-h-[40px] max-h-24"
                  dir="rtl"
                />
                <Button
                  type="submit"
                  size="sm"
                  className="!h-10"
                  disabled={!input.trim() || isAgentTyping}
                  icon={<Send className="w-3.5 h-3.5" />}
                >
                  ارسال
                </Button>
              </form>
            </>
          ) : (
            <div className="px-4 py-3 bg-surface-muted border-t border-line-soft text-center text-caption text-muted">
              {registrationRequired
                ? 'پس از ثبت پرونده، کادر گفتگو فعال می‌شود.'
                : 'فرم بیمار باز است؛ برای ادامه گفتگو آن را ببندید یا بیمار را اضافه کنید.'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

import React, { useEffect, useRef, useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { AgentConfirmationCard } from './AgentConfirmationCard';
import { AgentMessageActions } from './AgentMessageActions';
import { AgentOptionCards } from './AgentOptionCards';
import { AgentRecordForm } from './AgentRecordForm';
import { AgentRichText } from './AgentRichText';
import { Button } from '../common/Button';
import { PageHeader } from '../common/ui';
import {
  AlertCircle,
  Bot,
  ChevronLeft,
  Clock,
  MessageSquare,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  User,
  UserPlus,
} from 'lucide-react';
import { repeatsConfirmationPrompt } from '../../utils/agentMessages';
import { formatToJalali, toPersianDigits } from '../../utils/persianDate';

/**
 * Full-page agent workspace. Conversation history and every assistant reply
 * are persisted server-side; the UI only renders what ``/agent/chat`` returns.
 */
export const AgentView: React.FC = () => {
  const { currentUser } = useAuth();
  const {
    chatMessages,
    isAgentTyping,
    sessionId,
    conversationTitle,
    conversations,
    sendAgentMessage,
    retryLastAgentMessage,
    confirmAgentAction,
    clearAgentChat,
    openConversation,
    deleteConversation,
    recordFormRequired,
    openSelfRecordForm,
    closeSelfRecordForm,
  } = useClinic();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, isAgentTyping]);

  const handleSubmit = (event?: React.FormEvent) => {
    if (event) event.preventDefault();
    if (!input.trim() || isAgentTyping) return;
    if (
      (currentUser?.role === 'patient' &&
        (currentUser.patients?.length ?? 0) === 0 &&
        !currentUser.patient) ||
      recordFormRequired
    ) {
      return;
    }
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

  const role = currentUser?.role || 'patient';
  const roleSuggestions: Record<string, string[]> = {
    patient: [
      'نوبت‌های من را نشان بده',
      'می‌خواهم برای معاینه و جرم‌گیری وقت بگیرم',
      'زمان‌های خالی پزشکان در این هفته',
      'می‌خواهم نوبت قبلی‌ام را تغییر دهم',
    ],
    doctor: [
      'برنامه نوبت‌های امروز من چیست؟',
      'گزارش نوبت‌های هفته پیش روی کلینیک',
      'فهرست خدمات دندانپزشکی کلینیک',
    ],
    receptionist: [
      'زمان‌های خالی پزشکان برای فردا',
      'گزارش نوبت‌های امروز کلینیک',
      'رزرو نوبت جدید برای بیمار',
    ],
    admin: [
      'گزارش کلی نوبت‌های کلینیک در ۳۰ روز آینده',
      'نمای کلی کلینیک را گزارش بده',
      'چند پرونده ناقص ثبت شده است؟',
    ],
  };

  const currentSuggestions = roleSuggestions[role] || roleSuggestions.patient;
  const hasPatientRecord =
    (currentUser?.patients?.length ?? 0) > 0 || !!currentUser?.patient;
  const registrationRequired = role === 'patient' && !hasPatientRecord;
  const chatBlocked = registrationRequired || recordFormRequired;

  return (
    <div className="d-page d-fade flex flex-col h-[calc(100vh-74px)] !pb-5 min-w-0">
      <PageHeader
        title="دستیار هوشمند کلینیک"
        subtitle="پرسش، رزرو یا تغییر نوبت با گفتگوی فارسی؛ هر تغییر فقط پس از تأیید شما روی سرور اجرا می‌شود."
        action={
          <div className="flex items-center gap-2">
            {role === 'patient' && hasPatientRecord && (
              <Button
                variant="secondary"
                size="md"
                onClick={() => (recordFormRequired ? closeSelfRecordForm() : openSelfRecordForm())}
                icon={<UserPlus className="w-4 h-4" />}
              >
                {recordFormRequired ? 'بستن فرم بیمار' : 'افزودن بیمار'}
              </Button>
            )}
            <Button
              variant="ai"
              size="md"
              onClick={() => clearAgentChat()}
              icon={<Plus className="w-4 h-4" />}
            >
              گفتگوی جدید
            </Button>
          </div>
        }
      />

      <div className="flex-1 min-h-0 flex gap-4">
        {/* Server-persisted conversation history */}
        <aside className="hidden lg:flex w-[260px] shrink-0 d-card flex-col overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3.5 border-b border-line-soft">
            <div className="flex items-center gap-2 text-small font-bold text-ink">
              <MessageSquare className="w-4 h-4 text-primary" />
              گفتگوهای من
            </div>
            <button
              type="button"
              title="گفتگوی جدید"
              onClick={() => clearAgentChat()}
              className="p-1.5 rounded-[8px] bg-primary-soft text-primary border border-primary-line hover:bg-primary-hover transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {conversations.length === 0 ? (
              <div className="px-3 py-8 text-center text-caption text-muted leading-6">
                هنوز گفتگوی ذخیره‌شده‌ای ندارید.
                <br />
                تاریخچه به‌طور خودکار روی سرور ذخیره می‌شود.
              </div>
            ) : (
              conversations.map((conversation) => {
                const isActive = sessionId === conversation.session_id;
                return (
                  <div
                    key={conversation.session_id}
                    className={`group rounded-[10px] border transition-colors ${
                      isActive
                        ? 'border-primary-line bg-primary-soft'
                        : 'border-transparent hover:bg-surface-muted'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => openConversation(conversation.session_id)}
                      disabled={isAgentTyping}
                      className="w-full text-right px-3 py-2.5 disabled:opacity-60"
                    >
                      <div
                        className={`text-caption font-semibold truncate ${
                          isActive ? 'text-primary-deep' : 'text-ink'
                        }`}
                      >
                        {conversation.title || 'گفتگوی بدون عنوان'}
                      </div>
                      <div className="text-caption text-faint flex items-center gap-1.5 mt-1">
                        <span className="tabular-nums">
                          {toPersianDigits(conversation.message_count)}
                        </span>
                        <span>پیام</span>
                        <span className="text-line-strong">•</span>
                        <span>{formatToJalali(conversation.updated_at.slice(0, 10))}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      title="حذف گفتگو و تاریخچه آن"
                      onClick={() => deleteConversation(conversation.session_id)}
                      className="hidden group-hover:flex items-center gap-1 text-caption text-danger hover:text-danger-deep px-3 pb-2"
                    >
                      <Trash2 className="w-3 h-3" />
                      حذف
                    </button>
                  </div>
                );
              })
            )}
          </div>

          <div className="px-3.5 py-3 border-t border-line-soft text-caption text-faint leading-5">
            تاریخچه فقط برای حساب شما روی سرور ذخیره می‌شود. حذف از این فهرست، ردیف دیتابیس را هم
            پاک می‌کند.
          </div>
        </aside>

        {/* Chat surface */}
        <div className="flex-1 min-w-0 d-card flex flex-col overflow-hidden">
          {/* Chat header */}
          <div className="flex items-center justify-between gap-3 px-4 sm:px-5 py-3.5 border-b border-line-soft">
            <div className="flex items-center gap-3 min-w-0">
              <div className="relative w-10 h-10 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center shrink-0">
                <Bot className="w-5 h-5" />
                <span className="absolute -bottom-0.5 -left-0.5 w-3 h-3 rounded-full bg-primary border-2 border-surface" />
              </div>
              <div className="min-w-0">
                <h2 className="text-small font-bold text-ink flex items-center gap-2">
                  دستیار Dental Agent
                  <span className="hidden sm:inline-flex items-center gap-1 text-caption font-semibold text-ai bg-ai-soft border border-ai-line rounded-full px-2 py-0.5">
                    <Sparkles className="w-2.5 h-2.5" />
                    متصل به سرور
                  </span>
                </h2>
                <p className="text-caption text-faint truncate mt-0.5">
                  {conversationTitle?.trim()
                    ? conversationTitle
                    : sessionId
                    ? `جلسه فعال: ${sessionId.slice(0, 18)}…`
                    : 'گفتگوی جدید — پیام خود را بنویسید'}
                </p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => clearAgentChat()}
              icon={<RotateCcw className="w-3.5 h-3.5" />}
            >
              شروع مجدد
            </Button>
          </div>

          {/* Messages */}
          <div
            role="log"
            aria-live="polite"
            aria-label="گفتگو با دستیار"
            className="flex-1 min-h-0 overflow-y-auto bg-surface-muted px-3 sm:px-5 py-4 space-y-4"
          >
            {chatMessages.length === 0 && !isAgentTyping && (
              <div className="h-full min-h-[220px] flex items-center justify-center">
                <div className="max-w-md text-center">
                  <div className="w-14 h-14 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center mx-auto mb-4">
                    <Sparkles className="w-6 h-6" />
                  </div>
                  <h3 className="text-lead font-bold text-ink">
                    گفتگو را با یک پرسش شروع کنید
                  </h3>
                  <p className="text-caption text-muted mt-2 leading-6">
                    دستیار می‌تواند نوبت‌ها را بررسی کند، زمان خالی پیشنهاد بدهد و پس از تأیید شما
                    نوبت را ثبت یا تغییر دهد. هیچ تغییری بدون تأیید انجام نمی‌شود.
                  </p>
                </div>
              </div>
            )}

            {chatMessages.map((message) => {
              const isUser = message.sender === 'user';
              return (
                <div
                  key={message.id}
                  className={`flex items-start gap-2.5 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}
                >
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 border ${
                      isUser
                        ? 'bg-ink border-ink text-on-accent'
                        : 'bg-ai-soft border-ai-line text-ai'
                    }`}
                  >
                    {isUser ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
                  </div>

                  <div
                    className={`max-w-[88%] sm:max-w-xl px-3.5 py-3 text-small leading-6 ${
                      isUser ? 'd-chat-bubble-user' : 'd-chat-bubble-agent'
                    }`}
                  >
                    {message.error && (
                      <div className="mb-2 px-2.5 py-2 rounded-[8px] bg-danger-soft border border-danger-line text-caption text-danger flex items-start gap-1.5">
                        <AlertCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
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
                      />
                    )}

                    {message.confirmation_required && message.confirmation_token && (
                      <AgentConfirmationCard
                        token={message.confirmation_token}
                        promptText={message.confirmation_prompt}
                        suggestedAppointments={message.suggested_appointments}
                        confirmed={message.confirmed}
                        outcomeUnknown={message.outcomeUnknown}
                        rejected={message.rejected}
                        onConfirm={(token) => confirmAgentAction(token, 'approved')}
                        onReject={(token) => confirmAgentAction(token, 'rejected')}
                      />
                    )}

                    <div
                      className={`text-caption mt-2 flex items-center gap-1 ${
                        isUser ? 'text-on-accent/65 justify-end' : 'text-faint'
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
              <div className="d-card border-primary-line bg-surface-muted p-3">
                <div className="flex items-start gap-2 text-caption leading-5 text-primary-deep">
                  <UserPlus className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>
                    برای شروع گفتگو، ابتدا پرونده بیمار را ثبت کنید. پس از ثبت، دستیار نوبت‌دهی
                    فعال می‌شود.
                  </span>
                </div>
              </div>
            )}

            <AgentRecordForm />

            {isAgentTyping && (
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-full bg-ai-soft border border-ai-line text-ai flex items-center justify-center shrink-0">
                  <Bot className="w-3.5 h-3.5 animate-pulse" />
                </div>
                <div
                  aria-live="polite"
                  className="d-chat-bubble-agent px-3.5 py-2.5 flex items-center gap-2 text-caption text-muted"
                >
                  <span aria-hidden="true" className="inline-flex gap-1">
                    <span className="w-1.5 h-1.5 bg-ai rounded-full animate-bounce [animation-delay:-0.3s]" />
                    <span className="w-1.5 h-1.5 bg-ai rounded-full animate-bounce [animation-delay:-0.15s]" />
                    <span className="w-1.5 h-1.5 bg-ai rounded-full animate-bounce" />
                  </span>
                  در حال بررسی درخواست و داده‌های کلینیک…
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {!chatBlocked && (
            <>
              {/* Suggestion chips */}
              <div className="px-3 sm:px-4 py-2 flex items-center gap-1.5 overflow-x-auto no-scrollbar border-t border-line-soft bg-surface">
                {currentSuggestions.map((promptText) => (
                  <button
                    key={promptText}
                    type="button"
                    onClick={() => sendAgentMessage(promptText)}
                    disabled={isAgentTyping}
                    className="d-chip shrink-0 !h-9 !text-caption"
                  >
                    {promptText}
                  </button>
                ))}
              </div>

              {/* Composer */}
              <form
                onSubmit={handleSubmit}
                className="p-3 bg-surface border-t border-line-soft flex items-end gap-2"
              >
                <div className="flex-1 d-textarea !p-0 border border-line rounded-[12px] focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/10 bg-surface-muted">
                  <textarea
                    value={input}
                    onChange={(event) => setInput(event.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="پیام یا دستور خود را بنویسید… (Enter ارسال، Shift+Enter خط جدید)"
                    rows={1}
                    className="w-full resize-none bg-transparent text-small text-ink placeholder:text-faint px-3 py-2.5 focus:outline-none min-h-[42px] max-h-28"
                    dir="rtl"
                  />
                </div>
                <Button
                  type="submit"
                  size="md"
                  disabled={!input.trim() || isAgentTyping}
                  icon={<Send className="w-4 h-4" />}
                >
                  ارسال
                </Button>
              </form>
            </>
          )}
          {chatBlocked && (
            <div className="px-4 py-3 bg-surface-muted border-t border-line-soft text-center text-caption text-muted">
              {registrationRequired
                ? 'پس از ثبت پرونده، کادر گفتگو فعال می‌شود.'
                : 'فرم بیمار باز است؛ برای ادامه گفتگو آن را ببندید یا بیمار را اضافه کنید.'}
            </div>
          )}
        </div>

        {/* Context rail */}
        <aside className="hidden xl:flex w-[240px] shrink-0 flex-col gap-3">
          <section className="d-ai-card p-4">
            <div className="flex items-center gap-1.5 text-caption font-bold text-ai">
              <Sparkles className="w-3.5 h-3.5" />
              دستیار چگونه کار می‌کند؟
            </div>
            <ul className="mt-3 space-y-2 text-caption text-muted leading-5">
              <li className="bg-surface/70 border border-ai-line rounded-[9px] px-2.5 py-2">
                داده‌ها را از همان API واقعی کلینیک می‌خواند.
              </li>
              <li className="bg-surface/70 border border-ai-line rounded-[9px] px-2.5 py-2">
                پیش از هر تغییر، کارت تأیید نمایش می‌دهد.
              </li>
              <li className="bg-surface/70 border border-ai-line rounded-[9px] px-2.5 py-2">
                نتیجه اجرا دوباره از سرور خوانده می‌شود.
              </li>
            </ul>
          </section>

          <section className="d-card p-4">
            <div className="text-caption font-bold text-ink">پیشنهادها</div>
            <div className="mt-2.5 space-y-2">
              {currentSuggestions.slice(0, 3).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => sendAgentMessage(suggestion)}
                  disabled={isAgentTyping || chatBlocked}
                  className="w-full text-right text-caption text-muted leading-5 rounded-[9px] border border-line px-2.5 py-2 hover:border-primary-line hover:bg-surface-muted transition-colors disabled:opacity-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </section>

          <button
            type="button"
            onClick={() => clearAgentChat()}
            className="d-card p-3 flex items-center justify-between text-caption text-muted hover:border-primary-line"
          >
            <span className="flex items-center gap-2">
              <RotateCcw className="w-3.5 h-3.5" />
              گفتگوی جدید
            </span>
            <ChevronLeft className="w-3.5 h-3.5 text-line-strong" />
          </button>
        </aside>
      </div>
    </div>
  );
};

import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import {
  Patient,
  PatientCreate,
  PatientSelfRegister,
  Doctor,
  DentalService,
  Appointment,
  AppointmentCreate,
  AppointmentReschedule,
  BackendHealth,
  ChatHistoryMessage,
  ChatResponse,
  ChatSuggestedAppointment,
  ChatOptionItem,
  ChatConversation,
  FeedbackResponse,
} from '../types';
import { apiClient, ApiError } from '../api/client';
import { isOutcomeUncertain, OUTCOME_UNKNOWN_MESSAGE } from '../utils/agentMessages';
import { useAuth } from './AuthContext';

export interface UIChatMessage {
  id: string;
  sender: 'user' | 'agent';
  content: string;
  timestamp: string;
  confirmation_required?: boolean;
  confirmation_prompt?: string | null;
  confirmation_token?: string | null;
  suggested_appointments?: ChatSuggestedAppointment[];
  slots?: ChatSuggestedAppointment[];
  options?: ChatOptionItem[];
  confirmed?: boolean;
  rejected?: boolean;
  /** Approved, but the reply was lost: the write may or may not have happened. */
  outcomeUnknown?: boolean;
  error?: string;
  retryable?: boolean;
  request_id?: string | null;
}

interface ClinicContextType {
  patients: Patient[];
  doctors: Doctor[];
  services: DentalService[];
  appointments: Appointment[];
  healthState: BackendHealth;
  isLoading: boolean;
  errorMessage: string | null;
  refreshAll: () => Promise<void>;
  refreshHealth: () => Promise<void>;
  createPatient: (data: PatientCreate) => Promise<Patient>;
  bookAppointment: (data: AppointmentCreate) => Promise<Appointment>;
  cancelAppointment: (id: number) => Promise<void>;
  rescheduleAppointment: (id: number, data: AppointmentReschedule) => Promise<void>;
  getAvailableSlots: (doctorId: number, date: string) => Promise<string[]>;
  // Agentic AI Chat (server-persisted per user/session)
  chatMessages: UIChatMessage[];
  isAgentTyping: boolean;
  sessionId: string | null;
  conversations: ChatConversation[];
  conversationTitle: string | null;
  recordFormRequired: boolean;
  selfRecordSubmitting: boolean;
  sendAgentMessage: (messageText: string) => Promise<void>;
  retryLastAgentMessage: () => Promise<void>;
  confirmAgentAction: (token: string, decision: 'approved' | 'rejected') => Promise<void>;
  clearAgentChat: () => void;
  loadConversations: () => Promise<void>;
  openConversation: (sessionId: string) => Promise<void>;
  deleteConversation: (sessionId: string) => Promise<void>;
  submitSelfRecord: (data: PatientSelfRegister) => Promise<void>;
  openSelfRecordForm: () => void;
  closeSelfRecordForm: () => void;
  submitMessageFeedback: (data: {
    category: 'error' | 'suggestion';
    message: string;
    assistantMessage?: string | null;
    requestId?: string | null;
  }) => Promise<FeedbackResponse>;
  agentDrawerOpen: boolean;
  setAgentDrawerOpen: (open: boolean) => void;
}

const ClinicContext = createContext<ClinicContextType | undefined>(undefined);

const WELCOME_MESSAGE = 'سلام و وقت‌بخیر! من دستیار هوشمند کلینیک دندانپزشکی Dental Agent هستم. چطور می‌توانم در هماهنگی نوبت، بررسی ساعات خالی پزشک و امور درمانگاه به شما کمک کنم؟';

export const ClinicProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { currentUser, isAuthenticated, refreshUser } = useAuth();
  const [patients, setPatients] = useState<Patient[]>([]);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [services, setServices] = useState<DentalService[]>([]);
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [healthState, setHealthState] = useState<BackendHealth>(apiClient.getHealthState());
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [agentDrawerOpen, setAgentDrawerOpen] = useState(false);

  // Chat State — persisted server-side per (user, session) in backend mode.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [conversationTitle, setConversationTitle] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [recordFormRequired, setRecordFormRequired] = useState(false);
  const [selfRecordSubmitting, setSelfRecordSubmitting] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatHistoryMessage[]>([]);
  const [chatMessages, setChatMessages] = useState<UIChatMessage[]>([
    {
      id: 'welcome-msg',
      sender: 'agent',
      content: WELCOME_MESSAGE,
      timestamp: new Date().toISOString(),
    },
  ]);
  const [isAgentTyping, setIsAgentTyping] = useState(false);
  // Tracks whether any server-persisted turn exists for the active session,
  // so client history is only seeded to a truly brand-new conversation.
  const hasServerSession = useRef(false);

  const refreshHealth = useCallback(async () => {
    const health = await apiClient.checkHealth();
    setHealthState({ ...health });
  }, []);

  const WELCOME_NEW = 'گفتگوی جدید آغاز شد. چه کمکی در امور نوبت‌دهی و کلینیک از دست من برمی‌آید؟';

  const welcomeMessage = useCallback(
    (): UIChatMessage => ({
      id: `welcome-${Date.now()}`,
      sender: 'agent',
      content: WELCOME_NEW,
      timestamp: new Date().toISOString(),
    }),
    []
  );

  const refreshAll = useCallback(async () => {
    if (!isAuthenticated) return;
    setIsLoading(true);
    setErrorMessage(null);

    try {
      // 1. Fetch public/shared catalogs
      const [docList, srvList] = await Promise.all([
        apiClient.getDoctors(true),
        apiClient.getDentalServices(true),
      ]);
      setDoctors(docList);
      setServices(srvList);

      // 2. Fetch appointments scoped by role. An unlinked patient account
      // has no server-side record, so `/appointments/me` would always 403;
      // skip it and show the registration state instead.
      if (currentUser?.role === 'patient') {
        const hasRecord =
          (currentUser.patients?.length ?? 0) > 0 || !!currentUser.patient;
        if (!hasRecord) {
          setAppointments([]);
          setPatients([]);
        } else {
          try {
            const [myApps, ownPatients] = await Promise.all([
              apiClient.getMyAppointments(),
              apiClient.getPatients(),
            ]);
            setAppointments(myApps);
            setPatients(ownPatients);
          } catch (err: any) {
            if (String(err.message || '').includes('پیوست نشده')) {
              // A race/legacy response for a now-unlinked account is an
              // expected state, not a fatal dashboard error.
              setAppointments([]);
              setPatients([]);
            } else {
              throw err;
            }
          }
        }
      } else {
        const allApps = await apiClient.getAppointments();
        setAppointments(allApps);
      }

      // 3. Fetch patients if staff or admin
      if (currentUser?.role === 'admin' || currentUser?.role === 'receptionist') {
        const patList = await apiClient.getPatients();
        setPatients(patList);
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'خطا در دریافت اطلاعات از سرور');
    } finally {
      setIsLoading(false);
    }
  }, [currentUser, isAuthenticated]);

  useEffect(() => {
    refreshHealth();
    // Keep the connection indicator honest while the page stays open.
    const timer = window.setInterval(() => {
      if (!document.hidden) void refreshHealth();
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    if (isAuthenticated) {
      refreshAll();
      loadConversations().catch(() => undefined);
    } else {
      // Leaving the session must never leak chat rows into the next login.
      setSessionId(null);
      setConversationTitle(null);
      setConversations([]);
      setRecordFormRequired(false);
      setChatHistory([]);
      hasServerSession.current = false;
      setChatMessages([
        {
          id: 'welcome-msg',
          sender: 'agent',
          content: WELCOME_MESSAGE,
          timestamp: new Date().toISOString(),
        },
      ]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, currentUser?.phone, refreshAll]);

  useEffect(() => {
    if (!isAuthenticated || currentUser?.role !== 'patient') return;
    const count =
      currentUser.patients?.length ?? (currentUser.patient ? 1 : 0);
    setRecordFormRequired(count === 0);
  }, [
    isAuthenticated,
    currentUser?.role,
    currentUser?.patients?.length,
    currentUser?.patient?.id,
  ]);

  const createPatient = async (data: PatientCreate): Promise<Patient> => {
    const created = await apiClient.createPatient(data);
    await refreshAll();
    return created;
  };

  const bookAppointment = async (data: AppointmentCreate): Promise<Appointment> => {
    const created = await apiClient.createAppointment(data);
    await refreshAll();
    return created;
  };

  const cancelAppointment = async (id: number): Promise<void> => {
    await apiClient.cancelAppointment(id);
    await refreshAll();
  };

  const rescheduleAppointment = async (id: number, data: AppointmentReschedule): Promise<void> => {
    await apiClient.rescheduleAppointment(id, data);
    await refreshAll();
  };

  const getAvailableSlots = async (doctorId: number, date: string): Promise<string[]> => {
    return await apiClient.getAvailableSlots(doctorId, date);
  };

  // ---- Conversation history (server-side is the source of truth) ---------

  const loadConversations = useCallback(async () => {
    try {
      const rows = await apiClient.getAgentConversations();
      setConversations(rows);
    } catch {
      // History is an enhancement; a transient failure keeps the chat usable.
      setConversations([]);
    }
  }, []);

  const openConversation = async (targetSessionId: string) => {
    if (isAgentTyping) return;
    try {
      const detail = await apiClient.getAgentConversation(targetSessionId);
      setSessionId(detail.session_id);
      setConversationTitle(detail.title);
      hasServerSession.current = detail.messages.length > 0;
      setRecordFormRequired(false);
      // Client history mirrors the persisted turns so new sessions stay
      // coherent; the server keeps authority over model context regardless.
      setChatHistory(
        detail.messages.map((m) => ({ role: m.role, content: m.content }))
      );
      setChatMessages(
        detail.messages.map((m) => ({
          id: `${m.role}-${m.created_at}-${Math.random().toString(36).slice(2, 8)}`,
          sender: m.role === 'user' ? 'user' : 'agent',
          content: m.content,
          timestamp: m.created_at,
        }))
      );
      // An old conversation may already hold options server-side; the very
      // next «گزینه N» reply works, and the server re-renders them.
    } catch (err: any) {
      setErrorMessage(err.message || 'دریافت تاریخچه گفتگو ناکام ماند');
    }
  };

  const resetChat = useCallback(() => {
    setSessionId(null);
    setConversationTitle(null);
    setChatHistory([]);
    hasServerSession.current = false;
    setRecordFormRequired(false);
    setChatMessages([welcomeMessage()]);
  }, [welcomeMessage]);

  const deleteConversation = async (targetSessionId: string) => {
    try {
      await apiClient.deleteAgentConversation(targetSessionId);
      if (sessionId === targetSessionId) {
        resetChat();
      }
      setConversations((prev) => prev.filter((c) => c.session_id !== targetSessionId));
    } catch (err: any) {
      setErrorMessage(err.message || 'حذف گفتگو ناکام ماند');
    }
  };

  // ---- Agent chat execution ----------------------------------------------

  const sendAgentMessage = async (
    messageText: string,
    options: { appendUser?: boolean } = {}
  ) => {
    if (!messageText.trim()) return;

    const userMsg: UIChatMessage = {
      id: `usr-${Date.now()}`,
      sender: 'user',
      content: messageText.trim(),
      timestamp: new Date().toISOString(),
    };

    if (options.appendUser !== false) {
      setChatMessages((prev) => [...prev, userMsg]);
    }
    setIsAgentTyping(true);

    const isNewSession = !sessionId;
    // Server-side DB history is authoritative; the client list only seeds a
    // brand-new conversation the first time.
    const newHistory: ChatHistoryMessage[] = isNewSession
      ? chatHistory
      : [
          ...chatHistory,
          { role: 'user', content: messageText.trim() },
        ];

    try {
      const response: ChatResponse = await apiClient.sendAgentChat({
        message: messageText.trim(),
        session_id: sessionId,
        history: newHistory.slice(-10),
      });

      if (response.session_id) {
        setSessionId(response.session_id);
      }
      hasServerSession.current = true;
      if (response.conversation_title) {
        setConversationTitle(response.conversation_title);
      }

      setChatHistory([
        ...newHistory,
        { role: 'assistant', content: response.reply },
      ]);

      const agentMsg: UIChatMessage = {
        id: `agent-${Date.now()}`,
        sender: 'agent',
        content: response.reply,
        timestamp: new Date().toISOString(),
        confirmation_required: response.confirmation_required,
        confirmation_prompt: response.confirmation_prompt,
        confirmation_token: response.confirmation_token,
        suggested_appointments: response.suggested_appointments || response.slots,
        slots: response.slots,
        options: response.options || [],
        request_id: response.request_id ?? null,
      };

      setChatMessages((prev) => [...prev, agentMsg]);
      setRecordFormRequired(!!response.form_required);

      loadConversations().catch(() => undefined);
    } catch (err: any) {
      const detail =
        err?.message || 'ارتباط با دستیار برقرار نشد. لطفاً دوباره تلاش کنید.';
      setChatMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          sender: 'agent',
          content: detail,
          timestamp: new Date().toISOString(),
          error: detail,
          retryable: true,
        },
      ]);
    } finally {
      setIsAgentTyping(false);
    }
  };

  const retryLastAgentMessage = async () => {
    if (isAgentTyping) return;
    const lastUser = [...chatMessages].reverse().find((m) => m.sender === 'user');
    if (!lastUser) return;
    setChatMessages((prev) => prev.filter((m) => !m.retryable));
    // The failed turn was never added to chatHistory, so resend the same text
    // without appending a duplicate user bubble.
    await sendAgentMessage(lastUser.content, { appendUser: false });
  };

  const confirmAgentAction = async (token: string, decision: 'approved' | 'rejected') => {
    setIsAgentTyping(true);
    try {
      const response = await apiClient.sendAgentChat({
        message: decision === 'approved' ? 'تأیید شد' : 'انصراف',
        session_id: sessionId,
        confirmation: { token, decision },
      });

      // Mark matching confirmation card as confirmed/rejected
      setChatMessages((prev) =>
        prev.map((m) =>
          m.confirmation_token === token
            ? { ...m, confirmed: decision === 'approved', rejected: decision === 'rejected' }
            : m
        )
      );

      setChatMessages((prev) => [
        ...prev,
        {
          id: `conf-res-${Date.now()}`,
          sender: 'agent',
          content: response.reply,
          timestamp: new Date().toISOString(),
        },
      ]);

      if (decision === 'approved') {
        // Refresh live clinic appointments
        await refreshAll();
      }
      loadConversations().catch(() => undefined);
    } catch (err: any) {
      if (
        decision === 'approved' &&
        err instanceof ApiError &&
        isOutcomeUncertain(err.status)
      ) {
        // Never offer a blind retry: it could book twice. Show the truth instead.
        setChatMessages((prev) => [
          ...prev.map((m) =>
            m.confirmation_token === token ? { ...m, outcomeUnknown: true } : m
          ),
          {
            id: `unknown-${Date.now()}`,
            sender: 'agent' as const,
            content: OUTCOME_UNKNOWN_MESSAGE,
            timestamp: new Date().toISOString(),
          },
        ]);
        refreshAll().catch(() => undefined);
      } else {
        setChatMessages((prev) => [
          ...prev,
          {
            id: `err-${Date.now()}`,
            sender: 'agent',
            content: `تأیید انجام نشد: ${err.message}`,
            timestamp: new Date().toISOString(),
            error: err.message,
          },
        ]);
      }
    } finally {
      setIsAgentTyping(false);
    }
  };

  const clearAgentChat = () => {
    resetChat();
  };

  // ---- In-chat patient record registration (§4) --------------------------

  const submitSelfRecord = async (data: PatientSelfRegister): Promise<void> => {
    setSelfRecordSubmitting(true);
    try {
      await apiClient.registerSelfRecord(data);
      // Refresh the account profile so every view sees the new patient set.
      // The form disappears and the next chat turn can execute booking.
      setRecordFormRequired(false);
      setChatMessages((prev) => [
        ...prev,
        {
          id: `form-ok-${Date.now()}`,
          sender: 'agent',
          content:
            data.relation === 'self'
              ? 'پرونده شما با موفقیت ثبت و به حساب شما پیوست شد. حالا می‌توانید درخواست قبلی‌تان را ادامه دهید.'
              : `پرونده «${data.full_name}» با موفقیت به حساب شما اضافه شد. برای نوبت‌دهی، بیمار موردنظر را انتخاب کنید.`,
          timestamp: new Date().toISOString(),
        },
      ]);
      await refreshUser();
      await refreshAll();
    } catch (err: any) {
      setChatMessages((prev) => [
        ...prev,
        {
          id: `form-err-${Date.now()}`,
          sender: 'agent',
          content: `ثبت پرونده انجام نشد: ${err.message || 'خطای ناشناخته'}`,
          timestamp: new Date().toISOString(),
          error: err.message,
        },
      ]);
      throw err;
    } finally {
      setSelfRecordSubmitting(false);
    }
  };

  const openSelfRecordForm = () => {
    setRecordFormRequired(true);
  };

  const closeSelfRecordForm = () => {
    const count =
      currentUser?.patients?.length ?? (currentUser?.patient ? 1 : 0);
    if (count > 0) setRecordFormRequired(false);
  };

  const submitMessageFeedback: ClinicContextType['submitMessageFeedback'] = async ({
    category,
    message,
    assistantMessage,
    requestId,
  }) => {
    const lastUser = [...chatMessages]
      .reverse()
      .find((item) => item.sender === 'user');
    return await apiClient.submitFeedback({
      category,
      message,
      session_id: sessionId,
      page: typeof window === 'undefined' ? null : window.location.pathname,
      assistant_message: assistantMessage ?? null,
      user_message: lastUser?.content ?? null,
      request_id: requestId ?? null,
    });
  };

  return (
    <ClinicContext.Provider
      value={{
        patients,
        doctors,
        services,
        appointments,
        healthState,
        isLoading,
        errorMessage,
        refreshAll,
        refreshHealth,
        createPatient,
        bookAppointment,
        cancelAppointment,
        rescheduleAppointment,
        getAvailableSlots,
        chatMessages,
        isAgentTyping,
        sessionId,
        conversations,
        conversationTitle,
        recordFormRequired,
        selfRecordSubmitting,
        sendAgentMessage,
        retryLastAgentMessage,
        confirmAgentAction,
        clearAgentChat,
        loadConversations,
        openConversation,
        deleteConversation,
        submitSelfRecord,
        openSelfRecordForm,
        closeSelfRecordForm,
        submitMessageFeedback,
        agentDrawerOpen,
        setAgentDrawerOpen,
      }}
    >
      {children}
    </ClinicContext.Provider>
  );
};

export function useClinic() {
  const context = useContext(ClinicContext);
  if (!context) {
    throw new Error('useClinic must be used within a ClinicProvider');
  }
  return context;
}

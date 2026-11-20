import {
  MeResponse,
  TokenResponse,
  LoginRequest,
  OtpRequest,
  OtpRequestResponse,
  OtpVerifyRequest,
  OtpChannel,
  User,
  UserCreate,
  UserUpdate,
  Patient,
  PatientCreate,
  PatientUpdate,
  PatientSelfRegister,
  FeedbackCreate,
  FeedbackResponse,
  Doctor,
  DoctorCreate,
  DoctorUpdate,
  DoctorSchedule,
  DoctorScheduleCreate,
  DentalService,
  DentalServiceCreate,
  DentalServiceUpdate,
  Appointment,
  AppointmentCreate,
  AppointmentReschedule,
  ChatRequest,
  ChatResponse,
  ChatConversation,
  ChatConversationDetail,
  ReportsDashboard,
  BackendHealth,
  SystemHealth,
  UserPermissions,
  PermissionOverrideMap,
  AuditLogItem,
  ClinicalEntry,
  HealthRecordResponse,
  NotificationItem,
  NotificationsResponse,
  PatientHealthRecord,
  ToothCondition,
  WorklistItem,
  Prescription,
  TreatmentPlanItem,
  MedicationLine,
  VisitRatingItem,
  VisitRatingSummary,
} from '../types';
const STORAGE_KEYS = {
  AUTH_TOKEN: 'dental_agent_token',
};

/** jsdom-based dom-tests copy only window/document onto globalThis, so the
 *  token storage must degrade gracefully where localStorage is absent. */
function readStoredToken(): string | null {
  try {
    return typeof localStorage !== 'undefined'
      ? localStorage.getItem(STORAGE_KEYS.AUTH_TOKEN)
      : null;
  } catch {
    return null;
  }
}

function writeStoredToken(token: string | null): void {
  try {
    if (typeof localStorage === 'undefined') return;
    if (token) {
      localStorage.setItem(STORAGE_KEYS.AUTH_TOKEN, token);
    } else {
      localStorage.removeItem(STORAGE_KEYS.AUTH_TOKEN);
    }
  } catch {
    // Storage may be unavailable (private mode, quota); keep the session in memory.
  }
}

/** HTTP/network failure with the status code, so callers can tell a rejected
 *  session (401) from a server that is simply unreachable (status 0). */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

class ApiClient {
  private baseUrl: string;
  private token: string | null = null;
  private healthState: BackendHealth = {
    status: 'connecting',
    // Empty string = same origin: the UI is served by the FastAPI app itself
    // (at /app), so every API call goes to the same host with no CORS.
    serverUrl: '(same-origin)',
    lastChecked: new Date().toISOString(),
    openApiAvailable: false,
  };

  /** Default per-request budget. */
  private static DEFAULT_TIMEOUT_MS = 6000;
  /** Agentic chat runs a real (possibly local) LLM; give it a long leash. */
  private static AGENT_TIMEOUT_MS = 300_000;

  constructor() {
    // Same-origin by default: FastAPI serves this bundle at /app, so relative
    // fetches reach the API directly with no CORS. ``VITE_API_BASE_URL`` is a
    // build-time override for split deployments.
    this.baseUrl = ((import.meta.env.VITE_API_BASE_URL as string) || '').replace(/\/$/, '');
    this.token = readStoredToken();
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  public getBaseUrlLabel(): string {
    return this.baseUrl || '(same-origin)';
  }

  public setToken(token: string | null) {
    this.token = token;
    writeStoredToken(token);
  }

  public getToken(): string | null {
    return this.token;
  }

  public getHealthState(): BackendHealth {
    return this.healthState;
  }

  /** Admin-only operational summary for the «سلامت سامانه» page. */
  public async getSystemHealth(): Promise<SystemHealth> {
    return this.request<SystemHealth>('/system/health', { timeoutMs: 8000 });
  }

  public async checkHealth(): Promise<BackendHealth> {
    const startTime = performance.now();
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1500);

      const response = await fetch(`${this.baseUrl}/health`, {
        method: 'GET',
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      const latencyMs = Math.round(performance.now() - startTime);
      this.healthState = {
        status: response.ok ? 'connected' : 'disconnected',
        serverUrl: this.getBaseUrlLabel(),
        latencyMs,
        lastChecked: new Date().toISOString(),
        openApiAvailable: true,
      };
    } catch {
      this.healthState = {
        status: 'disconnected',
        serverUrl: this.getBaseUrlLabel(),
        lastChecked: new Date().toISOString(),
        openApiAvailable: false,
      };
    }
    return this.healthState;
  }

  /**
   * Central HTTP Fetcher adhering to OpenAPI specifications
   * Throws clean Error on HTTP error without swallowing or substituting mock data.
   */
  private async request<T>(
    endpoint: string,
    options: RequestInit & { timeoutMs?: number } = {}
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const controller = new AbortController();
    let timedOut = false;
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, options.timeoutMs ?? ApiClient.DEFAULT_TIMEOUT_MS);

    try {
      const { timeoutMs: _ignored, ...fetchOptions } = options;
      const res = await fetch(url, {
        ...fetchOptions,
        headers,
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) {
        let errorDetail = `خطای سرور: کد وضعیت ${res.status}`;
        try {
          const body = await res.json();
          if (typeof body.detail === 'string') {
            errorDetail = body.detail;
          } else if (Array.isArray(body.detail)) {
            errorDetail = body.detail.map((d: any) => d.msg || JSON.stringify(d)).join('، ');
          } else if (body.error && typeof body.error.message === 'string') {
            // Catalogued FastAPI errors arrive as { error: { code, message } }.
            errorDetail = body.error.message;
          } else if (body.message) {
            errorDetail = body.message;
          }
        } catch {
          // keep status error
        }
        throw new ApiError(errorDetail, res.status);
      }

      // Check if 204 No Content
      if (res.status === 204) {
        return undefined as unknown as T;
      }

      return (await res.json()) as T;
    } catch (err: any) {
      clearTimeout(timeout);
      if (err instanceof ApiError) throw err;
      if (err.name === 'AbortError' || timedOut || err.name === 'TimeoutError') {
        throw new ApiError('پاسخی از سرور دریافت نشد. چند لحظه بعد دوباره تلاش کنید.', 0);
      }
      throw new ApiError('ارتباط با سرور برقرار نشد. اتصال اینترنت را بررسی و دوباره تلاش کنید.', 0);
    }
  }

  // ==========================================
  // 1. Authentication Endpoints
  // ==========================================

  public async login(data: LoginRequest): Promise<TokenResponse> {
    const res = await this.request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    return res;
  }

  /**
   * Staff-portal door: rejects patient accounts even with a valid password,
   * keeping the clinic back-office a separate entry point from the patient app.
   */
  public async staffLogin(data: Omit<LoginRequest, 'portal'>): Promise<TokenResponse> {
    const res = await this.request<TokenResponse>('/auth/staff/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    return res;
  }

  public async requestOtp(data: OtpRequest): Promise<OtpRequestResponse> {
    return await this.request<OtpRequestResponse>('/auth/otp/request', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  /** Which channel delivers patient OTP codes; configuration-level only. */
  public async getOtpChannel(): Promise<OtpChannel> {
    return await this.request<OtpChannel>('/auth/otp/channel', {
      method: 'GET',
    });
  }

  public async verifyOtp(data: OtpVerifyRequest): Promise<TokenResponse> {
    const res = await this.request<TokenResponse>('/auth/otp/verify', {
      method: 'POST',
      body: JSON.stringify(data),
    });
    this.setToken(res.access_token);
    return res;
  }

  public async getMe(): Promise<MeResponse> {
    return await this.request<MeResponse>('/auth/me', {
      method: 'GET',
    });
  }

  // ==========================================
  // 2. Users Management (Admin)
  // ==========================================

  public async getUsers(): Promise<User[]> {
    return await this.request<User[]>('/users/', { method: 'GET' });
  }

  public async createUser(data: UserCreate): Promise<User> {
    return await this.request<User>('/users/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async updateUser(userId: number, data: UserUpdate): Promise<User> {
    return await this.request<User>(`/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  public async deleteStaffUser(userId: number): Promise<void> {
    return await this.request<void>(`/users/${userId}`, { method: 'DELETE' });
  }

  /** Effective permission matrix of one staff account (admin only). */
  public async getStaffPermissions(userId: number): Promise<UserPermissions> {
    return await this.request<UserPermissions>(`/users/${userId}/permissions`, {
      method: 'GET',
    });
  }

  /** Replace one staff account's allow/deny overrides (admin only). */
  public async updateStaffPermissions(
    userId: number,
    overrides: PermissionOverrideMap
  ): Promise<UserPermissions> {
    return await this.request<UserPermissions>(`/users/${userId}/permissions`, {
      method: 'PUT',
      body: JSON.stringify({ overrides }),
    });
  }

  /** Append-only staff audit trail (admin only). */
  public async getAuditLogs(options: { limit?: number; action?: string } = {}): Promise<AuditLogItem[]> {
    const params = new URLSearchParams();
    if (options.limit) params.set('limit', String(options.limit));
    if (options.action) params.set('action', options.action);
    const query = params.toString() ? `?${params.toString()}` : '';
    return await this.request<AuditLogItem[]>(`/audit-logs/${query}`, { method: 'GET' });
  }

  // ==========================================
  // 3. Patients Endpoints
  // ==========================================

  public async getPatients(search?: string): Promise<Patient[]> {
    const q = search ? `?search=${encodeURIComponent(search)}` : '';
    return await this.request<Patient[]>(`/patients/${q}`, { method: 'GET' });
  }

  public async createPatient(data: PatientCreate): Promise<Patient> {
    return await this.request<Patient>('/patients/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async getPatient(patientId: number): Promise<Patient> {
    return await this.request<Patient>(`/patients/${patientId}`, { method: 'GET' });
  }

  public async updatePatient(patientId: number, data: PatientUpdate): Promise<Patient> {
    return await this.request<Patient>(`/patients/${patientId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  /**
   * Self-service initial record creation for the authenticated patient
   * account (POST /patients/me). The link is established server-side from
   * the token; the phone must match the account phone.
   */
  public async registerSelfRecord(data: PatientSelfRegister): Promise<Patient> {
    return await this.request<Patient>('/patients/me', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async deletePatient(patientId: number): Promise<void> {
    return await this.request<void>(`/patients/${patientId}`, { method: 'DELETE' });
  }

  public async linkPatientUser(patientId: number, phone: string): Promise<Patient> {
    return await this.request<Patient>(`/patients/${patientId}/link-user`, {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
  }

  /**
   * Staff-only filtering by server-derived record status. A patient-role
   * caller always receives just their own record from the server, so the
   * parameter is only forwarded for staff dashboards.
   */
  public async getPatientsFiltered(
    options: { search?: string; recordStatus?: 'complete' | 'incomplete' } = {}
  ): Promise<Patient[]> {
    const params = new URLSearchParams();
    if (options.search) params.set('search', options.search);
    if (options.recordStatus) params.set('record_status', options.recordStatus);
    const query = params.toString() ? `?${params.toString()}` : '';
    return await this.request<Patient[]>(`/patients/${query}`, { method: 'GET' });
  }

  // ==========================================
  // 3b. Agent Conversation History (server-persisted)
  // ==========================================

  public async getAgentConversations(): Promise<ChatConversation[]> {
    return await this.request<ChatConversation[]>('/agent/conversations', { method: 'GET' });
  }

  public async createAgentConversation(): Promise<ChatConversation> {
    return await this.request<ChatConversation>('/agent/conversations', {
      method: 'POST',
    });
  }

  public async getAgentConversation(sessionId: string): Promise<ChatConversationDetail> {
    return await this.request<ChatConversationDetail>(
      `/agent/conversations/${encodeURIComponent(sessionId)}`,
      { method: 'GET' }
    );
  }

  public async deleteAgentConversation(sessionId: string): Promise<void> {
    await this.request<void>(
      `/agent/conversations/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' }
    );
    return;
  }

  // ==========================================
  // 3c. Clinic Reports (admin dashboard)
  // ==========================================

  public async getReportsDashboard(): Promise<ReportsDashboard> {
    return await this.request<ReportsDashboard>('/reports/dashboard', { method: 'GET' });
  }

  // ==========================================
  // 4. Doctors Endpoints
  // ==========================================

  public async getDoctors(activeOnly = true): Promise<Doctor[]> {
    return await this.request<Doctor[]>(`/doctors/?active_only=${activeOnly}`, {
      method: 'GET',
    });
  }

  public async createDoctor(data: DoctorCreate): Promise<Doctor> {
    return await this.request<Doctor>('/doctors/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async getDoctor(doctorId: number): Promise<Doctor> {
    return await this.request<Doctor>(`/doctors/${doctorId}`, { method: 'GET' });
  }

  /** Admin-only full record (phone included) for the management edit form. */
  public async getDoctorForManagement(doctorId: number): Promise<Doctor> {
    return await this.request<Doctor>(`/doctors/${doctorId}/manage`, { method: 'GET' });
  }

  /** Admin-only management listing: phone + account/service links in one call. */
  public async listDoctorsForManagement(): Promise<Doctor[]> {
    return await this.request<Doctor[]>('/doctors/manage', { method: 'GET' });
  }

  public async updateDoctor(doctorId: number, data: DoctorUpdate): Promise<Doctor> {
    return await this.request<Doctor>(`/doctors/${doctorId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  public async getDoctorServices(doctorId: number): Promise<DentalService[]> {
    return await this.request<DentalService[]>(`/doctors/${doctorId}/services`, {
      method: 'GET',
    });
  }

  public async linkDoctorUser(doctorId: number, phone: string): Promise<Doctor> {
    return await this.request<Doctor>(`/doctors/${doctorId}/link-user`, {
      method: 'POST',
      body: JSON.stringify({ phone }),
    });
  }

  // ==========================================
  // 5. Doctor Schedules
  // ==========================================

  public async createDoctorSchedule(data: DoctorScheduleCreate): Promise<DoctorSchedule> {
    return await this.request<DoctorSchedule>('/doctor-schedules/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async getDoctorSchedules(doctorId: number): Promise<DoctorSchedule[]> {
    return await this.request<DoctorSchedule[]>(`/doctor-schedules/${doctorId}`, {
      method: 'GET',
    });
  }

  public async updateDoctorSchedule(
    scheduleId: number,
    data: { day_of_week: number; start_time: string; end_time: string; slot_duration_minutes: number; is_active: boolean }
  ): Promise<DoctorSchedule> {
    return await this.request<DoctorSchedule>(`/doctor-schedules/${scheduleId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  public async deleteDoctorSchedule(scheduleId: number): Promise<void> {
    return await this.request<void>(`/doctor-schedules/${scheduleId}`, { method: 'DELETE' });
  }

  // ==========================================
  // 6. Dental Services Endpoints
  // ==========================================

  public async getDentalServices(activeOnly = true): Promise<DentalService[]> {
    return await this.request<DentalService[]>(`/dental-services/?active_only=${activeOnly}`, {
      method: 'GET',
    });
  }

  public async createDentalService(data: DentalServiceCreate): Promise<DentalService> {
    return await this.request<DentalService>('/dental-services/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async updateDentalService(
    serviceId: number,
    data: DentalServiceUpdate
  ): Promise<DentalService> {
    return await this.request<DentalService>(`/dental-services/${serviceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  public async deleteDentalService(serviceId: number): Promise<void> {
    return await this.request<void>(`/dental-services/${serviceId}`, { method: 'DELETE' });
  }

  public async getServiceDoctors(serviceId: number): Promise<Doctor[]> {
    return await this.request<Doctor[]>(`/dental-services/${serviceId}/doctors`, {
      method: 'GET',
    });
  }

  // ==========================================
  // 7. Appointments Endpoints
  // ==========================================

  public async getAppointments(filters?: {
    doctor_id?: number;
    patient_id?: number;
    appointment_date?: string;
    status?: string;
  }): Promise<Appointment[]> {
    const params = new URLSearchParams();
    if (filters?.doctor_id) params.set('doctor_id', String(filters.doctor_id));
    if (filters?.patient_id) params.set('patient_id', String(filters.patient_id));
    if (filters?.appointment_date) params.set('appointment_date', filters.appointment_date);
    if (filters?.status) params.set('status', filters.status);
    const query = params.toString() ? `?${params.toString()}` : '';
    return await this.request<Appointment[]>(`/appointments/${query}`, { method: 'GET' });
  }

  public async getMyAppointments(): Promise<Appointment[]> {
    return await this.request<Appointment[]>('/appointments/me', { method: 'GET' });
  }

  /** Today's front-desk worklist (optionally another Jalali day). */
  public async getDayWorklist(options?: {
    appointment_date?: string;
    doctor_id?: number;
  }): Promise<WorklistItem[]> {
    const params = new URLSearchParams();
    if (options?.appointment_date) params.set('appointment_date', options.appointment_date);
    if (options?.doctor_id) params.set('doctor_id', String(options.doctor_id));
    const query = params.toString() ? `?${params.toString()}` : '';
    return await this.request<WorklistItem[]>(`/appointments/day${query}`, {
      method: 'GET',
    });
  }

  /** Patient arrival: assigns the daily queue number. */
  public async checkInAppointment(appointmentId: number): Promise<WorklistItem> {
    return await this.request<WorklistItem>(`/appointments/${appointmentId}/check-in`, {
      method: 'POST',
    });
  }

  public async startAppointment(appointmentId: number): Promise<WorklistItem> {
    return await this.request<WorklistItem>(`/appointments/${appointmentId}/start`, {
      method: 'POST',
    });
  }

  public async completeAppointment(appointmentId: number): Promise<WorklistItem> {
    return await this.request<WorklistItem>(`/appointments/${appointmentId}/complete`, {
      method: 'POST',
    });
  }

  public async markAppointmentNoShow(appointmentId: number): Promise<WorklistItem> {
    return await this.request<WorklistItem>(`/appointments/${appointmentId}/no-show`, {
      method: 'POST',
    });
  }

  public async getPatientAppointments(patientId: number): Promise<Appointment[]> {
    return await this.request<Appointment[]>(`/appointments/patient/${patientId}`, {
      method: 'GET',
    });
  }

  public async createAppointment(data: AppointmentCreate): Promise<Appointment> {
    return await this.request<Appointment>('/appointments/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async cancelAppointment(appointmentId: number): Promise<Appointment> {
    return await this.request<Appointment>(`/appointments/${appointmentId}/cancel`, {
      method: 'POST',
    });
  }

  public async rescheduleAppointment(
    appointmentId: number,
    data: AppointmentReschedule
  ): Promise<Appointment> {
    return await this.request<Appointment>(`/appointments/${appointmentId}/reschedule`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async getAvailableSlots(
    doctorId: number,
    appointmentDate: string
  ): Promise<string[]> {
    // The backend returns { doctor_id, date, available_slots: [...] }.
    const payload = await this.request<unknown>(
      `/appointments/available-slots/?doctor_id=${doctorId}&appointment_date=${encodeURIComponent(
        appointmentDate
      )}`,
      { method: 'GET' }
    );
    const slots = Array.isArray(payload)
      ? payload
      : ((payload as { available_slots?: unknown[] })?.available_slots ?? []);
    if (!Array.isArray(slots)) return [];
    return slots.map((s: any) =>
      typeof s === 'string' ? (s.length > 5 ? s.slice(0, 5) : s) : (s.appointment_time || s.time || '').slice(0, 5)
    );
  }

  // ==========================================
  // 8. Agentic AI Chat Endpoint
  // ==========================================

  public async sendAgentChat(data: ChatRequest): Promise<ChatResponse> {
    return await this.request<ChatResponse>('/agent/chat', {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: ApiClient.AGENT_TIMEOUT_MS,
    });
  }

  public async submitFeedback(data: FeedbackCreate): Promise<FeedbackResponse> {
    return await this.request<FeedbackResponse>('/feedback/', {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: 20_000,
    });
  }

  // ==========================================
  // 9. Health Record (patient portal v3)
  // ==========================================

  /** Patient self-view: every owned record with entries + tooth chart. */
  public async getMyHealthRecord(): Promise<HealthRecordResponse> {
    return await this.request<HealthRecordResponse>('/clinical/me', {
      method: 'GET',
    });
  }

  /** Staff read access to one patient's clinical record. */
  public async getClinicalRecord(patientId: number): Promise<PatientHealthRecord> {
    return await this.request<PatientHealthRecord>(
      `/clinical/patients/${patientId}`,
      { method: 'GET' }
    );
  }

  /** Append a treatment note, allergy alert or clinical note (admin/doctor). */
  public async createClinicalEntry(
    patientId: number,
    data: {
      kind: 'treatment' | 'allergy' | 'note';
      title: string;
      body?: string | null;
      tooth_fdi?: number | null;
      appointment_id?: number | null;
    }
  ): Promise<ClinicalEntry> {
    return await this.request<ClinicalEntry>(
      `/clinical/patients/${patientId}/entries`,
      {
        method: 'POST',
        body: JSON.stringify(data),
      }
    );
  }

  /** Set one tooth's chart status (admin/doctor). */
  public async setToothStatus(
    patientId: number,
    toothFdi: number,
    status: ToothCondition,
    note?: string | null
  ): Promise<void> {
    await this.request<void>(`/clinical/patients/${patientId}/teeth/${toothFdi}`, {
      method: 'PUT',
      body: JSON.stringify({ status, note: note ?? null }),
    });
    return;
  }

  /** Write a structured prescription (admin/doctor). */
  public async createPrescription(
    patientId: number,
    data: {
      items: MedicationLine[];
      notes?: string | null;
      appointment_id?: number | null;
      doctor_id?: number | null;
    }
  ): Promise<Prescription> {
    return await this.request<Prescription>(
      `/clinical/patients/${patientId}/prescriptions`,
      { method: 'POST', body: JSON.stringify(data) }
    );
  }

  /** Add one planned procedure to the treatment roadmap (admin/doctor). */
  public async createTreatmentPlanItem(
    patientId: number,
    data: {
      title: string;
      tooth_fdi?: number | null;
      notes?: string | null;
      doctor_id?: number | null;
    }
  ): Promise<TreatmentPlanItem> {
    return await this.request<TreatmentPlanItem>(
      `/clinical/patients/${patientId}/plan-items`,
      { method: 'POST', body: JSON.stringify(data) }
    );
  }

  /** Move a plan item through planned → in progress → completed. */
  public async updateTreatmentPlanItem(
    patientId: number,
    itemId: number,
    data: { status: TreatmentPlanItem['status']; notes?: string | null }
  ): Promise<TreatmentPlanItem> {
    return await this.request<TreatmentPlanItem>(
      `/clinical/patients/${patientId}/plan-items/${itemId}`,
      { method: 'PUT', body: JSON.stringify(data) }
    );
  }

  // ==========================================
  // 10. Notifications (all roles)
  // ==========================================

  public async getNotifications(): Promise<NotificationsResponse> {
    return await this.request<NotificationsResponse>('/notifications/me', {
      method: 'GET',
    });
  }

  public async markNotificationRead(notificationId: number): Promise<void> {
    await this.request<void>(`/notifications/${notificationId}/read`, {
      method: 'POST',
    });
    return;
  }

  public async markAllNotificationsRead(): Promise<{ updated: number }> {
    return await this.request<{ updated: number }>('/notifications/read-all', {
      method: 'POST',
    });
  }

  // ==========================================
  // 11. Profile self-service + visit ratings
  // ==========================================

  /** Rename own account (any active role). Phone/role stay protected. */
  public async updateMyProfile(data: { full_name: string }): Promise<User> {
    return await this.request<User>('/users/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  public async submitVisitRating(data: {
    appointment_id: number;
    rating: number;
    comment?: string | null;
  }): Promise<VisitRatingItem> {
    return await this.request<VisitRatingItem>('/visit-ratings/', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  public async getMyVisitRatings(): Promise<VisitRatingItem[]> {
    return await this.request<VisitRatingItem[]>('/visit-ratings/mine', {
      method: 'GET',
    });
  }

  public async getVisitRatingSummary(): Promise<VisitRatingSummary> {
    return await this.request<VisitRatingSummary>('/visit-ratings/summary', {
      method: 'GET',
    });
  }

}

export const apiClient = new ApiClient();

/**
 * Dental Agent - Strict OpenAPI 3.1.0 Domain Types
 * Exactly matches /public/assets/aistudio/openapi_utf8.json
 */

export type UserRole = 'admin' | 'receptionist' | 'doctor' | 'patient';

export interface MeLinkInfo {
  id: number;
  full_name: string;
  is_account_holder?: boolean;
}

export interface MeResponse {
  full_name: string;
  phone: string;
  role: UserRole;
  is_active: boolean;
  /** Primary account-holder record (backwards compatible). */
  patient?: MeLinkInfo | null;
  /** Every patient record saved under this account. */
  patients?: MeLinkInfo[];
  doctor?: MeLinkInfo | null;
}

export interface TokenResponse {
  access_token: string;
  token_type?: string;
}

export interface LoginRequest {
  phone: string;
  password: string;
  /** Which portal the caller used: patients and staff have separate doors. */
  portal?: 'patient' | 'staff' | null;
}

export interface OtpRequest {
  phone: string;
}

export interface OtpRequestResponse {
  status: string;
  message: string;
  dev_otp?: string | null;
  dev_notice?: string | null;
}

/** Public descriptor of the OTP delivery channel. Config-level only: it names
 *  the provider and (for Bale) the bot's public deep link, never any account
 *  or phone state. */
export interface OtpChannel {
  provider: string;
  bot_username?: string | null;
  bot_url?: string | null;
}

export interface OtpVerifyRequest {
  phone: string;
  code: string;
}

export interface User {
  id: number;
  full_name: string;
  phone: string;
  role: UserRole;
  is_active: boolean;
  /** Naive UTC ISO timestamps rendered as Jalali in the staff panel. */
  created_at?: string | null;
  last_login_at?: string | null;
  /** Per-account allow/deny overrides applied on top of the role matrix. */
  permission_overrides?: Record<string, 'allow' | 'deny'> | null;
}

export interface UserCreate {
  full_name: string;
  phone: string;
  password: string;
  role: UserRole;
}

export interface UserUpdate {
  full_name?: string | null;
  role?: UserRole | null;
  is_active?: boolean | null;
  password?: string | null;
}

/** One row of the admin permission matrix for a single staff account. */
export interface PermissionActionState {
  action: string;
  role_default: boolean;
  override: 'allow' | 'deny' | null;
  effective: boolean;
}

export interface UserPermissions {
  user_id: number;
  role: UserRole;
  actions: PermissionActionState[];
}

export type PermissionOverrideMap = Record<string, 'allow' | 'deny'>;

/** One row of the append-only staff audit trail. */
export interface AuditLogItem {
  id: number;
  actor_user_id?: number | null;
  actor_phone?: string | null;
  action: string;
  target_user_id?: number | null;
  target_label?: string | null;
  detail?: Record<string, unknown> | null;
  created_at?: string | null;
}

export type RecordStatus = 'complete' | 'incomplete';

export interface Patient {
  id: number;
  // Nullable only for legacy rows; every current registration requires it.
  national_id: string | null;
  full_name: string;
  phone: string;
  /** True for the account holder record within a multi-patient account. */
  is_account_holder?: boolean;
  // Server-derived record completeness ('complete' | 'incomplete').
  record_status: RecordStatus;
  /** Linked patient-account id (null = the record has no app login yet). */
  user_id?: number | null;
}

export interface PatientCreate {
  national_id: string;
  full_name: string;
  phone: string;
}

export interface PatientUpdate {
  full_name: string;
  phone: string;
  // Optional staff completion of an initial record (null = not provided).
  national_id?: string | null;
}

export interface PatientSelfRegister {
  full_name: string;
  // For relation='self' this must match the account phone; for 'other' it
  // must be the dependent's unique phone. Verified server-side.
  phone: string;
  national_id: string;
  relation: 'self' | 'other';
}

export interface FeedbackCreate {
  category: 'error' | 'suggestion';
  message: string;
  session_id?: string | null;
  page?: string | null;
  assistant_message?: string | null;
  user_message?: string | null;
  request_id?: string | null;
}

export interface FeedbackResponse {
  id: number;
  status: string;
  message: string;
}

export interface Doctor {
  id: number;
  full_name: string;
  specialty: string;
  is_active: boolean;
  phone?: string; // Only in the admin management responses, never the catalog
  /** Linked staff account id (admin management responses only). */
  user_id?: number | null;
  /** Offered services (admin management responses only). */
  service_ids?: number[];
}

export interface DoctorCreate {
  full_name: string;
  specialty: string;
  phone: string;
  service_ids?: number[];
}

export interface DoctorUpdate {
  full_name: string;
  specialty: string;
  phone: string;
  is_active: boolean;
  service_ids?: number[];
}

export interface DoctorSchedule {
  id: number;
  doctor_id: number;
  day_of_week: number; // 0 = Saturday or Monday depending on backend convention
  start_time: string; // HH:MM:SS
  end_time: string;   // HH:MM:SS
  slot_duration_minutes: number;
  is_active: boolean;
}

export interface DoctorScheduleCreate {
  doctor_id: number;
  day_of_week: number;
  start_time: string;
  end_time: string;
  slot_duration_minutes?: number;
}

export interface DentalService {
  id: number;
  name: string;
  description?: string | null;
  is_active: boolean;
}

export interface DentalServiceCreate {
  name: string;
  description?: string | null;
}

export interface DentalServiceUpdate {
  name: string;
  is_active: boolean;
  description?: string | null;
}

export type AppointmentStatus =
  | 'scheduled'
  | 'confirmed'
  | 'in_progress'
  | 'completed'
  | 'cancelled'
  | 'no_show'
  | 'rescheduled'
  | string;

export interface Appointment {
  id: number;
  patient_id: number;
  doctor_id: number;
  service_id: number;
  appointment_date: string; // YYYY-MM-DD
  appointment_time: string; // HH:MM:SS or HH:MM
  status: AppointmentStatus;
  reason?: string | null;
  patient_name: string;
  doctor_name: string;
  service_name: string;
  /** Front-desk flow markers (null until the step happens). */
  checked_in_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  queue_number?: number | null;
}

/** One row of the reception worklist for a clinic day. */
export interface WorklistItem extends Appointment {
  patient_phone: string;
  is_late: boolean;
  /** Minutes spent in the waiting room (server-computed, Tehran clock). */
  waiting_minutes?: number | null;
}

export interface AppointmentCreate {
  doctor_id: number;
  service_id: number;
  appointment_date: string;
  appointment_time: string;
  patient_id?: number | null;
  national_id?: string | null;
  full_name?: string | null;
  phone?: string | null;
  reason?: string | null;
}

export interface AppointmentReschedule {
  appointment_date: string;
  appointment_time: string;
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatConfirmation {
  token: string;
  decision: 'approved' | 'rejected';
}

export interface ChatSuggestedAppointment {
  doctor_id: number;
  doctor_name: string;
  service_id: number;
  service_name: string;
  appointment_date: string;
  appointment_time: string;
}

export interface ChatOptionItem {
  /** 1-based option number the client sends back as «گزینه N» (server-resolved). */
  index: number;
  kind: 'service' | 'doctor' | 'slot_time' | 'appointment' | 'patient';
  label: string;
  patient_id?: number | null;
  is_account_holder?: boolean | null;
  doctor_id?: number | null;
  doctor_name?: string | null;
  service_id?: number | null;
  service_name?: string | null;
  appointment_date?: string | null;
  appointment_time?: string | null;
  specialty?: string | null;
  description?: string | null;
}

export interface ChatConversation {
  session_id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface ChatHistoryEntry extends ChatHistoryMessage {
  created_at: string;
}

export interface ChatConversationDetail extends ChatConversation {
  messages: ChatHistoryEntry[];
}

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  history?: ChatHistoryMessage[];
  confirmation?: ChatConfirmation | null;
}

export interface ChatResponse {
  reply: string;
  confirmation_required: boolean;
  confirmation_prompt?: string | null;
  confirmation_token?: string | null;
  suggested_appointments?: ChatSuggestedAppointment[];
  slots?: ChatSuggestedAppointment[];
  // Selectable cards of the conversation's active option set.
  options?: ChatOptionItem[];
  // Server-side flag: show the in-chat patient-record registration form.
  form_required?: boolean;
  conversation_title?: string | null;
  session_id: string;
  request_id?: string | null;
}

export interface DoctorAppointmentStat {
  doctor_id: number;
  doctor_name: string;
  scheduled_count: number;
}

export interface ClinicAppointmentsReport {
  generated_at: string;
  window_days: number;
  today_appointments: number;
  upcoming_scheduled: number;
  upcoming_cancelled: number;
  doctor_load: DoctorAppointmentStat[];
}

export interface ClinicOverviewStats {
  generated_at: string;
  patients_total: number;
  patients_incomplete: number;
  doctors_total: number;
  services_total: number;
  appointments_upcoming: number;
  appointments_today: number;
  cancellations_30d: number;
}

export interface ReportsDashboard {
  overview: ClinicOverviewStats;
  appointments: ClinicAppointmentsReport;
}

export interface BackendHealth {
  status: 'connected' | 'disconnected' | 'connecting';
  serverUrl: string;
  latencyMs?: number;
  version?: string;
  lastChecked: string;
  openApiAvailable: boolean;
}

/** Admin-only operational summary. Provider names only; never keys or URLs. */
export interface SystemHealth {
  status: 'ok' | 'degraded';
  version: string;
  uptime_seconds: number;
  database: 'ok' | 'unavailable';
  sms_provider: string;
  assistant_provider: string;
  assistant_configured: boolean;
}

// ==========================================
// Patient portal v3: health record, notifications, ratings
// ==========================================

export type ClinicalEntryKind = 'treatment' | 'allergy' | 'note';

export interface ClinicalEntry {
  id: number;
  patient_id: number;
  doctor_id: number | null;
  doctor_name?: string | null;
  appointment_id: number | null;
  kind: ClinicalEntryKind;
  tooth_fdi: number | null;
  title: string;
  body?: string | null;
  created_by_name?: string | null;
  created_at: string;
}

export type ToothCondition = 'healthy' | 'treated' | 'needs_treatment' | 'extracted';

export interface ToothStatus {
  tooth_fdi: number;
  status: ToothCondition;
  note?: string | null;
  updated_at?: string | null;
}

export interface MedicationLine {
  name: string;
  dose?: string | null;
  frequency?: string | null;
  duration?: string | null;
}

export interface Prescription {
  id: number;
  patient_id: number;
  doctor_id: number | null;
  doctor_name?: string | null;
  appointment_id: number | null;
  items: MedicationLine[];
  notes?: string | null;
  created_by_name?: string | null;
  created_at: string;
  cancelled_at?: string | null;
}

export type TreatmentPlanStatus =
  | 'planned'
  | 'in_progress'
  | 'completed'
  | 'cancelled';

export interface TreatmentPlanItem {
  id: number;
  patient_id: number;
  doctor_id: number | null;
  doctor_name?: string | null;
  tooth_fdi: number | null;
  title: string;
  status: TreatmentPlanStatus;
  notes?: string | null;
  created_by_name?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PatientHealthRecord {
  patient: {
    id: number;
    full_name: string;
    national_id: string | null;
    phone: string;
    is_account_holder: boolean;
    record_status: string;
  };
  entries: ClinicalEntry[];
  teeth: ToothStatus[];
  prescriptions?: Prescription[];
  plan_items?: TreatmentPlanItem[];
}

export interface HealthRecordResponse {
  records: PatientHealthRecord[];
}

export type NotificationKind =
  | 'appointment_booked'
  | 'appointment_cancelled'
  | 'appointment_rescheduled'
  | 'reminder'
  | 'clinical_entry'
  | 'system';

export interface NotificationItem {
  id: number;
  kind: NotificationKind;
  title: string;
  body?: string | null;
  appointment_id?: number | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  unread_count: number;
}

export interface VisitRatingItem {
  id: number;
  appointment_id: number;
  patient_id: number;
  rating: number;
  comment?: string | null;
  created_at: string;
}

export interface VisitRatingSummary {
  count: number;
  average: number;
  average_30d: number;
}

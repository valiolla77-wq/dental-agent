import React, { useMemo, useState } from 'react';
import { useClinic } from '../../context/ClinicContext';
import { useAuth } from '../../context/AuthContext';
import { Patient } from '../../types';
import { Button } from '../common/Button';
import { EmptyState } from '../common/EmptyState';
import { PatientDossierModal } from './PatientDossierModal';
import { NewPatientModal } from './NewPatientModal';
import {
  DeletePatientModal,
  EditPatientModal,
  LinkPatientAccountModal,
} from './PatientManageModals';
import { RecordStatusBadge } from '../common/Badge';
import { formatToJalali, toPersianDigits, todayJalaliString } from '../../utils/persianDate';
import { isUpcoming, lastVisitForPatient, nextVisitForPatient } from '../../utils/analytics';
import { PageHeader, SectionCard, StatCard } from '../common/ui';
import {
  UserPlus,
  Search,
  Users,
  UserCheck,
  FileWarning,
  CalendarCheck2,
  ChevronLeft,
  Link2,
  Pencil,
  Trash2,
} from 'lucide-react';

type RecordFilter = 'all' | 'complete' | 'incomplete';
type PatientDialog = 'edit' | 'link' | 'delete';

export const PatientsView: React.FC = () => {
  const { patients, appointments, refreshAll } = useClinic();
  const { hasPerm, currentUser } = useAuth();
  const [search, setSearch] = useState('');
  const [recordFilter, setRecordFilter] = useState<RecordFilter>('all');
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [newPatientOpen, setNewPatientOpen] = useState(false);
  const [dialog, setDialog] = useState<{ kind: PatientDialog; patient: Patient } | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const isAdmin = currentUser?.role === 'admin';

  const today = todayJalaliString();

  const assignedPatients = useMemo(
    () =>
      patients.map((patient) => {
        const rows = appointments.filter(
          (appointment) =>
            appointment.patient_id === patient.id ||
            appointment.patient_name === patient.full_name
        );
        return {
          patient,
          visitCount: rows.filter((appointment) => appointment.status !== 'cancelled').length,
          completedCount: rows.filter((appointment) => appointment.status === 'completed').length,
          last: lastVisitForPatient(appointments, patient, today),
          next: nextVisitForPatient(appointments, patient, today),
          upcoming: rows.some((appointment) => isUpcoming(appointment, today)),
        };
      }),
    [patients, appointments, today]
  );

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return assignedPatients.filter((row) => {
      const matchesRecord =
        recordFilter === 'all' || row.patient.record_status === recordFilter;
      const matchesQuery =
        !query ||
        row.patient.full_name.toLowerCase().includes(query) ||
        (row.patient.national_id ?? '').includes(query) ||
        row.patient.phone.includes(query);
      return matchesRecord && matchesQuery;
    });
  }, [assignedPatients, search, recordFilter]);

  const completeCount = patients.filter((patient) => patient.record_status === 'complete').length;
  const incompleteCount = patients.length - completeCount;
  const upcomingPatients = assignedPatients.filter((row) => row.upcoming).length;
  const linkedAccounts = patients.filter((patient) => patient.user_id).length;

  const handleManaged = async (message: string) => {
    setDialog(null);
    setSelectedPatient(null);
    setToast(message);
    await refreshAll();
  };

  const openDossier = (patient: Patient) => setSelectedPatient(patient);

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="پرونده‌ها، منظم و در دسترس"
        subtitle="جستجوی بیماران، وضعیت تکمیل پرونده و سوابق نوبت‌ها؛ همه از داده‌های ثبت‌شده سرور."
        action={
          hasPerm('manage_patients') ? (
            <Button
              size="md"
              onClick={() => setNewPatientOpen(true)}
              icon={<UserPlus className="w-4 h-4" />}
            >
              پرونده بیمار جدید
            </Button>
          ) : undefined
        }
      />

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 sm:gap-4 mb-5">
        <StatCard
          icon={<Users className="w-[18px] h-[18px]" />}
          label="کل پرونده‌ها"
          value={toPersianDigits(patients.length)}
          hint="ثبت‌شده در پایگاه داده"
        />
        <StatCard
          icon={<UserCheck className="w-[18px] h-[18px]" />}
          label="پرونده‌های کامل"
          value={toPersianDigits(completeCount)}
          hint="کد ملی ثبت شده است"
          tone="soft"
        />
        <StatCard
          icon={<FileWarning className="w-[18px] h-[18px]" />}
          label="نیازمند تکمیل"
          value={toPersianDigits(incompleteCount)}
          hint="بدون کد ملی"
          tone={incompleteCount > 0 ? 'warn' : 'soft'}
        />
        <StatCard
          icon={<CalendarCheck2 className="w-[18px] h-[18px]" />}
          label="بیماران با نوبت آینده"
          value={toPersianDigits(upcomingPatients)}
          hint="نوبت فعال ثبت‌شده"
        />
        <StatCard
          icon={<Link2 className="w-[18px] h-[18px]" />}
          label="متصل به حساب کاربری"
          value={toPersianDigits(linkedAccounts)}
          hint="از درگاه بیماران وارد می‌شوند"
          tone="soft"
        />
      </div>

      {toast && (
        <div className="d-soft-teal px-4 py-3 mb-4 text-small text-primary-deep flex items-center gap-2">
          <UserCheck className="w-4 h-4 shrink-0" />
          {toast}
        </div>
      )}

      <SectionCard
        title="فهرست بیماران"
        subtitle="برای مشاهده پرونده و سوابق، روی هر ردیف کلیک کنید"
        noPadding
      >
        <div className="p-4 sm:p-5 border-b border-line-soft flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div className="flex gap-1.5">
            {[
              { value: 'all' as RecordFilter, label: 'همه', count: patients.length },
              { value: 'complete' as RecordFilter, label: 'کامل', count: completeCount },
              { value: 'incomplete' as RecordFilter, label: 'نیازمند تکمیل', count: incompleteCount },
            ].map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setRecordFilter(item.value)}
                className={`d-chip ${recordFilter === item.value ? 'active' : ''}`}
              >
                {item.label}
                <span className="opacity-70">({toPersianDigits(item.count)})</span>
              </button>
            ))}
          </div>
          <div className="d-search w-full lg:w-72">
            <Search className="w-4 h-4" />
            <input
              className="d-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="نام، کد ملی یا شماره همراه..."
              aria-label="جستجوی بیمار"
            />
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<Users className="w-5 h-5" />}
              title="بیماری با این مشخصات یافت نشد"
              description={
                patients.length === 0
                  ? 'هنوز پرونده‌ای ثبت نشده است. اولین پرونده را ایجاد کنید.'
                  : 'فیلتر یا عبارت جستجو را تغییر دهید.'
              }
              actionLabel={patients.length === 0 && hasPerm('manage_patients') ? 'تشکیل پرونده' : 'پاک کردن فیلترها'}
              onAction={() => {
                if (patients.length === 0 && hasPerm('manage_patients')) {
                  setNewPatientOpen(true);
                } else {
                  setSearch('');
                  setRecordFilter('all');
                }
              }}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="d-table">
              <thead>
                <tr>
                  <th>بیمار</th>
                  <th>شماره تماس</th>
                  <th>کد ملی</th>
                  <th>وضعیت پرونده</th>
                  <th>مراجعات</th>
                  <th>آخرین / نوبت بعدی</th>
                  <th className="text-left">عملیات</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(({ patient, visitCount, completedCount, last, next }) => (
                  <tr key={patient.id}>
                    <td>
                      <button
                        type="button"
                        onClick={() => openDossier(patient)}
                        className="flex items-center gap-2.5 text-right"
                      >
                        <span className="w-8 h-8 rounded-full bg-primary-soft border border-primary-line text-primary-deep text-small font-bold flex items-center justify-center shrink-0">
                          {patient.full_name.charAt(0)}
                        </span>
                        <span>
                          <span className="block font-semibold text-ink">
                            {patient.full_name}
                          </span>
                          <span className="block text-caption text-faint mt-0.5">
                            شناسه {toPersianDigits(patient.id)}
                          </span>
                        </span>
                      </button>
                    </td>
                    <td className="tabular-nums text-muted" dir="ltr">
                      {toPersianDigits(patient.phone)}
                    </td>
                    <td className="tabular-nums text-muted">
                      {patient.national_id ? toPersianDigits(patient.national_id) : '—'}
                    </td>
                    <td>
                      <RecordStatusBadge status={patient.record_status} />
                    </td>
                    <td>
                      <div className="text-small font-semibold text-ink">
                        {toPersianDigits(visitCount)} نوبت
                      </div>
                      <div className="text-caption text-faint mt-0.5">
                        {toPersianDigits(completedCount)} تکمیل‌شده
                      </div>
                    </td>
                    <td>
                      <div className="text-caption text-ink">
                        {last ? `آخرین: ${formatToJalali(last.appointment_date)}` : 'بدون مراجعه'}
                      </div>
                      <div className="text-caption text-primary mt-1">
                        {next ? `بعدی: ${formatToJalali(next.appointment_date)}` : 'نوبت بعدی ثبت نشده'}
                      </div>
                    </td>
                    <td className="text-left">
                      <div className="inline-flex items-center gap-1">
                        <button
                          type="button"
                          title="مشاهدهٔ پرونده"
                          aria-label={`مشاهدهٔ پروندهٔ ${patient.full_name}`}
                          onClick={() => openDossier(patient)}
                          className="p-2 rounded-[9px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                        >
                          <ChevronLeft className="w-4 h-4" />
                        </button>
                        {hasPerm('manage_patients') && (
                          <>
                            <button
                              type="button"
                              title="ویرایش اطلاعات"
                              aria-label={`ویرایش ${patient.full_name}`}
                              onClick={() => setDialog({ kind: 'edit', patient })}
                              className="p-2 rounded-[9px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                            >
                              <Pencil className="w-4 h-4" />
                            </button>
                            {isAdmin && !patient.user_id && (
                              <button
                                type="button"
                                title="اتصال به حساب کاربری"
                                aria-label={`اتصال ${patient.full_name} به حساب`}
                                onClick={() => setDialog({ kind: 'link', patient })}
                                className="p-2 rounded-[9px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
                              >
                                <Link2 className="w-4 h-4" />
                              </button>
                            )}
                            {isAdmin && (
                              <button
                                type="button"
                                title="حذف پرونده"
                                aria-label={`حذف پروندهٔ ${patient.full_name}`}
                                onClick={() => setDialog({ kind: 'delete', patient })}
                                className="p-2 rounded-[9px] text-faint hover:text-danger hover:bg-danger-soft transition-colors"
                              >
                                <Trash2 className="w-4 h-4" />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <PatientDossierModal
        isOpen={Boolean(selectedPatient)}
        onClose={() => setSelectedPatient(null)}
        patient={selectedPatient}
        onEdit={(patient) => setDialog({ kind: 'edit', patient })}
        onLink={(patient) => setDialog({ kind: 'link', patient })}
      />
      <NewPatientModal isOpen={newPatientOpen} onClose={() => setNewPatientOpen(false)} />

      {dialog?.kind === 'edit' && (
        <EditPatientModal
          patient={dialog.patient}
          onClose={() => setDialog(null)}
          onDone={handleManaged}
        />
      )}
      {dialog?.kind === 'link' && (
        <LinkPatientAccountModal
          patient={dialog.patient}
          onClose={() => setDialog(null)}
          onDone={handleManaged}
        />
      )}
      {dialog?.kind === 'delete' && (
        <DeletePatientModal
          patient={dialog.patient}
          onClose={() => setDialog(null)}
          onDone={handleManaged}
        />
      )}
    </div>
  );
};

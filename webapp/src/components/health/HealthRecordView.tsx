import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import {
  ClinicalEntry,
  PatientHealthRecord,
  ToothCondition,
} from '../../types';
import { formatToJalali, toPersianDigits } from '../../utils/persianDate';
import { DentalChart, DentalChartLegend } from './DentalChart';
import { PrescriptionsPanel, TreatmentPlanPanel } from './ClinicalExtras';
import { ErrorBanner, InfoBanner, LoadingPanel, PageHeader, SectionCard } from '../common/ui';
import {
  AlertTriangle,
  ClipboardList,
  HeartPulse,
  Info,
  RefreshCw,
  Sparkles,
  Stethoscope,
  UserRound,
} from 'lucide-react';

const KIND_META: Record<
  ClinicalEntry['kind'],
  { label: string; chip: string; icon: React.ElementType }
> = {
  allergy: {
    label: 'هشدار حساسیت',
    chip: 'bg-danger-soft text-danger border-danger-line',
    icon: AlertTriangle,
  },
  treatment: {
    label: 'درمان',
    chip: 'bg-primary-soft text-primary-deep border-primary-line',
    icon: Stethoscope,
  },
  note: {
    label: 'یادداشت پزشک',
    chip: 'bg-info-soft text-info border-info-line',
    icon: Info,
  },
};

/**
 * Patient health record: allergies, the FDI tooth chart and the clinical
 * timeline. All content is server-scoped to the authenticated account; the
 * patient view is strictly read-only.
 */
export const HealthRecordView: React.FC = () => {
  const [records, setRecords] = useState<PatientHealthRecord[] | null>(null);
  const [activeRecordId, setActiveRecordId] = useState<number | null>(null);
  const [selectedTooth, setSelectedTooth] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiClient.getMyHealthRecord();
      setRecords(data.records);
      setActiveRecordId((current) => {
        if (current && data.records.some((r) => r.patient.id === current)) {
          return current;
        }
        return data.records[0]?.patient.id ?? null;
      });
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت پرونده سلامت ناکام ماند');
      setRecords(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const active = useMemo(
    () => records?.find((record) => record.patient.id === activeRecordId) || null,
    [records, activeRecordId]
  );

  const toothMap = useMemo(() => {
    const map: Record<number, ToothCondition> = {};
    active?.teeth.forEach((tooth) => {
      map[tooth.tooth_fdi] = tooth.status;
    });
    return map;
  }, [active]);

  const allergies = useMemo(
    () => active?.entries.filter((entry) => entry.kind === 'allergy') ?? [],
    [active]
  );

  const toothEntries = useMemo(
    () =>
      selectedTooth
        ? (active?.entries ?? []).filter(
            (entry) => entry.tooth_fdi === selectedTooth
          )
        : [],
    [active, selectedTooth]
  );

  const selectedToothCondition: ToothCondition | null = selectedTooth
    ? toothMap[selectedTooth] || 'healthy'
    : null;

  if (loading && records === null) {
    return <LoadingPanel message="در حال دریافت پرونده سلامت شما..." />;
  }

  return (
    <div className="d-page d-fade">
      <PageHeader
        title="پرونده سلامت من"
        subtitle="سابقه درمان‌ها، هشدارهای حساسیت و نقشه دندان‌های شما — به‌روزرسانی توسط تیم درمان."
        action={
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="p-2 rounded-[3px] text-faint hover:text-primary hover:bg-primary-soft transition-colors"
            aria-label="به‌روزرسانی پرونده"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {records && records.length === 0 && (
        <InfoBanner tone="warning" icon={<ClipboardList className="w-4 h-4" />} title="حساب شما هنوز پرونده ندارد">
          برای تشکیل پرونده، در گفتگو با دستیار نام، کد ملی و شماره تلفن را ثبت کنید.
        </InfoBanner>
      )}

      {records && records.length > 0 && (
        <div className="space-y-5">
          {/* Family record selector */}
          {records.length > 1 && (
            <div className="flex flex-wrap items-center gap-2">
              {records.map((record) => {
                const isActive = record.patient.id === activeRecordId;
                return (
                  <button
                    key={record.patient.id}
                    type="button"
                    onClick={() => {
                      setActiveRecordId(record.patient.id);
                      setSelectedTooth(null);
                    }}
                    className={`inline-flex items-center gap-2 h-9 px-3.5 rounded-full border text-small font-semibold transition-colors ${
                      isActive
                        ? 'bg-primary border-primary text-on-accent'
                        : 'bg-surface border-line text-muted hover:border-primary-line'
                    }`}
                  >
                    <UserRound className="w-3.5 h-3.5" />
                    {record.patient.full_name}
                    <span className={`text-caption ${isActive ? 'text-on-accent/75' : 'text-faint'}`}>
                      {record.patient.is_account_holder ? 'صاحب حساب' : 'عضو خانواده'}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Allergy alerts stay on top — they are safety-critical */}
          {allergies.length > 0 && (
            <div className="rounded-[4px] border border-danger-line bg-danger-soft p-4">
              <div className="flex items-center gap-2 text-small font-bold text-danger">
                <AlertTriangle className="w-4 h-4" />
                هشدار حساسیت ({toPersianDigits(allergies.length)} مورد)
              </div>
              <div className="mt-2.5 flex flex-wrap gap-2">
                {allergies.map((entry) => (
                  <span
                    key={entry.id}
                    className="inline-flex items-center gap-1.5 rounded-full bg-surface border border-danger-line px-3 py-1.5 text-caption font-semibold text-danger"
                  >
                    {entry.title}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tooth chart */}
          <SectionCard
            title="نقشه دندان‌ها (FDI)"
            subtitle="برای مشاهده جزئیات هر دندان، روی آن بزنید"
          >
            <DentalChart
              teeth={toothMap}
              selectedTooth={selectedTooth}
              onSelectTooth={(fdi) =>
                setSelectedTooth((current) => (current === fdi ? null : fdi))
              }
              disabled={loading}
            />
            <DentalChartLegend />

            {selectedTooth && (
              <div className="mt-4 rounded-[4px] border border-line bg-surface-muted p-4">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="text-small font-bold text-ink">
                    دندان {toPersianDigits(selectedTooth)}
                  </div>
                  <span className="text-caption font-semibold text-primary-deep bg-primary-soft rounded-full px-2.5 py-1">
                    وضعیت: {
                      { healthy: 'سالم', treated: 'درمان‌شده', needs_treatment: 'نیاز به درمان', extracted: 'کشیده‌شده' }[
                        selectedToothCondition || 'healthy'
                      ]
                    }
                  </span>
                </div>
                {toothEntries.length === 0 ? (
                  <p className="text-caption text-muted mt-2.5 leading-5">
                    برای این دندان ثبت‌کردنی در پرونده وجود ندارد.
                  </p>
                ) : (
                  <ul className="mt-2.5 space-y-2">
                    {toothEntries.map((entry) => (
                      <li key={entry.id} className="text-caption text-muted leading-5">
                        <span className="font-semibold text-ink">{entry.title}</span>
                        {' — '}
                        {formatToJalali(entry.created_at)}
                        {entry.doctor_name ? ` • ${entry.doctor_name}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </SectionCard>

          {/* Clinical timeline */}
          <SectionCard
            title="تاریخچه درمان و یادداشت‌ها"
            subtitle="جدیدترین رکوردهای ثبت‌شده توسط تیم درمان"
          >
            {!active || active.entries.filter((e) => e.kind !== 'allergy').length === 0 ? (
              <div className="d-empty">
                <div className="d-empty-icon">
                  <HeartPulse className="w-5 h-5" />
                </div>
                <h4 className="text-body font-bold text-ink mb-1">
                  هنوز رکوردی ثبت نشده است
                </h4>
                <p className="text-small text-muted leading-6 max-w-md">
                  پس از اولین ویزیت، یادداشت‌های درمانی پزشک به‌صورت خودکار در این بخش
                  نمایش داده می‌شود.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {active.entries
                  .filter((entry) => entry.kind !== 'allergy')
                  .map((entry) => {
                    const meta = KIND_META[entry.kind] || KIND_META.note;
                    const Icon = meta.icon;
                    return (
                      <div
                        key={entry.id}
                        className="rounded-[4px] border border-line-soft bg-surface p-4 hover:border-primary-line transition-colors"
                      >
                        <div className="flex items-start justify-between gap-3 flex-wrap">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className={`w-8 h-8 rounded-[3px] border flex items-center justify-center shrink-0 ${meta.chip}`}>
                              <Icon className="w-4 h-4" />
                            </span>
                            <div className="min-w-0">
                              <div className="text-small font-bold text-ink truncate">
                                {entry.title}
                              </div>
                              <div className="text-caption text-faint mt-0.5 flex items-center gap-1.5 flex-wrap">
                                <span>{formatToJalali(entry.created_at)}</span>
                                {entry.tooth_fdi && (
                                  <>
                                    <span className="text-line-strong">•</span>
                                    <span>دندان {toPersianDigits(entry.tooth_fdi)}</span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                          <span className={`shrink-0 rounded-full border px-2.5 py-1 text-caption font-semibold ${meta.chip}`}>
                            {meta.label}
                          </span>
                        </div>
                        {entry.body && (
                          <p className="text-caption text-muted leading-6 mt-3 bg-surface-muted rounded-[3px] border border-line-soft p-3">
                            {entry.body}
                          </p>
                        )}
                        {(entry.doctor_name || entry.created_by_name) && (
                          <div className="text-caption text-faint mt-2.5 flex items-center gap-1.5">
                            <Stethoscope className="w-3.5 h-3.5" />
                            {entry.doctor_name || entry.created_by_name}
                          </div>
                        )}
                      </div>
                    );
                  })}
              </div>
            )}
          </SectionCard>

          <SectionCard
            title="طرح درمان و نسخه‌ها"
            subtitle="مسیر درمان تأییدشده و داروهای تجویزشده توسط تیم درمان"
          >
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
              <TreatmentPlanPanel
                patientId={active?.patient.id ?? 0}
                canWrite={false}
                onRefresh={load}
                items={active?.plan_items ?? []}
              />
              <PrescriptionsPanel
                patientId={active?.patient.id ?? 0}
                canWrite={false}
                onRefresh={load}
                items={active?.prescriptions ?? []}
              />
            </div>
          </SectionCard>

          <div className="d-soft-teal rounded-[4px] px-4 py-3.5 flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-primary-deep shrink-0 mt-0.5" />
            <p className="text-caption text-primary-deep leading-5">
              محتوای این صفحه صرفاً سابقه درمانی ثبت‌شده کلینیک است و جایگزین
              معاینه حضوری نیست. برای هرگونه تصمیم درمانی با پزشک خود مشورت کنید.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

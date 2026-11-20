import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../../api/client';
import {
  ClinicalEntry,
  PatientHealthRecord,
  ToothCondition,
} from '../../types';
import { formatToJalali, toPersianDigits } from '../../utils/persianDate';
import { DentalChart, DentalChartLegend, TOOTH_CONDITION_STYLES } from './DentalChart';
import { Modal } from '../common/Modal';
import { Button } from '../common/Button';
import { ErrorBanner } from '../common/ui';
import { PrescriptionsPanel, TreatmentPlanPanel } from './ClinicalExtras';
import {
  AlertTriangle,
  Info,
  Loader2,
  Plus,
  Stethoscope,
} from 'lucide-react';

const KIND_OPTIONS: {
  value: ClinicalEntry['kind'];
  label: string;
}[] = [
  { value: 'treatment', label: 'درمان انجام‌شده' },
  { value: 'allergy', label: 'هشدار حساسیت' },
  { value: 'note', label: 'یادداشت بالینی' },
];

const STATUS_OPTIONS: { value: ToothCondition; label: string }[] = [
  { value: 'healthy', label: 'سالم' },
  { value: 'treated', label: 'درمان‌شده' },
  { value: 'needs_treatment', label: 'نیاز به درمان' },
  { value: 'extracted', label: 'کشیده‌شده' },
];

interface ClinicalRecordModalProps {
  isOpen: boolean;
  onClose: () => void;
  patientId: number;
  patientName: string;
  /** Admin/doctor may write; reception stays read-only. */
  canWrite: boolean;
}

/**
 * Staff clinical record surface: the FDI chart, the entry timeline and the
 * write forms. The same modal serves the doctor's patient list (write) and
 * the admin/receptionist dossier (configurable), so the clinic edits patient
 * records from exactly one audited code path.
 */
export const ClinicalRecordModal: React.FC<ClinicalRecordModalProps> = ({
  isOpen,
  onClose,
  patientId,
  patientName,
  canWrite,
}) => {
  const [record, setRecord] = useState<PatientHealthRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTooth, setSelectedTooth] = useState<number | null>(null);

  // Entry form state
  const [formOpen, setFormOpen] = useState(false);
  const [kind, setKind] = useState<ClinicalEntry['kind']>('treatment');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [entryTooth, setEntryTooth] = useState<string>('');
  const [saving, setSaving] = useState(false);

  // Tooth status state
  const [toothStatus, setToothStatus] = useState<ToothCondition>('treated');
  const [toothNote, setToothNote] = useState('');
  const [savingTooth, setSavingTooth] = useState(false);

  const load = useCallback(async () => {
    if (!isOpen) return;
    setLoading(true);
    try {
      const data = await apiClient.getClinicalRecord(patientId);
      setRecord(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'دریافت پرونده بالینی ناکام ماند');
      setRecord(null);
    } finally {
      setLoading(false);
    }
  }, [isOpen, patientId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Reset transient state whenever the modal (or patient) changes.
  useEffect(() => {
    if (isOpen) {
      setSelectedTooth(null);
      setFormOpen(false);
      setTitle('');
      setBody('');
      setEntryTooth('');
      setKind('treatment');
      setToothStatus('treated');
      setToothNote('');
      setError(null);
    }
  }, [isOpen, patientId]);

  const toothMap = useMemo(() => {
    const map: Record<number, ToothCondition> = {};
    record?.teeth.forEach((tooth) => {
      map[tooth.tooth_fdi] = tooth.status;
    });
    return map;
  }, [record]);

  const selectedToothStatus = record?.teeth.find(
    (tooth) => tooth.tooth_fdi === selectedTooth
  );

  const submitEntry = async () => {
    if (title.trim().length < 2) return;
    setSaving(true);
    try {
      await apiClient.createClinicalEntry(patientId, {
        kind,
        title: title.trim(),
        body: body.trim() || null,
        tooth_fdi: entryTooth ? Number(entryTooth) : null,
      });
      setTitle('');
      setBody('');
      setEntryTooth('');
      setFormOpen(false);
      await load();
    } catch (err: any) {
      setError(err.message || 'ثبت یادداشت ناکام ماند');
    } finally {
      setSaving(false);
    }
  };

  const submitToothStatus = async () => {
    if (!selectedTooth) return;
    setSavingTooth(true);
    try {
      await apiClient.setToothStatus(
        patientId,
        selectedTooth,
        toothStatus,
        toothNote.trim() || null
      );
      setToothNote('');
      await load();
    } catch (err: any) {
      setError(err.message || 'ثبت وضعیت دندان ناکام ماند');
    } finally {
      setSavingTooth(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`پرونده بالینی — ${patientName}`}
      subtitle="نقشه دندان‌ها، یادداشت‌های درمانی و هشدارهای حساسیت"
      maxWidth="3xl"
    >
      {error && <ErrorBanner message={error} onRetry={() => void load()} />}

      {loading && !record ? (
        <div className="flex items-center justify-center gap-2 py-10 text-caption text-muted">
          <Loader2 className="w-4 h-4 animate-spin" />
          در حال دریافت پرونده...
        </div>
      ) : (
        <div className="space-y-5">
          {/* Allergy banner */}
          {(record?.entries ?? []).filter((e) => e.kind === 'allergy').length >
            0 && (
            <div className="rounded-[12px] border border-danger-line bg-danger-soft p-3.5">
              <div className="flex items-center gap-2 text-small font-bold text-danger">
                <AlertTriangle className="w-4 h-4" />
                هشدار حساسیت
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {record!.entries
                  .filter((entry) => entry.kind === 'allergy')
                  .map((entry) => (
                    <span
                      key={entry.id}
                      className="rounded-full bg-surface border border-danger-line px-3 py-1 text-caption font-semibold text-danger"
                    >
                      {entry.title}
                    </span>
                  ))}
              </div>
            </div>
          )}

          {/* Chart */}
          <div>
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
              <h4 className="text-body font-bold text-ink">
                نقشه دندان‌ها (FDI)
              </h4>
              {canWrite && (
                <span className="text-caption text-muted">
                  برای ثبت/ویرایش وضعیت، روی دندان بزنید
                </span>
              )}
            </div>
            <DentalChart
              teeth={toothMap}
              selectedTooth={selectedTooth}
              onSelectTooth={(fdi) => {
                setSelectedTooth((current) => (current === fdi ? null : fdi));
                const existing = record?.teeth.find((t) => t.tooth_fdi === fdi);
                setToothStatus(existing?.status ?? 'treated');
                setToothNote(existing?.note ?? '');
              }}
              disabled={!canWrite && !selectedTooth}
            />
            <DentalChartLegend />
          </div>

          {/* Selected tooth panel */}
          {selectedTooth && (
            <div className="rounded-[12px] border border-line bg-surface-muted p-4">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <div className="text-small font-bold text-ink">
                  دندان {toPersianDigits(selectedTooth)}
                  {selectedToothStatus && (
                    <span className="text-caption font-semibold text-primary-deep bg-primary-soft rounded-full px-2.5 py-1 mr-2">
                      {TOOTH_CONDITION_STYLES[selectedToothStatus.status].label}
                    </span>
                  )}
                </div>
              </div>

              {canWrite ? (
                <div className="mt-3 flex flex-col sm:flex-row gap-2.5">
                  <select
                    value={toothStatus}
                    onChange={(event) =>
                      setToothStatus(event.target.value as ToothCondition)
                    }
                    className="h-9 rounded-[9px] border border-line bg-surface px-2.5 text-small text-ink focus:outline-none focus:ring-2 focus:ring-primary/30"
                    aria-label="وضعیت دندان"
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={toothNote}
                    onChange={(event) => setToothNote(event.target.value)}
                    placeholder="توضیح کوتاه (اختیاری)"
                    maxLength={300}
                    className="flex-1 h-9 rounded-[9px] border border-line bg-surface px-3 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                  <Button
                    size="sm"
                    onClick={() => void submitToothStatus()}
                    disabled={savingTooth}
                    icon={
                      savingTooth ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : undefined
                    }
                  >
                    ثبت وضعیت
                  </Button>
                </div>
              ) : selectedToothStatus?.note ? (
                <p className="text-caption text-muted mt-2">
                  {selectedToothStatus.note}
                </p>
              ) : null}
            </div>
          )}

          {/* Entries */}
          <div>
            <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
              <h4 className="text-body font-bold text-ink">
                یادداشت‌های درمانی ({toPersianDigits(record?.entries.length ?? 0)})
              </h4>
              {canWrite && !formOpen && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setFormOpen(true)}
                  icon={<Plus className="w-3.5 h-3.5" />}
                >
                  یادداشت جدید
                </Button>
              )}
            </div>

            {canWrite && formOpen && (
              <div className="rounded-[12px] border border-primary-line bg-[#FBFDFD] p-4 space-y-3 mb-4">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  <select
                    value={kind}
                    onChange={(event) =>
                      setKind(event.target.value as ClinicalEntry['kind'])
                    }
                    className="h-9 rounded-[9px] border border-line bg-surface px-2.5 text-small text-ink focus:outline-none focus:ring-2 focus:ring-primary/30"
                    aria-label="نوع یادداشت"
                  >
                    {KIND_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={entryTooth}
                    onChange={(event) => setEntryTooth(event.target.value)}
                    className="h-9 rounded-[9px] border border-line bg-surface px-2.5 text-small text-ink focus:outline-none focus:ring-2 focus:ring-primary/30"
                    aria-label="دندان مرتبط"
                  >
                    <option value="">بدون دندان مشخص</option>
                    {Array.from({ length: 32 }, (_, index) => {
                      const quadrant = Math.floor(index / 8) + 1;
                      const tooth = (index % 8) + 1;
                      const fdi = quadrant * 10 + tooth;
                      return (
                        <option key={fdi} value={fdi}>
                          دندان {fdi}
                        </option>
                      );
                    })}
                  </select>
                  <input
                    type="text"
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="عنوان (الزامی)"
                    maxLength={200}
                    className="h-9 rounded-[9px] border border-line bg-surface px-3 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                </div>
                <textarea
                  value={body}
                  onChange={(event) => setBody(event.target.value)}
                  placeholder="شرح یادداشت (اختیاری)"
                  rows={3}
                  maxLength={4000}
                  className="w-full rounded-[9px] border border-line bg-surface px-3 py-2 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
                />
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => void submitEntry()}
                    disabled={saving || title.trim().length < 2}
                    icon={
                      saving ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Stethoscope className="w-3.5 h-3.5" />
                      )
                    }
                  >
                    ثبت در پرونده
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setFormOpen(false)}
                  >
                    انصراف
                  </Button>
                </div>
              </div>
            )}

            {!record || record.entries.length === 0 ? (
              <div className="rounded-[12px] border border-dashed border-line p-5 text-center">
                <Info className="w-5 h-5 text-faint mx-auto mb-2" />
                <p className="text-caption text-muted">
                  هنوز یادداشتی در این پرونده ثبت نشده است.
                </p>
              </div>
            ) : (
              <div className="space-y-2.5">
                {record.entries.map((entry) => (
                  <div
                    key={entry.id}
                    className="rounded-[12px] border border-line-soft bg-surface p-3.5"
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="text-small font-bold text-ink">
                          {entry.title}
                          {entry.tooth_fdi && (
                            <span className="text-caption text-faint font-normal mr-2">
                              دندان {toPersianDigits(entry.tooth_fdi)}
                            </span>
                          )}
                        </div>
                        <div className="text-caption text-faint mt-0.5">
                          {formatToJalali(entry.created_at)}
                          {entry.doctor_name ? ` • ${entry.doctor_name}` : ''}
                          {!entry.doctor_name && entry.created_by_name
                            ? ` • ${entry.created_by_name}`
                            : ''}
                        </div>
                      </div>
                      <span
                        className={`shrink-0 rounded-full border px-2.5 py-1 text-caption font-semibold ${
                          entry.kind === 'allergy'
                            ? 'bg-danger-soft text-danger border-danger-line'
                            : entry.kind === 'treatment'
                              ? 'bg-primary-soft text-primary-deep border-primary-line'
                              : 'bg-[#EEF4FB] text-info border-[#D7E4F4]'
                        }`}
                      >
                        {
                          {
                            treatment: 'درمان',
                            allergy: 'حساسیت',
                            note: 'یادداشت',
                          }[entry.kind]
                        }
                      </span>
                    </div>
                    {entry.body && (
                      <p className="text-caption text-muted leading-6 mt-2.5">
                        {entry.body}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Treatment roadmap and prescriptions */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 pt-2 border-t border-line-soft">
            <TreatmentPlanPanel
              patientId={patientId}
              canWrite={canWrite}
              onRefresh={load}
              items={record?.plan_items ?? []}
            />
            <PrescriptionsPanel
              patientId={patientId}
              canWrite={canWrite}
              onRefresh={load}
              items={record?.prescriptions ?? []}
            />
          </div>
        </div>
      )}
    </Modal>
  );
};

import React, { useState } from 'react';
import { apiClient } from '../../api/client';
import {
  MedicationLine,
  Prescription,
  TreatmentPlanItem,
  TreatmentPlanStatus,
} from '../../types';
import { Button } from '../common/Button';
import { Badge } from '../common/Badge';
import { formatToJalali, toPersianDigits } from '../../utils/persianDate';
import {
  CheckCircle2,
  ClipboardList,
  Loader2,
  Pill,
  Plus,
  Trash2,
} from 'lucide-react';

const PLAN_STATUS_META: Record<
  TreatmentPlanStatus,
  { label: string; tone: 'info' | 'teal' | 'success' | 'neutral' }
> = {
  planned: { label: 'برنامه‌ریزی‌شده', tone: 'info' },
  in_progress: { label: 'در حال انجام', tone: 'teal' },
  completed: { label: 'انجام‌شده', tone: 'success' },
  cancelled: { label: 'لغوشده', tone: 'neutral' },
};

const FDI_OPTIONS = Array.from({ length: 32 }, (_, index) => {
  const quadrant = Math.floor(index / 8) + 1;
  const tooth = (index % 8) + 1;
  return quadrant * 10 + tooth;
});

const inputClass =
  'h-9 rounded-[9px] border border-line bg-surface px-3 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30';

interface PanelProps {
  patientId: number;
  canWrite: boolean;
  onRefresh: () => Promise<void> | void;
}

/* ------------------------------------------------------------ treatment plan */

export const TreatmentPlanPanel: React.FC<
  PanelProps & { items: TreatmentPlanItem[] }
> = ({ patientId, canWrite, onRefresh, items }) => {
  const [formOpen, setFormOpen] = useState(false);
  const [title, setTitle] = useState('');
  const [tooth, setTooth] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [updatingId, setUpdatingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (title.trim().length < 2) return;
    setSaving(true);
    setError(null);
    try {
      await apiClient.createTreatmentPlanItem(patientId, {
        title: title.trim(),
        tooth_fdi: tooth ? Number(tooth) : null,
        notes: notes.trim() || null,
      });
      setTitle('');
      setTooth('');
      setNotes('');
      setFormOpen(false);
      await onRefresh();
    } catch (err: any) {
      setError(err.message || 'ثبت طرح درمان ناکام ماند');
    } finally {
      setSaving(false);
    }
  };

  const changeStatus = async (item: TreatmentPlanItem, status: TreatmentPlanStatus) => {
    setUpdatingId(item.id);
    setError(null);
    try {
      await apiClient.updateTreatmentPlanItem(patientId, item.id, { status });
      await onRefresh();
    } catch (err: any) {
      setError(err.message || 'تغییر وضعیت طرح درمان ناکام ماند');
    } finally {
      setUpdatingId(null);
    }
  };

  const openCount = items.filter(
    (item) => item.status === 'planned' || item.status === 'in_progress'
  ).length;

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div>
          <h4 className="text-body font-bold text-ink flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-primary" />
            طرح درمان
            <span className="text-caption font-normal text-faint">
              ({toPersianDigits(items.length)} قلم، {toPersianDigits(openCount)} باز)
            </span>
          </h4>
          <p className="text-caption text-faint mt-1">
            نقشهٔ درمان چندجلسه‌ای؛ هر قلم را می‌توانید به «در حال انجام» یا «انجام‌شده» ببرید.
          </p>
        </div>
        {canWrite && !formOpen && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setFormOpen(true)}
            icon={<Plus className="w-3.5 h-3.5" />}
          >
            افزودن به طرح
          </Button>
        )}
      </div>

      {error && (
        <div className="d-soft-danger px-3 py-2 text-caption text-danger mb-3">
          {error}
        </div>
      )}

      {canWrite && formOpen && (
        <div className="rounded-[12px] border border-primary-line bg-[#FBFDFD] p-4 space-y-3 mb-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="نوع درمان (مثلاً عصب‌کشی)"
              maxLength={200}
              className={`${inputClass} sm:col-span-2`}
            />
            <select
              value={tooth}
              onChange={(event) => setTooth(event.target.value)}
              className={inputClass}
              aria-label="دندان هدف"
            >
              <option value="">بدون دندان مشخص</option>
              {FDI_OPTIONS.map((fdi) => (
                <option key={fdi} value={fdi}>
                  دندان {fdi}
                </option>
              ))}
            </select>
          </div>
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="توضیح کوتاه (اختیاری)"
            rows={2}
            maxLength={2000}
            className="w-full rounded-[9px] border border-line bg-surface px-3 py-2 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => void submit()}
              disabled={saving || title.trim().length < 2}
              icon={
                saving ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Plus className="w-3.5 h-3.5" />
                )
              }
            >
              ثبت در طرح درمان
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setFormOpen(false)}>
              انصراف
            </Button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="rounded-[12px] border border-dashed border-line p-5 text-center">
          <ClipboardList className="w-5 h-5 text-faint mx-auto mb-2" />
          <p className="text-caption text-muted">
            هنوز درمانی در طرح درمان ثبت نشده است.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {items.map((item) => {
            const meta = PLAN_STATUS_META[item.status] || PLAN_STATUS_META.planned;
            return (
              <div
                key={item.id}
                className={`rounded-[12px] border p-3.5 ${
                  item.status === 'completed'
                    ? 'border-line bg-surface-muted'
                    : 'border-line-soft bg-surface'
                }`}
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div className="min-w-0">
                    <div className="text-small font-bold text-ink flex items-center gap-2 flex-wrap">
                      {item.title}
                      {item.tooth_fdi && (
                        <span className="text-caption font-normal text-faint">
                          دندان {toPersianDigits(item.tooth_fdi)}
                        </span>
                      )}
                    </div>
                    <div className="text-caption text-faint mt-0.5">
                      {formatToJalali(item.created_at)}
                      {item.doctor_name ? ` • ${item.doctor_name}` : ''}
                    </div>
                    {item.notes && (
                      <p className="text-caption text-muted leading-6 mt-2">{item.notes}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={meta.tone} dot>
                      {meta.label}
                    </Badge>
                    {canWrite && item.status !== 'completed' && item.status !== 'cancelled' && (
                      <select
                        className="h-8 rounded-[8px] border border-line bg-surface px-2 text-caption text-ink"
                        value={item.status}
                        disabled={updatingId === item.id}
                        onChange={(event) =>
                          void changeStatus(
                            item,
                            event.target.value as TreatmentPlanStatus
                          )
                        }
                        aria-label="تغییر وضعیت طرح درمان"
                      >
                        <option value="planned">برنامه‌ریزی‌شده</option>
                        <option value="in_progress">در حال انجام</option>
                        <option value="completed">انجام‌شده</option>
                        <option value="cancelled">لغو</option>
                      </select>
                    )}
                    {item.status === 'completed' && (
                      <CheckCircle2 className="w-4 h-4 text-primary" />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

/* -------------------------------------------------------------- prescriptions */

const emptyLine = (): MedicationLine => ({
  name: '',
  dose: '',
  frequency: '',
  duration: '',
});

export const PrescriptionsPanel: React.FC<
  PanelProps & { items: Prescription[] }
> = ({ patientId, canWrite, onRefresh, items }) => {
  const [formOpen, setFormOpen] = useState(false);
  const [lines, setLines] = useState<MedicationLine[]>([emptyLine()]);
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const updateLine = (index: number, patch: Partial<MedicationLine>) => {
    setLines((current) =>
      current.map((line, lineIndex) =>
        lineIndex === index ? { ...line, ...patch } : line
      )
    );
  };

  const submit = async () => {
    const cleaned = lines.filter((line) => line.name.trim().length >= 2);
    if (cleaned.length === 0) {
      setError('حداقل نام یک دارو را وارد کنید.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiClient.createPrescription(patientId, {
        items: cleaned,
        notes: notes.trim() || null,
      });
      setLines([emptyLine()]);
      setNotes('');
      setFormOpen(false);
      await onRefresh();
    } catch (err: any) {
      setError(err.message || 'ثبت نسخه ناکام ماند');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div>
          <h4 className="text-body font-bold text-ink flex items-center gap-2">
            <Pill className="w-4 h-4 text-primary" />
            نسخه‌ها
            <span className="text-caption font-normal text-faint">
              ({toPersianDigits(items.length)})
            </span>
          </h4>
          <p className="text-caption text-faint mt-1">
            داروهای تجویزشده با دوز و دورهٔ مصرف؛ سابقه به‌صورت فقط-افزودنی می‌ماند.
          </p>
        </div>
        {canWrite && !formOpen && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setFormOpen(true)}
            icon={<Plus className="w-3.5 h-3.5" />}
          >
            نسخه جدید
          </Button>
        )}
      </div>

      {error && (
        <div className="d-soft-danger px-3 py-2 text-caption text-danger mb-3">
          {error}
        </div>
      )}

      {canWrite && formOpen && (
        <div className="rounded-[12px] border border-primary-line bg-[#FBFDFD] p-4 space-y-3 mb-4">
          {lines.map((line, index) => (
            <div key={index} className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              <input
                value={line.name}
                onChange={(event) => updateLine(index, { name: event.target.value })}
                placeholder="نام دارو"
                maxLength={120}
                className={inputClass}
              />
              <input
                value={line.dose || ''}
                onChange={(event) => updateLine(index, { dose: event.target.value })}
                placeholder="دوز (۵۰۰ میلی‌گرم)"
                maxLength={80}
                className={inputClass}
              />
              <input
                value={line.frequency || ''}
                onChange={(event) =>
                  updateLine(index, { frequency: event.target.value })
                }
                placeholder="تعداد (هر ۸ ساعت)"
                maxLength={80}
                className={inputClass}
              />
              <div className="flex items-center gap-1.5">
                <input
                  value={line.duration || ''}
                  onChange={(event) =>
                    updateLine(index, { duration: event.target.value })
                  }
                  placeholder="مدت (۵ روز)"
                  maxLength={80}
                  className={`${inputClass} flex-1`}
                />
                {lines.length > 1 && (
                  <button
                    type="button"
                    onClick={() =>
                      setLines((current) =>
                        current.filter((_, lineIndex) => lineIndex !== index)
                      )
                    }
                    className="p-2 text-danger hover:bg-danger-soft rounded-[8px]"
                    aria-label="حذف دارو"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setLines((current) => [...current, emptyLine()])}
            className="text-caption font-semibold text-primary inline-flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            افزودن دارو
          </button>
          <textarea
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="توضیح/توصیه (اختیاری)"
            rows={2}
            maxLength={2000}
            className="w-full rounded-[9px] border border-line bg-surface px-3 py-2 text-small text-ink placeholder:text-line-strong focus:outline-none focus:ring-2 focus:ring-primary/30"
          />
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              onClick={() => void submit()}
              disabled={saving}
              icon={
                saving ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Pill className="w-3.5 h-3.5" />
                )
              }
            >
              ثبت نسخه
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setFormOpen(false)}>
              انصراف
            </Button>
          </div>
        </div>
      )}

      {items.length === 0 ? (
        <div className="rounded-[12px] border border-dashed border-line p-5 text-center">
          <Pill className="w-5 h-5 text-faint mx-auto mb-2" />
          <p className="text-caption text-muted">هنوز نسخه‌ای صادر نشده است.</p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {items.map((prescription) => (
            <div
              key={prescription.id}
              className="rounded-[12px] border border-line-soft bg-surface p-3.5"
            >
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="text-caption text-faint">
                  {formatToJalali(prescription.created_at)}
                  {prescription.doctor_name ? ` • ${prescription.doctor_name}` : ''}
                </div>
                {prescription.cancelled_at && (
                  <Badge variant="neutral">لغوشده</Badge>
                )}
              </div>
              <ul className="mt-2 space-y-1.5">
                {prescription.items.map((line, index) => (
                  <li key={index} className="text-small text-ink">
                    <span className="font-semibold">{line.name}</span>
                    {(() => {
                      const details = [
                        line.dose,
                        line.frequency,
                        line.duration,
                      ]
                        .filter(Boolean)
                        .join(' • ');
                      return details ? (
                        <span className="text-caption text-muted mr-2">
                          — {details}
                        </span>
                      ) : null;
                    })()}
                  </li>
                ))}
              </ul>
              {prescription.notes && (
                <p className="text-caption text-muted leading-6 mt-2 bg-surface-muted rounded-[10px] border border-line-soft p-2.5">
                  {prescription.notes}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

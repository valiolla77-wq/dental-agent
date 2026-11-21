import React from 'react';
import { Check } from 'lucide-react';
import { DayMeta } from '../../../utils/analytics';
import { formatTimeFa, toPersianDigits } from '../../../utils/persianDate';

interface BookingTicketProps {
  status: 'draft' | 'confirmed';
  day: DayMeta | null;
  time: string;
  serviceName?: string;
  doctorName?: string;
  patientName?: string;
  notes?: string;
  /** Colour of the surface behind the card; the notches are cut in this colour. */
  notchColor?: string;
}

const Row: React.FC<{ label: string; value?: string }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-4">
    <dt className="text-small text-on-accent/55 shrink-0">{label}</dt>
    <dd
      key={value || 'empty'}
      className={`text-body min-w-0 truncate text-left ${
        value ? 'font-semibold text-on-accent d-pop' : 'text-on-accent/30'
      }`}
    >
      {value || 'انتخاب نشده'}
    </dd>
  </div>
);

/**
 * The appointment card: a paper-card metaphor from the clinic desk. It fills
 * in as choices are made, and the same card becomes the receipt once the
 * booking is saved.
 */
export const BookingTicket: React.FC<BookingTicketProps> = ({
  status,
  day,
  time,
  serviceName,
  doctorName,
  patientName,
  notes,
  notchColor = '#FFFFFF',
}) => {
  const confirmed = status === 'confirmed';
  const notch = { backgroundColor: notchColor } as React.CSSProperties;

  return (
    <div
      role="group"
      aria-label="کارت نوبت"
      className={`relative overflow-hidden rounded-[4px] bg-ink text-on-accent ${
        confirmed ? 'ring-2 ring-[#c98a72]/60' : ''
      }`}
    >
      <div className="px-5 pt-4 pb-5">
        <div className="flex items-center justify-between">
          <span className="text-small font-semibold text-on-accent/70">کارت نوبت</span>
          <span
            className={`inline-flex items-center gap-1 rounded-[2px] px-2 py-1 text-small font-semibold ${
              confirmed ? 'bg-[#f0cbb9] text-[#241f19]' : 'bg-surface/10 text-on-accent/70'
            }`}
          >
            {confirmed && <Check className="w-3 h-3" aria-hidden="true" />}
            {confirmed ? 'ثبت شد' : 'در حال تکمیل'}
          </span>
        </div>

        <div aria-live="polite" className="mt-4 min-h-[88px]">
          {day ? (
            <div className="flex items-end justify-between gap-3">
              <div key={day.jalali} className="d-pop flex items-end gap-2.5">
                <span className="text-[52px] leading-[0.95] font-extrabold tabular-nums">
                  {toPersianDigits(day.day)}
                </span>
                <span className="pb-1 leading-5">
                  <span className="block text-lead font-bold">{day.monthName}</span>
                  <span className="block text-small text-on-accent/60">
                    {day.isToday ? `امروز، ${day.weekday}` : day.weekday}
                  </span>
                </span>
              </div>
              <div
                key={time || 'no-time'}
                className={`pb-0.5 text-[30px] leading-none font-extrabold tabular-nums ${
                  time ? 'text-[#f0cbb9] d-pop' : 'text-on-accent/25'
                }`}
              >
                {time ? formatTimeFa(time) : '--:--'}
              </div>
            </div>
          ) : (
            <div className="flex h-[88px] items-center justify-center rounded-[4px] border border-dashed border-surface/20 px-4 text-center text-small leading-5 text-on-accent/50">
              روز و ساعت هنوز انتخاب نشده است
            </div>
          )}
        </div>
      </div>

      {/* Perforation */}
      <div className="relative" aria-hidden="true">
        <span className="absolute -start-3 -top-3 h-6 w-6 rounded-full" style={notch} />
        <span className="absolute -end-3 -top-3 h-6 w-6 rounded-full" style={notch} />
        <div className="mx-5 border-t border-dashed border-surface/25" />
      </div>

      <dl className="space-y-2.5 px-5 pt-4 pb-5">
        <Row label="خدمت" value={serviceName} />
        <Row label="پزشک" value={doctorName} />
        <Row label="بیمار" value={patientName} />
      </dl>
      {notes && (
        <p className="px-5 pb-5 -mt-1 text-small leading-5 text-on-accent/65 line-clamp-2">{notes}</p>
      )}
    </div>
  );
};

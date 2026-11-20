import { useCallback, useEffect, useRef, useState } from 'react';
import { DayAvailability, normalizeSlots } from '../../../utils/bookingSlots';
import { DayMeta } from '../../../utils/analytics';

const BATCH_SIZE = 4;
const FALLBACK_ERROR = 'دریافت زمان‌های خالی انجام نشد. دوباره تلاش کنید.';

type Fetcher = (doctorId: number, jalaliDate: string) => Promise<string[]>;

/**
 * Free slots for one doctor across a list of days.
 *
 * Days are requested in small batches, nearest first, so the nearest free
 * slot is known as early as possible without flooding the server. Results
 * come only from the API: a failed day is marked as an error, never filled
 * with invented times.
 */
export function useDoctorAvailability(
  enabled: boolean,
  doctorId: number | null,
  days: DayMeta[],
  fetchSlots: Fetcher
) {
  const [byDay, setByDay] = useState<Record<string, DayAvailability>>({});
  const fetcher = useRef(fetchSlots);
  fetcher.current = fetchSlots;
  const runId = useRef(0);

  const load = useCallback(async (doctor: number, day: DayMeta, run: number) => {
    try {
      const raw = await fetcher.current(doctor, day.jalali);
      if (run !== runId.current) return;
      setByDay((prev) => ({ ...prev, [day.jalali]: { status: 'ready', slots: normalizeSlots(raw) } }));
    } catch (err) {
      if (run !== runId.current) return;
      const message = err instanceof Error && err.message ? err.message : FALLBACK_ERROR;
      setByDay((prev) => ({ ...prev, [day.jalali]: { status: 'error', message } }));
    }
  }, []);

  useEffect(() => {
    runId.current += 1;
    const run = runId.current;
    if (!enabled || doctorId === null) {
      setByDay({});
      return;
    }
    setByDay(Object.fromEntries(days.map((day) => [day.jalali, { status: 'loading' as const }])));
    (async () => {
      for (let index = 0; index < days.length; index += BATCH_SIZE) {
        if (run !== runId.current) return;
        await Promise.all(
          days.slice(index, index + BATCH_SIZE).map((day) => load(doctorId, day, run))
        );
      }
    })();
    return () => {
      runId.current += 1;
    };
  }, [enabled, doctorId, days, load]);

  /** Re-read one day (after a conflict, or on the person's request). */
  const refreshDay = useCallback(
    (day: DayMeta) => {
      if (doctorId === null) return;
      setByDay((prev) => ({ ...prev, [day.jalali]: { status: 'loading' } }));
      void load(doctorId, day, runId.current);
    },
    [doctorId, load]
  );

  return { byDay, refreshDay };
}

/** Pure helpers for the manual booking flow (slot grouping, availability). */

export type DayPart = 'morning' | 'afternoon' | 'evening';

export const DAY_PART_LABELS: Record<DayPart, string> = {
  morning: 'صبح',
  afternoon: 'بعدازظهر',
  evening: 'عصر',
};

export type DayAvailability =
  | { status: 'loading' }
  | { status: 'ready'; slots: string[] }
  | { status: 'error'; message: string };

const SLOT_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

/** «10:30:00» → «10:30»; drops junk and duplicates; sorted ascending. */
export function normalizeSlots(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const cleaned = raw
    .map((slot) => String(slot ?? '').slice(0, 5))
    .filter((slot) => SLOT_RE.test(slot));
  return Array.from(new Set(cleaned)).sort();
}

export function dayPartOf(slot: string): DayPart {
  const hour = Number(slot.slice(0, 2));
  if (hour < 12) return 'morning';
  if (hour < 16) return 'afternoon';
  return 'evening';
}

export interface SlotGroup {
  part: DayPart;
  label: string;
  slots: string[];
}

/** Only non-empty groups, in chronological order. */
export function groupSlotsByDayPart(slots: string[]): SlotGroup[] {
  const order: DayPart[] = ['morning', 'afternoon', 'evening'];
  return order
    .map((part) => ({
      part,
      label: DAY_PART_LABELS[part],
      slots: slots.filter((slot) => dayPartOf(slot) === part),
    }))
    .filter((group) => group.slots.length > 0);
}

export interface EarliestSlot {
  dayKey: string;
  slot: string;
}

/**
 * Nearest free slot across days, given in chronological order.
 *
 * Returns ``'pending'`` while an earlier day is still loading (the answer
 * could still change), ``null`` when every day is known and none has a free
 * slot. Days that failed to load are skipped rather than blocking the answer.
 */
export function findEarliestSlot(
  dayKeys: string[],
  availability: Record<string, DayAvailability | undefined>
): EarliestSlot | 'pending' | null {
  for (const dayKey of dayKeys) {
    const entry = availability[dayKey];
    if (!entry || entry.status === 'loading') return 'pending';
    if (entry.status === 'ready' && entry.slots.length > 0) {
      return { dayKey, slot: entry.slots[0] };
    }
  }
  return null;
}

/** «دکتر مینا رضایی» → «مر»: first letters of the first two name words. */
export function initialsOf(fullName: string): string {
  const words = fullName
    .replace(/^(دکتر|دکترا|خانم|آقای)\s+/u, '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  return words
    .slice(0, 2)
    .map((word) => Array.from(word)[0])
    .join('\u200c');
}

/** Case/ZWNJ-insensitive match used by the staff patient search. */
export function matchesQuery(haystacks: Array<string | null | undefined>, query: string): boolean {
  const normalize = (value: string) =>
    value
      .replace(/[\u200c\s]/g, '')
      .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
      .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
      .toLowerCase();
  const needle = normalize(query);
  if (!needle) return true;
  return haystacks.some((text) => normalize(text ?? '').includes(needle));
}

import React from 'react';
import { toPersianDigits } from '../../utils/persianDate';
import { ToothCondition } from '../../types';

/**
 * Visual FDI dental chart (32 permanent teeth).
 *
 * Layout follows the clinical mirror convention: the patient's right side is
 * drawn on the viewer's left, with quadrants 1/3 (patient right) on the left
 * column and quadrants 2/4 (patient left) on the right column. The container
 * is forced to LTR so the anatomical layout stays stable inside the RTL app.
 *
 * Statuses arrive sparse (only charted teeth); every other tooth renders
 * healthy. Clicking a tooth reports it to the parent for the details panel
 * or, in editable mode, for the status setter.
 */

const UPPER_RIGHT = [18, 17, 16, 15, 14, 13, 12, 11];
const UPPER_LEFT = [21, 22, 23, 24, 25, 26, 27, 28];
const LOWER_RIGHT = [48, 47, 46, 45, 44, 43, 42, 41];
const LOWER_LEFT = [31, 32, 33, 34, 35, 36, 37, 38];

export const TOOTH_CONDITION_STYLES: Record<
  ToothCondition,
  { cell: string; label: string }
> = {
  healthy: {
    cell: 'bg-surface border-line-strong text-muted',
    label: 'سالم',
  },
  treated: {
    cell: 'bg-primary border-primary text-on-accent',
    label: 'درمان‌شده',
  },
  needs_treatment: {
    cell: 'bg-[#FFF7E6] border-[#F0B429] text-[#9A6700]',
    label: 'نیاز به درمان',
  },
  extracted: {
    cell: 'bg-line-soft border-line-strong text-faint line-through',
    label: 'کشیده‌شده',
  },
};

interface DentalChartProps {
  /** Sparse map: FDI number -> condition. Missing teeth are healthy. */
  teeth: Record<number, ToothCondition>;
  selectedTooth?: number | null;
  onSelectTooth?: (fdi: number) => void;
  disabled?: boolean;
}

const ToothCell: React.FC<{
  fdi: number;
  condition: ToothCondition;
  selected: boolean;
  disabled?: boolean;
  onSelect?: (fdi: number) => void;
}> = ({ fdi, condition, selected, disabled, onSelect }) => {
  const style = TOOTH_CONDITION_STYLES[condition] || TOOTH_CONDITION_STYLES.healthy;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSelect?.(fdi)}
      title={`دندان ${toPersianDigits(fdi)} — ${style.label}`}
      aria-label={`دندان ${toPersianDigits(fdi)}، ${style.label}`}
      className={`w-8 h-9 sm:w-9 sm:h-10 rounded-[9px] border text-caption font-extrabold tabular-nums flex flex-col items-center justify-center gap-0.5 transition-all ${style.cell} ${
        selected
          ? 'ring-2 ring-offset-1 ring-primary ring-offset-white scale-[1.04]'
          : ''
      } ${disabled ? 'cursor-default' : 'hover:scale-[1.06] cursor-pointer'}`}
    >
      <span className="leading-none">{toPersianDigits(fdi)}</span>
    </button>
  );
};

export const DentalChart: React.FC<DentalChartProps> = ({
  teeth,
  selectedTooth = null,
  onSelectTooth,
  disabled = false,
}) => {
  const conditionOf = (fdi: number): ToothCondition => teeth[fdi] || 'healthy';

  return (
    <div dir="ltr" className="w-full overflow-x-auto pb-1">
      <div className="min-w-[360px] space-y-2.5">
        {/* Upper arch */}
        <div className="grid grid-cols-2 gap-x-2.5">
          <div className="flex justify-start gap-1">
            {UPPER_RIGHT.map((fdi) => (
              <ToothCell
                key={fdi}
                fdi={fdi}
                condition={conditionOf(fdi)}
                selected={selectedTooth === fdi}
                disabled={disabled}
                onSelect={onSelectTooth}
              />
            ))}
          </div>
          <div className="flex justify-end gap-1">
            {UPPER_LEFT.map((fdi) => (
              <ToothCell
                key={fdi}
                fdi={fdi}
                condition={conditionOf(fdi)}
                selected={selectedTooth === fdi}
                disabled={disabled}
                onSelect={onSelectTooth}
              />
            ))}
          </div>
        </div>

        {/* Midline */}
        <div className="relative h-px bg-line mx-1">
          <span className="absolute -top-2.5 right-1/2 translate-x-1/2 bg-surface px-2 text-caption font-bold text-faint">
            خط وسط
          </span>
        </div>

        {/* Lower arch */}
        <div className="grid grid-cols-2 gap-x-2.5">
          <div className="flex justify-start gap-1">
            {LOWER_RIGHT.map((fdi) => (
              <ToothCell
                key={fdi}
                fdi={fdi}
                condition={conditionOf(fdi)}
                selected={selectedTooth === fdi}
                disabled={disabled}
                onSelect={onSelectTooth}
              />
            ))}
          </div>
          <div className="flex justify-end gap-1">
            {LOWER_LEFT.map((fdi) => (
              <ToothCell
                key={fdi}
                fdi={fdi}
                condition={conditionOf(fdi)}
                selected={selectedTooth === fdi}
                disabled={disabled}
                onSelect={onSelectTooth}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export const DentalChartLegend: React.FC = () => (
  <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 pt-2">
    {(Object.keys(TOOTH_CONDITION_STYLES) as ToothCondition[]).map((key) => (
      <span key={key} className="inline-flex items-center gap-1.5">
        <span
          className={`w-3 h-3 rounded-[4px] border ${TOOTH_CONDITION_STYLES[key].cell}`}
        />
        <span className="text-caption text-muted">
          {TOOTH_CONDITION_STYLES[key].label}
        </span>
      </span>
    ))}
  </div>
);

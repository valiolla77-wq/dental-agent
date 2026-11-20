import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl';
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  maxWidth = 'lg',
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose();
    };
    if (isOpen) {
      document.body.style.overflow = 'hidden';
      window.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.body.style.overflow = 'unset';
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const maxWidthClasses = {
    sm: 'max-w-sm',
    md: 'max-w-md',
    lg: 'max-w-lg',
    xl: 'max-w-xl',
    '2xl': 'max-w-2xl',
    '3xl': 'max-w-3xl',
    '4xl': 'max-w-4xl',
  };

  const modal = (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[100] flex items-end sm:items-center justify-center p-2 sm:p-5 bg-ink-deep/45 backdrop-blur-[2px] d-fade"
    >
      <div className="fixed inset-0" onClick={onClose} aria-hidden="true" />
      <div
        className={`relative z-10 flex min-h-0 w-full flex-col overflow-hidden ${maxWidthClasses[maxWidth]} max-h-[calc(100dvh-1rem)] rounded-[20px] border border-line bg-surface shadow-[0_24px_80px_-24px_rgba(23,43,71,0.35)] sm:max-h-[92vh] sm:rounded-[24px]`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 px-4 py-4 sm:px-6 sm:py-5 border-b border-line-soft">
          <div className="min-w-0">
            <h3 className="text-heading font-bold text-ink leading-6 break-words">
              {title}
            </h3>
            {subtitle && (
              <p className="text-caption text-muted mt-1 leading-5 break-words">
                {subtitle}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="بستن پنجره"
            className="p-1.5 -mt-1 -ml-1 text-faint hover:text-ink hover:bg-canvas rounded-[10px] transition-colors shrink-0"
          >
            <X className="w-4.5 h-4.5" />
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-4 sm:px-6 sm:py-5">
          {children}
        </div>
      </div>
    </div>
  );

  // Render at the document root. Views animate with a CSS transform, which
  // turns `position: fixed` descendants into a local containing block and
  // would otherwise trap the modal under the sticky header / inside the page
  // scroll area.
  return createPortal(modal, document.body);
};

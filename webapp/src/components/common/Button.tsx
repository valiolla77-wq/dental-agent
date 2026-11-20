import React from 'react';
import { Loader2 } from 'lucide-react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'danger' | 'ghost' | 'teal' | 'ai';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  icon?: React.ReactNode;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  icon,
  className = '',
  disabled,
  ...props
}) => {
  const base =
    'inline-flex items-center justify-center font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 focus-visible:ring-offset-1 disabled:opacity-50 disabled:pointer-events-none rounded-[10px] whitespace-nowrap shrink-0';

  const variants = {
    primary:
      'bg-primary text-on-accent hover:bg-primary-deep active:bg-[#075A5D] shadow-[0_1px_2px_rgba(8,127,131,0.16)]',
    teal:
      'bg-primary text-on-accent hover:bg-primary-deep active:bg-[#075A5D] shadow-[0_1px_2px_rgba(8,127,131,0.16)]',
    secondary:
      'bg-primary-soft text-primary-deep border border-primary-line hover:bg-primary-hover',
    outline:
      'border border-line text-ink bg-surface hover:bg-surface-muted hover:border-primary-line',
    danger: 'bg-danger text-on-accent hover:bg-[#A03547]',
    ghost: 'text-muted hover:bg-canvas hover:text-ink',
    ai: 'bg-ai text-on-accent hover:bg-[#5351A6]',
  };

  const sizes = {
    sm: 'text-small px-3 gap-1.5 h-8',
    md: 'text-small px-4 gap-2 h-10',
    lg: 'text-body px-5 gap-2 h-11',
  };

  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          <span>{children}</span>
        </>
      ) : (
        <>
          {icon && <span className="shrink-0">{icon}</span>}
          <span>{children}</span>
        </>
      )}
    </button>
  );
};

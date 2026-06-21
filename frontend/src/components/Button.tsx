import { ButtonHTMLAttributes, ReactNode } from 'react';

type Variant = 'primary' | 'secondary' | 'spark' | 'outline' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: Variant;
  size?: Size;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const variantStyles: Record<Variant, string> = {
  primary:
    'bg-walmart-blue text-white hover:bg-walmart-blue/90 active:bg-walmart-blue/80 shadow-sm',
  secondary:
    'bg-walmart-navy text-white hover:bg-walmart-navy/90 active:bg-walmart-navy/80 shadow-sm',
  spark:
    'bg-walmart-spark text-walmart-navy hover:bg-walmart-spark-dark active:brightness-95 shadow-sm font-semibold',
  outline:
    'bg-white text-walmart-navy border border-walmart-navy/20 hover:bg-walmart-navy/5 active:bg-walmart-navy/10',
  ghost:
    'bg-transparent text-walmart-navy hover:bg-walmart-navy/5 active:bg-walmart-navy/10',
  danger:
    'bg-sentiment-negative text-white hover:bg-sentiment-negative/90 active:bg-sentiment-negative/80 shadow-sm',
};

const sizeStyles: Record<Size, string> = {
  sm: 'text-xs px-3 py-1.5 gap-1.5',
  md: 'text-sm px-4 py-2 gap-2',
  lg: 'text-base px-5 py-2.5 gap-2',
};

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  leftIcon,
  rightIcon,
  className = '',
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center font-medium rounded-pill transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-walmart-blue focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      disabled={disabled}
      {...rest}
    >
      {leftIcon && <span className="shrink-0">{leftIcon}</span>}
      {children}
      {rightIcon && <span className="shrink-0">{rightIcon}</span>}
    </button>
  );
}

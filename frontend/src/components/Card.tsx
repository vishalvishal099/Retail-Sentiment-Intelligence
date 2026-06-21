import { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padded?: boolean;
  hoverable?: boolean;
}

export default function Card({
  children,
  padded = true,
  hoverable = false,
  className = '',
  ...rest
}: CardProps) {
  return (
    <div
      className={`bg-surface rounded-2xl shadow-card border border-walmart-navy/5 ${
        padded ? 'p-5' : ''
      } ${hoverable ? 'transition-shadow hover:shadow-card-hover' : ''} ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  accent?: boolean;
}

export function CardHeader({ title, subtitle, action, accent = false }: CardHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-3 mb-4">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {accent && <span className="inline-block w-1 h-5 rounded-full bg-walmart-spark" />}
          <h3 className="text-base font-semibold text-walmart-navy truncate">{title}</h3>
        </div>
        {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

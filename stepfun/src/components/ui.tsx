import type { ReactNode } from 'react';

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = '',
  id,
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} id={id}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p className="panel-sub">{subtitle}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Pill({
  tone = 'neutral',
  children,
  title,
}: {
  tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'accent';
  children: ReactNode;
  title?: string;
}) {
  return (
    <span className={`pill pill-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'ok' | 'warn';
}) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label?: string }) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div className="progress-wrap">
      {label && <span className="progress-label">{label}</span>}
      <div className="progress" role="progressbar" aria-valuenow={Math.round(clamped)} aria-valuemin={0} aria-valuemax={100}>
        <div className="progress-fill" style={{ width: `${clamped}%` }} />
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}

export function SectionLabel({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="section-label">
      <span>{children}</span>
      {aside && <span className="section-aside">{aside}</span>}
    </div>
  );
}

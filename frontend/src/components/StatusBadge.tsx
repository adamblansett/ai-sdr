interface StatusBadgeProps {
  value: string;
}

const STYLE_MAP: Record<string, string> = {
  active: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  approved: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  sent: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  completed: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  merged: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  high: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  a: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  b: 'bg-sky-50 text-sky-700 border-sky-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  pending: 'bg-amber-50 text-amber-700 border-amber-200',
  pending_approval: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-100 text-slate-700 border-slate-200',
  c: 'bg-amber-50 text-amber-700 border-amber-200',
  dismissed: 'bg-slate-100 text-slate-600 border-slate-200',
  paused: 'bg-slate-100 text-slate-600 border-slate-200',
  rejected: 'bg-rose-50 text-rose-700 border-rose-200',
  suppressed: 'bg-rose-50 text-rose-700 border-rose-200',
  blocked_suppressed: 'bg-rose-50 text-rose-700 border-rose-200',
  disqualified: 'bg-rose-50 text-rose-700 border-rose-200',
  d: 'bg-rose-50 text-rose-700 border-rose-200',
};

export function StatusBadge({ value }: StatusBadgeProps) {
  const key = value.trim().toLowerCase();
  const classes = STYLE_MAP[key] || 'bg-slate-100 text-slate-700 border-slate-200';
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${classes}`}
    >
      {value.replace(/_/g, ' ')}
    </span>
  );
}

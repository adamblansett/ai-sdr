import { Database, ShieldAlert, Sparkles } from 'lucide-react';
import type { ApprovalRequestItem, OverviewSummary } from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface OverviewViewProps {
  overview: OverviewSummary | null;
  approvals: ApprovalRequestItem[];
  onNavigate: (tab: string) => void;
  onLoadDemo: () => void;
  busy: boolean;
  offline: boolean;
}

const PLANNED_CAPABILITIES = [
  {
    title: 'Outbound Prospecting',
    summary:
      'Account research synthesis from public signals with strict opt-out and compliance checks.',
  },
  {
    title: 'Lead Qualification',
    summary:
      'Structured ICP scoring, buying-intent classification, and BANT/MEDDIC field extraction.',
  },
  {
    title: 'Personalized Sequences',
    summary:
      'Human-approved multi-touch email and follow-up drafts grounded in verified account facts.',
  },
  {
    title: 'CRM Pipeline Hygiene',
    summary:
      'Automated contact deduplication, stage validation, and next-step summarization.',
  },
];

export function OverviewView({
  overview,
  approvals,
  onNavigate,
  onLoadDemo,
  busy,
  offline,
}: OverviewViewProps) {
  const pendingApprovals = approvals.filter((a) => a.status === 'pending').slice(0, 6);

  return (
    <div className="space-y-6">
      {!offline && overview && overview.accounts_total === 0 && (
        <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-indigo-200 bg-indigo-50 p-5">
          <div>
            <h2 className="text-sm font-semibold text-indigo-950">
              Initialize AI SDR Workspace
            </h2>
            <p className="mt-1 text-xs text-indigo-800">
              Load the sample dataset (4 accounts, 7 verified signals, suppression rules, BANT/MEDDIC
              qualifications, 3-touch sequence, and CRM hygiene deals) to test every workflow.
            </p>
          </div>
          <button
            type="button"
            onClick={onLoadDemo}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
          >
            <Database className="h-3.5 w-3.5" />
            {busy ? 'Loading...' : 'Load Demo Dataset'}
          </button>
        </div>
      )}

      {overview && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500">Target Accounts &amp; Signals</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{overview.accounts_total}</p>
            <p className="mt-1 text-xs text-slate-600">
              {overview.signals_total} signals · {overview.suppressed_accounts} suppressed
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500">Lead Qualification</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{overview.avg_icp_score}</p>
            <p className="mt-1 text-xs text-slate-600">
              Avg ICP · {overview.high_intent_leads} high-intent / {overview.qualifications_total}{' '}
              scored
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500">Outbound Approval Gate</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">
              {overview.touches_pending_approval}
            </p>
            <p className="mt-1 text-xs text-slate-600">
              Pending review · {overview.touches_approved} approved · {overview.touches_sent} sent
            </p>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-xs font-medium text-slate-500">CRM Hygiene Score</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{overview.avg_hygiene_score}</p>
            <p className="mt-1 text-xs text-slate-600">
              {overview.hygiene_issues_open} open issues · {overview.pending_merges} merge candidates
            </p>
          </div>
        </section>
      )}

      <section className="grid gap-4 sm:grid-cols-2">
        {PLANNED_CAPABILITIES.map((item) => (
          <article
            key={item.title}
            className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <h2 className="text-sm font-semibold text-slate-900">{item.title}</h2>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{item.summary}</p>
          </article>
        ))}
      </section>

      {!offline && (
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4 text-amber-600" />
              <h3 className="text-sm font-semibold text-slate-900">
                Pending Human-in-the-Loop Approvals ({pendingApprovals.length})
              </h3>
            </div>
            <button
              type="button"
              onClick={() => onNavigate('audit')}
              className="inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800"
            >
              <Sparkles className="h-3.5 w-3.5" />
              Open Approval Queue
            </button>
          </div>
          {pendingApprovals.length === 0 ? (
            <p className="mt-3 text-xs text-slate-500">
              No pending approval items. Generate a sequence or scan duplicate contacts to queue
              reviews.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-slate-100">
              {pendingApprovals.map((app) => (
                <li key={app.id} className="flex items-center justify-between gap-4 py-2.5 text-xs">
                  <div>
                    <p className="font-medium text-slate-900">{app.summary}</p>
                    <p className="text-[11px] text-slate-500">
                      {app.entity_type} · requested by {app.requested_by}
                    </p>
                  </div>
                  <StatusBadge value={app.risk_level} />
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

import { useState, type FormEvent } from 'react';
import { Check, EyeOff, ShieldCheck, X } from 'lucide-react';
import { decideApproval, previewPiiRedaction, verifyAuditChain } from '../api/client';
import type {
  ActorContext,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  PiiRedactionResult,
} from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface AuditViewProps {
  actor: ActorContext;
  approvals: ApprovalRequestItem[];
  events: AuditEventItem[];
  chainStatus: AuditChainVerify | null;
  onChainVerified: (status: AuditChainVerify) => void;
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function AuditView({
  actor,
  approvals,
  events,
  chainStatus,
  onChainVerified,
  onRefresh,
  onNotify,
}: AuditViewProps) {
  const [piiInput, setPiiInput] = useState(
    'Reach Elena at elena@helioscloud.io or +1-512-555-0142 (SSN 123-45-6789, Bearer sk-live-secret1234567890).',
  );
  const [piiResult, setPiiResult] = useState<PiiRedactionResult | null>(null);

  const isManager = actor.role === 'sales_manager';

  async function handleDecide(approvalId: string, decision: 'approved' | 'rejected') {
    try {
      await decideApproval(actor, approvalId, decision, `${decision} via Audit queue`);
      onNotify(`Approval ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval action failed', true);
    }
  }

  async function handleVerifyChain() {
    try {
      const res = await verifyAuditChain(actor);
      onChainVerified(res);
      onNotify(res.message, !res.valid);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Chain verification failed', true);
    }
  }

  async function handlePiiPreview(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await previewPiiRedaction(actor, piiInput);
      setPiiResult(res);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'PII preview failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">
          Human-in-the-Loop Approvals ({approvals.length})
        </h2>
        <div className="mt-3 space-y-2.5">
          {approvals.map((app) => (
            <div
              key={app.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-3.5 text-xs"
            >
              <div>
                <p className="font-semibold text-slate-900">{app.summary}</p>
                <p className="text-slate-500">
                  {app.entity_type} · {app.action_requested} · requested by {app.requested_by}
                  {app.decided_by ? ` · decided by ${app.decided_by}` : ''}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge value={app.risk_level} />
                <StatusBadge value={app.status} />
                {isManager && app.status === 'pending' && (
                  <>
                    <button
                      type="button"
                      onClick={() => handleDecide(app.id, 'approved')}
                      className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700"
                    >
                      <Check className="h-3 w-3" />
                      Approve
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDecide(app.id, 'rejected')}
                      className="inline-flex items-center gap-1 rounded bg-rose-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-rose-700"
                    >
                      <X className="h-3 w-3" />
                      Reject
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <EyeOff className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Cloud LLM PII Redaction Guardrail Preview
          </h2>
        </div>
        <form onSubmit={handlePiiPreview} className="space-y-2">
          <textarea
            rows={3}
            aria-label="PII Redaction Input"
            value={piiInput}
            onChange={(e) => setPiiInput(e.target.value)}
            className="w-full rounded-lg border border-slate-200 p-2.5 text-xs"
          />
          <button
            type="submit"
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
          >
            Test Cloud PII Scrubbing
          </button>
        </form>
        {piiResult && (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs">
            <p className="font-semibold text-emerald-900">
              Scrubbed Output ({piiResult.total_redactions} redaction(s)):
            </p>
            <p className="mt-1 font-mono text-emerald-800">{piiResult.redacted_text}</p>
          </div>
        )}
      </section>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-600" />
            <h2 className="text-sm font-semibold text-slate-900">
              Immutable SHA-256 Audit Trail ({events.length})
            </h2>
          </div>
          <button
            type="button"
            onClick={handleVerifyChain}
            className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-100"
          >
            Verify Hash Chain
          </button>
        </div>

        {chainStatus && (
          <div
            className={`rounded-lg border px-3 py-2 text-xs font-medium ${
              chainStatus.valid
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-rose-200 bg-rose-50 text-rose-800'
            }`}
          >
            {chainStatus.message} (head: {chainStatus.head_hash.slice(0, 16)}...)
          </div>
        )}

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2 pr-3">#</th>
                <th className="py-2 pr-3">Event</th>
                <th className="py-2 pr-3">Actor</th>
                <th className="py-2 pr-3">Entity</th>
                <th className="py-2">Hash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {events.map((ev) => (
                <tr key={ev.id}>
                  <td className="py-2 pr-3 font-mono text-slate-500">{ev.sequence_no}</td>
                  <td className="py-2 pr-3 font-medium text-slate-900">
                    {ev.event_type} ({ev.action})
                  </td>
                  <td className="py-2 pr-3 text-slate-600">
                    {ev.actor_email} [{ev.actor_role}]
                  </td>
                  <td className="py-2 pr-3 text-slate-600">{ev.entity_type}</td>
                  <td className="py-2 font-mono text-[11px] text-slate-500">
                    {ev.event_hash.slice(0, 14)}...
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

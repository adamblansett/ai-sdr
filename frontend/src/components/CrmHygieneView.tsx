import { useState, type FormEvent } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  GitMerge,
  Plus,
  RefreshCw,
  Sparkles,
  Webhook,
} from 'lucide-react';
import {
  createDeal,
  decideApproval,
  pushCrmSync,
  scanDuplicates,
  simulateWebhook,
  synthesizeDealNextStep,
  validateDealHygieneAll,
} from '../api/client';
import type {
  AccountItem,
  ActorContext,
  CrmDealItem,
  CrmSyncJobItem,
  CrmWebhookEventItem,
  DuplicateCandidateItem,
  QualificationItem,
} from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface CrmHygieneViewProps {
  actor: ActorContext;
  accounts: AccountItem[];
  deals: CrmDealItem[];
  duplicates: DuplicateCandidateItem[];
  webhooks: CrmWebhookEventItem[];
  qualifications: QualificationItem[];
  syncJobs: CrmSyncJobItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function CrmHygieneView({
  actor,
  accounts,
  deals,
  duplicates,
  webhooks,
  qualifications,
  syncJobs,
  onRefresh,
  onNotify,
}: CrmHygieneViewProps) {
  const [accountId, setAccountId] = useState('');
  const [dealName, setDealName] = useState('');
  const [stage, setStage] = useState('discovery');
  const [amount, setAmount] = useState('35000');

  const [webhookSource, setWebhookSource] = useState('hubspot');
  const [webhookEventId, setWebhookEventId] = useState('demo-evt-1001');
  const [webhookEmail, setWebhookEmail] = useState('maya@acme.io');

  const [syncOp, setSyncOp] = useState<
    'deal_next_step_sync' | 'qualification_sync' | 'contact_merge_sync'
  >('deal_next_step_sync');
  const [syncEntityId, setSyncEntityId] = useState('');

  const canWrite = actor.role !== 'viewer';
  const isManager = actor.role === 'sales_manager';
  const accountMap = new Map(accounts.map((a) => [a.id, a]));

  async function handleValidateAll() {
    try {
      const res = await validateDealHygieneAll(actor);
      onNotify(
        `Validated ${res.deals_checked} deals (${res.deals_flagged} flagged, avg hygiene ${res.avg_hygiene_score}).`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Hygiene validation failed', true);
    }
  }

  async function handleScanDuplicates() {
    try {
      const res = await scanDuplicates(actor);
      onNotify(`Duplicate scan created ${res.candidates_created} merge candidate(s).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Duplicate scan failed', true);
    }
  }

  async function handleNextStep(dealId: string) {
    try {
      const updated = await synthesizeDealNextStep(actor, dealId);
      onNotify(`Synthesized next step (hygiene ${updated.hygiene_score}/100).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Next step synthesis failed', true);
    }
  }

  async function handleMergeDecision(approvalId: string, decision: 'approved' | 'rejected') {
    try {
      await decideApproval(actor, approvalId, decision, `${decision} from CRM Hygiene`);
      onNotify(`Merge candidate ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Merge decision failed', true);
    }
  }

  async function handleCreateDeal(e: FormEvent) {
    e.preventDefault();
    const targetAccountId = accountId || accounts[0]?.id;
    if (!targetAccountId) {
      onNotify('Create an account first.', true);
      return;
    }
    try {
      await createDeal(actor, {
        account_id: targetAccountId,
        name: dealName,
        stage,
        amount_usd: Number(amount) || 0,
        next_step: '',
      });
      setDealName('');
      onNotify(`Created deal ${dealName}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Deal creation failed', true);
    }
  }

  async function handleSimulateWebhook(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await simulateWebhook(actor, webhookSource, {
        event_id: webhookEventId,
        event_type: 'contact.upsert',
        data: {
          email: webhookEmail,
          first_name: 'Synced',
          last_name: 'Contact',
          title: 'Director RevOps',
        },
      });
      onNotify(
        res.duplicate_ignored
          ? `Idempotent replay ignored (${res.idempotency_key}).`
          : `Processed webhook: ${res.result_summary}`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Webhook failed', true);
    }
  }

  const syncTargets =
    syncOp === 'deal_next_step_sync'
      ? deals.map((d) => ({ id: d.id, label: `${d.name} (${d.stage})` }))
      : syncOp === 'qualification_sync'
      ? qualifications.map((q) => ({
          id: q.id,
          label: `${accountMap.get(q.account_id)?.name || q.account_id} (Grade ${q.grade})`,
        }))
      : duplicates
          .filter((m) => m.status === 'merged')
          .map((m) => ({ id: m.id, label: `${m.primary_email} ← ${m.duplicate_email}` }));
  const resolvedSyncEntityId =
    syncEntityId && syncTargets.some((t) => t.id === syncEntityId)
      ? syncEntityId
      : syncTargets[0]?.id || '';

  async function handlePushSync(e: FormEvent) {
    e.preventDefault();
    if (!resolvedSyncEntityId) {
      onNotify('No eligible entity available for selected CRM sync operation.', true);
      return;
    }
    try {
      const job = await pushCrmSync(actor, {
        operation: syncOp,
        entity_id: resolvedSyncEntityId,
      });
      onNotify(`CRM sync ${job.status}: ${job.response_summary}`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'CRM sync failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">CRM Pipeline Hygiene Controls</h2>
          <p className="text-xs text-slate-500">
            Detect stale opportunities, missing BANT/MEDDIC qualification gates, and duplicate
            contacts.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!canWrite}
            onClick={handleValidateAll}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Validate Pipeline Hygiene
          </button>
          <button
            type="button"
            disabled={!canWrite}
            onClick={handleScanDuplicates}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <GitMerge className="h-3.5 w-3.5" />
            Scan Duplicate Contacts
          </button>
        </div>
      </div>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">
          Pipeline Deals ({deals.length})
        </h3>

        <form onSubmit={handleCreateDeal} className="flex flex-wrap gap-2">
          <select
            value={accountId || accounts[0]?.id || ''}
            onChange={(e) => setAccountId(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <input
            required
            placeholder="Deal Name"
            value={dealName}
            onChange={(e) => setDealName(e.target.value)}
            className="min-w-[180px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            <option value="discovery">discovery</option>
            <option value="qualification">qualification</option>
            <option value="proposal">proposal</option>
            <option value="negotiation">negotiation</option>
          </select>
          <input
            type="number"
            placeholder="Amount USD"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-28 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite || accounts.length === 0}
            className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Deal
          </button>
        </form>

        <div className="space-y-3 pt-2">
          {deals.map((deal) => (
            <div key={deal.id} className="rounded-lg border border-slate-200 p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{deal.name}</p>
                  <p className="text-xs text-slate-500">
                    {accountMap.get(deal.account_id)?.name || deal.account_id} · Stage:{' '}
                    {deal.stage} · ${deal.amount_usd.toLocaleString()} · Close:{' '}
                    {deal.close_date || 'Unset'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                      deal.hygiene_score >= 80
                        ? 'bg-emerald-50 text-emerald-700'
                        : deal.hygiene_score >= 50
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-rose-50 text-rose-700'
                    }`}
                  >
                    Hygiene {deal.hygiene_score}/100
                  </span>
                  <button
                    type="button"
                    disabled={!canWrite}
                    onClick={() => handleNextStep(deal.id)}
                    className="inline-flex items-center gap-1 rounded border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
                  >
                    <Sparkles className="h-3 w-3" />
                    Synthesize Next Step
                  </button>
                </div>
              </div>

              {deal.next_step && (
                <p className="mt-2 text-xs text-slate-700">
                  <span className="font-semibold">Next Step:</span> {deal.next_step}
                </p>
              )}

              {deal.hygiene_issues.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {deal.hygiene_issues.map((issue) => (
                    <li
                      key={issue.code}
                      className="flex items-center gap-1.5 text-xs text-rose-700"
                    >
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                      <span>
                        [{issue.severity}] {issue.message}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">
          Duplicate Contact Merge Candidates ({duplicates.length})
        </h3>
        <div className="mt-3 space-y-2.5">
          {duplicates.length === 0 ? (
            <p className="text-xs text-slate-500">No duplicate contact pairs detected.</p>
          ) : (
            duplicates.map((cand) => (
              <div
                key={cand.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-3.5 text-xs"
              >
                <div>
                  <p className="font-semibold text-slate-900">
                    Keep {cand.primary_name} ({cand.primary_email}) ← Merge {cand.duplicate_name}{' '}
                    ({cand.duplicate_email})
                  </p>
                  <p className="text-slate-500">
                    Match: {cand.match_reason} ({Math.round(cand.confidence * 100)}% confidence)
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge value={cand.status} />
                  {isManager && cand.status === 'pending_approval' && cand.approval_id && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleMergeDecision(cand.approval_id!, 'approved')}
                        className="rounded bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700"
                      >
                        Approve Merge
                      </button>
                      <button
                        type="button"
                        onClick={() => handleMergeDecision(cand.approval_id!, 'rejected')}
                        className="rounded bg-rose-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-rose-700"
                      >
                        Dismiss
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Webhook className="h-4 w-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">
            Idempotent CRM Webhooks ({webhooks.length})
          </h3>
        </div>

        <form onSubmit={handleSimulateWebhook} className="mt-3 flex flex-wrap gap-2">
          <select
            value={webhookSource}
            onChange={(e) => setWebhookSource(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            <option value="hubspot">hubspot</option>
            <option value="salesforce">salesforce</option>
          </select>
          <input
            required
            placeholder="Idempotency Key / event_id"
            value={webhookEventId}
            onChange={(e) => setWebhookEventId(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            required
            type="email"
            placeholder="Contact email"
            value={webhookEmail}
            onChange={(e) => setWebhookEmail(e.target.value)}
            className="min-w-[200px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite}
            className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            Send Webhook
          </button>
        </form>

        <ul className="mt-3 divide-y divide-slate-100 text-xs">
          {webhooks.map((ev) => (
            <li key={ev.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <span className="font-semibold text-slate-900">
                  [{ev.source}] {ev.event_type}
                </span>
                <span className="ml-2 text-slate-500">key={ev.idempotency_key}</span>
                <p className="text-slate-600">{ev.result_summary}</p>
              </div>
              <StatusBadge value={ev.status} />
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <ArrowUpRight className="h-4 w-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">
            Outbound CRM Sync Connector ({syncJobs.length})
          </h3>
        </div>
        <form onSubmit={handlePushSync} className="flex flex-wrap gap-2">
          <select
            value={syncOp}
            onChange={(e) => {
              setSyncOp(
                e.target.value as
                  | 'deal_next_step_sync'
                  | 'qualification_sync'
                  | 'contact_merge_sync',
              );
              setSyncEntityId('');
            }}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            <option value="deal_next_step_sync">deal_next_step_sync</option>
            <option value="qualification_sync">qualification_sync</option>
            <option value="contact_merge_sync">contact_merge_sync</option>
          </select>
          <select
            value={resolvedSyncEntityId}
            onChange={(e) => setSyncEntityId(e.target.value)}
            className="min-w-[220px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {syncTargets.length === 0 ? (
              <option value="">No eligible records</option>
            ) : (
              syncTargets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))
            )}
          </select>
          <button
            type="submit"
            disabled={!canWrite || !resolvedSyncEntityId}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            Push CRM Sync
          </button>
        </form>
        <ul className="divide-y divide-slate-100 text-xs">
          {syncJobs.map((job) => (
            <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <div>
                <span className="font-semibold text-slate-900">
                  [{job.provider}] {job.operation}
                </span>
                <span className="ml-2 text-slate-500">ext={job.external_record_id}</span>
                <p className="text-slate-600">{job.response_summary}</p>
              </div>
              <StatusBadge value={job.status} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

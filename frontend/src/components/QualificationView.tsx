import { useState, type FormEvent } from 'react';
import { Award, CheckCircle2, FileText } from 'lucide-react';
import { evaluateLead } from '../api/client';
import type {
  AccountItem,
  ActorContext,
  ContactItem,
  QualificationItem,
} from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface QualificationViewProps {
  actor: ActorContext;
  accounts: AccountItem[];
  contacts: ContactItem[];
  qualifications: QualificationItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function QualificationView({
  actor,
  accounts,
  contacts,
  qualifications,
  onRefresh,
  onNotify,
}: QualificationViewProps) {
  const [accountId, setAccountId] = useState('');
  const [contactId, setContactId] = useState('');
  const [notes, setNotes] = useState(
    'Budget approved for Q2 outbound automation pilot; manual CRM hygiene pain affecting 25% SQL conversion.',
  );
  const [busy, setBusy] = useState(false);

  const selectedAccountId = accountId || accounts[0]?.id || '';
  const accountContacts = contacts.filter((c) => c.account_id === selectedAccountId);
  const accountMap = new Map(accounts.map((a) => [a.id, a]));
  const canWrite = actor.role !== 'viewer';

  async function handleEvaluate(e: FormEvent) {
    e.preventDefault();
    if (!selectedAccountId) {
      onNotify('Create or seed an account before running qualification.', true);
      return;
    }
    setBusy(true);
    try {
      const res = await evaluateLead(actor, {
        account_id: selectedAccountId,
        contact_id: contactId || null,
        discovery_notes: notes,
      });
      onNotify(
        `Evaluated lead: ICP ${res.icp_score}/100 (Grade ${res.grade}, ${res.intent_tier} intent).`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Qualification evaluation failed', true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleEvaluate}
        className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div className="flex items-center gap-2">
          <Award className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Run Rubric ICP &amp; BANT/MEDDIC Qualification
          </h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs font-medium text-slate-700">
            <span>Target Account</span>
            <select
              value={selectedAccountId}
              onChange={(e) => {
                setAccountId(e.target.value);
                setContactId('');
              }}
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-normal"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.domain})
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-xs font-medium text-slate-700">
            <span>Primary Contact (Optional)</span>
            <select
              value={contactId}
              onChange={(e) => setContactId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-normal"
            >
              <option value="">Account-level scoring only</option>
              {accountContacts.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.first_name} {c.last_name} ({c.title || c.seniority})
                </option>
              ))}
            </select>
          </label>
        </div>

        <label className="block space-y-1 text-xs font-medium text-slate-700">
          <span>Discovery &amp; Qualification Notes</span>
          <textarea
            rows={3}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            className="w-full rounded-lg border border-slate-200 p-2.5 text-xs font-normal"
          />
        </label>

        <button
          type="submit"
          disabled={!canWrite || busy || accounts.length === 0}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          <CheckCircle2 className="h-3.5 w-3.5" />
          {busy ? 'Scoring...' : 'Evaluate Lead'}
        </button>
      </form>

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">
          Qualification Scorecards ({qualifications.length})
        </h2>
        {qualifications.map((q) => {
          const acc = accountMap.get(q.account_id);
          return (
            <article
              key={q.id}
              className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">
                    {acc ? `${acc.name} (${acc.domain})` : q.account_id}
                  </h3>
                  <p className="text-xs text-slate-500">
                    ICP Score: {q.icp_score}/100 · Engine: {q.llm_provider} ({q.llm_model})
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge value={q.grade} />
                  <StatusBadge value={q.intent_tier} />
                </div>
              </div>

              <p className="rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
                {q.rationale}
              </p>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-lg border border-slate-200 p-3.5">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    BANT Extraction
                  </h4>
                  <dl className="mt-2 space-y-1.5 text-xs">
                    {Object.entries(q.bant).map(([k, v]) => (
                      <div key={k}>
                        <dt className="font-semibold capitalize text-slate-800">{k}:</dt>
                        <dd className="text-slate-600">{v}</dd>
                      </div>
                    ))}
                  </dl>
                </div>

                <div className="rounded-lg border border-slate-200 p-3.5">
                  <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    MEDDIC Extraction
                  </h4>
                  <dl className="mt-2 space-y-1.5 text-xs">
                    {Object.entries(q.meddic).map(([k, v]) => (
                      <div key={k}>
                        <dt className="font-semibold capitalize text-slate-800">
                          {k.replace(/_/g, ' ')}:
                        </dt>
                        <dd className="text-slate-600">{v}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>

              {q.evidence_citations.length > 0 && (
                <div>
                  <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-slate-700">
                    <FileText className="h-3.5 w-3.5 text-indigo-600" />
                    Cited Public Evidence ({q.evidence_citations.length})
                  </h4>
                  <ul className="space-y-1.5">
                    {q.evidence_citations.map((cit) => (
                      <li
                        key={cit.signal_id}
                        className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
                      >
                        <span className="font-semibold text-slate-900">
                          [{cit.signal_type}] {cit.title}
                        </span>
                        <span className="ml-2 text-slate-500">
                          ({Math.round(cit.confidence * 100)}% confidence)
                        </span>
                        {cit.excerpt && <p className="mt-0.5 text-slate-600">{cit.excerpt}</p>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </article>
          );
        })}
      </section>
    </div>
  );
}

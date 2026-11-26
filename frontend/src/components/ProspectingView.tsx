import { useState, type FormEvent } from 'react';
import { Ban, BookOpen, Building2, Plus, Search, Sparkles, Upload, UserPlus } from 'lucide-react';
import {
  addAccountSignal,
  addSuppression,
  createAccount,
  createContact,
  createKnowledgeDocument,
  deactivateSuppression,
  importContactsCsv,
  researchAccount,
  searchKnowledge,
} from '../api/client';
import type {
  AccountItem,
  ActorContext,
  ContactItem,
  KnowledgeChunkItem,
  KnowledgeSearchHit,
  SuppressionEntryItem,
} from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface ProspectingViewProps {
  actor: ActorContext;
  accounts: AccountItem[];
  contacts: ContactItem[];
  suppressions: SuppressionEntryItem[];
  knowledgeDocs: KnowledgeChunkItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function ProspectingView({
  actor,
  accounts,
  contacts,
  suppressions,
  knowledgeDocs,
  onRefresh,
  onNotify,
}: ProspectingViewProps) {
  const [accName, setAccName] = useState('');
  const [accDomain, setAccDomain] = useState('');
  const [accIndustry, setAccIndustry] = useState('SaaS');
  const [accEmployees, setAccEmployees] = useState('200');
  const [accStack, setAccStack] = useState('Salesforce, AWS');

  const [sigAccountId, setSigAccountId] = useState('');
  const [sigType, setSigType] = useState('funding');
  const [sigTitle, setSigTitle] = useState('');
  const [sigUrl, setSigUrl] = useState('');

  const [contactAccountId, setContactAccountId] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [title, setTitle] = useState('');

  const [csvText, setCsvText] = useState(
    'first_name,last_name,email,title,company_name,domain\nJordan,Shaw,jordan@lumenops.io,VP Sales,LumenOps,lumenops.io',
  );

  const [supScope, setSupScope] = useState<'email' | 'domain'>('email');
  const [supValue, setSupValue] = useState('');
  const [supReason, setSupReason] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const [docType, setDocType] = useState<'case_study' | 'playbook' | 'note'>('case_study');
  const [docTitle, setDocTitle] = useState('');
  const [docContent, setDocContent] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchHits, setSearchHits] = useState<KnowledgeSearchHit[]>([]);

  const canWrite = actor.role !== 'viewer';
  const isManager = actor.role === 'sales_manager';

  async function handleCreateAccount(e: FormEvent) {
    e.preventDefault();
    try {
      await createAccount(actor, {
        name: accName,
        domain: accDomain,
        industry: accIndustry,
        employee_count: Number(accEmployees) || 0,
        tech_stack: accStack
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setAccName('');
      setAccDomain('');
      onNotify(`Created target account ${accName}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Account creation failed', true);
    }
  }

  async function handleAddSignal(e: FormEvent) {
    e.preventDefault();
    const targetId = sigAccountId || accounts[0]?.id;
    if (!targetId) {
      onNotify('Create an account before adding signals.', true);
      return;
    }
    try {
      await addAccountSignal(actor, targetId, {
        signal_type: sigType,
        title: sigTitle,
        summary: sigTitle,
        source_url: sigUrl || 'https://public-signal.example.com',
        weight: 25,
      });
      setSigTitle('');
      setSigUrl('');
      onNotify('Recorded verified buying signal.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Failed to add signal', true);
    }
  }

  async function handleResearch(accountId: string) {
    setBusyId(accountId);
    try {
      const res = await researchAccount(actor, accountId);
      onNotify(`Synthesized research for ${res.account.name} (${res.llm_provider}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Research synthesis failed', true);
    } finally {
      setBusyId(null);
    }
  }

  async function handleCreateContact(e: FormEvent) {
    e.preventDefault();
    const targetId = contactAccountId || accounts[0]?.id;
    if (!targetId) {
      onNotify('Select an account first.', true);
      return;
    }
    try {
      const created = await createContact(actor, {
        account_id: targetId,
        first_name: firstName,
        last_name: lastName,
        email,
        title,
      });
      setFirstName('');
      setLastName('');
      setEmail('');
      setTitle('');
      onNotify(
        created.is_suppressed
          ? `Added ${created.email} (flagged suppressed: ${created.suppression_reason}).`
          : `Added contact ${created.email}.`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Contact creation failed', true);
    }
  }

  async function handleCsvImport(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await importContactsCsv(actor, csvText);
      onNotify(
        `CSV import complete: ${res.contacts_created} contacts created, ${res.suppressed_flagged} suppressed.`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'CSV import failed', true);
    }
  }

  async function handleAddSuppression(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await addSuppression(actor, {
        scope: supScope,
        value: supValue,
        reason: supReason,
      });
      setSupValue('');
      setSupReason('');
      onNotify(
        `Suppression added (${res.entry.value}): ${res.contacts_affected} contacts updated, ${res.touches_blocked} touches blocked.`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Suppression update failed', true);
    }
  }

  async function handleDeactivateSuppression(entryId: string) {
    try {
      await deactivateSuppression(actor, entryId);
      onNotify('Deactivated suppression entry.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Deactivate failed', true);
    }
  }

  async function handleAddKnowledge(e: FormEvent) {
    e.preventDefault();
    try {
      await createKnowledgeDocument(actor, {
        source_type: docType,
        title: docTitle,
        content: docContent,
      });
      setDocTitle('');
      setDocContent('');
      onNotify('Indexed knowledge chunk with dense embeddings.');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Knowledge indexing failed', true);
    }
  }

  async function handleSemanticSearch(e: FormEvent) {
    e.preventDefault();
    try {
      const hits = await searchKnowledge(actor, { query: searchQuery, top_k: 4 });
      setSearchHits(hits);
      onNotify(`Found ${hits.length} semantic evidence match(es).`);
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Semantic search failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <section className="grid gap-4 lg:grid-cols-2">
        <form
          onSubmit={handleCreateAccount}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Add Target Account</h2>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              required
              placeholder="Company Name"
              value={accName}
              onChange={(e) => setAccName(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              required
              placeholder="Domain (e.g. acme.io)"
              value={accDomain}
              onChange={(e) => setAccDomain(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              placeholder="Industry"
              value={accIndustry}
              onChange={(e) => setAccIndustry(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              type="number"
              placeholder="Employees"
              value={accEmployees}
              onChange={(e) => setAccEmployees(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
          </div>
          <input
            placeholder="Tech stack (comma-separated)"
            value={accStack}
            onChange={(e) => setAccStack(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            Create Account
          </button>
        </form>

        <form
          onSubmit={handleAddSignal}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Log Public Buying Signal</h2>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={sigAccountId || accounts[0]?.id || ''}
              onChange={(e) => setSigAccountId(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            >
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.domain})
                </option>
              ))}
            </select>
            <select
              value={sigType}
              onChange={(e) => setSigType(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            >
              <option value="funding">funding</option>
              <option value="hiring">hiring</option>
              <option value="tech_migration">tech_migration</option>
              <option value="intent_surge">intent_surge</option>
              <option value="expansion">expansion</option>
            </select>
          </div>
          <input
            required
            placeholder="Verified signal headline"
            value={sigTitle}
            onChange={(e) => setSigTitle(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            placeholder="Source URL"
            value={sigUrl}
            onChange={(e) => setSigUrl(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite || accounts.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <Plus className="h-3.5 w-3.5" />
            Add Signal
          </button>
        </form>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">
          Target Accounts ({accounts.length})
        </h2>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {accounts.map((acc) => (
            <div key={acc.id} className="rounded-lg border border-slate-200 p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">{acc.name}</h3>
                  <p className="text-xs text-slate-500">
                    {acc.domain} · {acc.industry || 'General B2B'} · {acc.employee_count} emp
                  </p>
                </div>
                <StatusBadge value={acc.status} />
              </div>
              <div className="mt-2 flex flex-wrap gap-3 text-xs font-medium text-slate-700">
                <span>ICP Fit: {acc.icp_fit_score}/100</span>
                <span>Signal Score: {acc.signal_score}/100</span>
              </div>
              {acc.research_summary && (
                <p className="mt-2 text-xs leading-relaxed text-slate-600">
                  {acc.research_summary}
                </p>
              )}
              <div className="mt-3">
                <button
                  type="button"
                  disabled={!canWrite || busyId === acc.id}
                  onClick={() => handleResearch(acc.id)}
                  className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
                >
                  <Sparkles className="h-3 w-3" />
                  {busyId === acc.id ? 'Synthesizing...' : 'Synthesize AI Brief'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <form
          onSubmit={handleCreateContact}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Add Contact</h2>
          </div>
          <select
            value={contactAccountId || accounts[0]?.id || ''}
            onChange={(e) => setContactAccountId(e.target.value)}
            className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.domain})
              </option>
            ))}
          </select>
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              required
              placeholder="First Name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              required
              placeholder="Last Name"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              required
              type="email"
              placeholder="Work Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              placeholder="Job Title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
          </div>
          <button
            type="submit"
            disabled={!canWrite || accounts.length === 0}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <UserPlus className="h-3.5 w-3.5" />
            Add Contact
          </button>
        </form>

        <form
          onSubmit={handleCsvImport}
          className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="flex items-center gap-2">
            <Upload className="h-4 w-4 text-indigo-600" />
            <h2 className="text-sm font-semibold text-slate-900">Bulk CSV Contact Import</h2>
          </div>
          <textarea
            rows={4}
            value={csvText}
            onChange={(e) => setCsvText(e.target.value)}
            className="w-full rounded-lg border border-slate-200 p-2.5 font-mono text-[11px]"
          />
          <button
            type="submit"
            disabled={!canWrite}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
          >
            <Upload className="h-3.5 w-3.5" />
            Import CSV
          </button>
        </form>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-900">Contacts ({contacts.length})</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-2 pr-3">Name</th>
                <th className="py-2 pr-3">Email</th>
                <th className="py-2 pr-3">Title</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2">Compliance Note</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {contacts.map((c) => (
                <tr key={c.id}>
                  <td className="py-2 pr-3 font-medium text-slate-900">
                    {c.first_name} {c.last_name}
                  </td>
                  <td className="py-2 pr-3 text-slate-700">{c.email}</td>
                  <td className="py-2 pr-3 text-slate-600">{c.title || c.seniority}</td>
                  <td className="py-2 pr-3">
                    <StatusBadge value={c.is_suppressed ? 'suppressed' : c.status} />
                  </td>
                  <td className="py-2 text-slate-500">{c.suppression_reason || 'Cleared'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <Ban className="h-4 w-4 text-rose-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Suppression &amp; Opt-Out Compliance List ({suppressions.length})
          </h2>
        </div>
        <form onSubmit={handleAddSuppression} className="mt-3 flex flex-wrap gap-2">
          <select
            value={supScope}
            onChange={(e) => setSupScope(e.target.value as 'email' | 'domain')}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            <option value="email">email</option>
            <option value="domain">domain</option>
          </select>
          <input
            required
            placeholder="Email or domain to suppress"
            value={supValue}
            onChange={(e) => setSupValue(e.target.value)}
            className="min-w-[200px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <input
            required
            placeholder="Reason (e.g. Unsubscribed, competitor)"
            value={supReason}
            onChange={(e) => setSupReason(e.target.value)}
            className="min-w-[200px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite}
            className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
          >
            Enforce Suppression
          </button>
        </form>

        <ul className="mt-4 divide-y divide-slate-100">
          {suppressions.map((entry) => (
            <li
              key={entry.id}
              className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-xs"
            >
              <div>
                <span className="font-semibold text-slate-900">
                  [{entry.scope}] {entry.value}
                </span>
                <span className="ml-2 text-slate-500">
                  — {entry.reason} ({entry.source})
                </span>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge value={entry.active ? 'suppressed' : 'dismissed'} />
                {entry.active && isManager && (
                  <button
                    type="button"
                    onClick={() => handleDeactivateSuppression(entry.id)}
                    className="rounded border border-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Deactivate
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <BookOpen className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Semantic Evidence Knowledge Base ({knowledgeDocs.length} indexed)
          </h2>
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <form onSubmit={handleAddKnowledge} className="space-y-2">
            <div className="flex gap-2">
              <select
                value={docType}
                onChange={(e) => setDocType(e.target.value as 'case_study' | 'playbook' | 'note')}
                className="rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs"
              >
                <option value="case_study">case_study</option>
                <option value="playbook">playbook</option>
                <option value="note">note</option>
              </select>
              <input
                required
                placeholder="Case study or playbook title"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
              />
            </div>
            <textarea
              required
              rows={2}
              placeholder="Verified facts, metrics, or positioning snippet..."
              value={docContent}
              onChange={(e) => setDocContent(e.target.value)}
              className="w-full rounded-lg border border-slate-200 p-2.5 text-xs"
            />
            <button
              type="submit"
              disabled={!canWrite}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              Index Knowledge Snippet
            </button>
          </form>

          <div className="space-y-2">
            <form onSubmit={handleSemanticSearch} className="flex gap-2">
              <input
                required
                placeholder="Semantic query (e.g. Snowflake Series B SQL lift)"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
              />
              <button
                type="submit"
                className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
              >
                <Search className="h-3.5 w-3.5" />
                Search Evidence
              </button>
            </form>
            {searchHits.length > 0 && (
              <ul className="space-y-1.5">
                {searchHits.map((hit) => (
                  <li
                    key={hit.chunk.id}
                    className="rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-slate-900">
                        [{hit.chunk.source_type}] {hit.chunk.title}
                      </span>
                      <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[11px] font-semibold text-indigo-700">
                        {Math.round(hit.score * 100)}% match
                      </span>
                    </div>
                    <p className="mt-1 text-slate-600">{hit.chunk.content}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  Activity,
  Award,
  Database,
  GitMerge,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Mail,
  Radar,
  ShieldCheck,
} from 'lucide-react';
import {
  fetchAccounts,
  fetchApprovals,
  fetchAuditEvents,
  fetchBackgroundJobs,
  fetchContacts,
  fetchCrmSyncJobs,
  fetchDeals,
  fetchDuplicateCandidates,
  fetchHealth,
  fetchInboundReplies,
  fetchKnowledgeDocuments,
  fetchMetrics,
  fetchOverview,
  fetchQualifications,
  fetchSequences,
  fetchSuppressions,
  fetchWebhooks,
  loginUser,
  seedDemoData,
  verifyAuditChain,
} from './api/client';
import { AuditView } from './components/AuditView';
import { CrmHygieneView } from './components/CrmHygieneView';
import { OverviewView } from './components/OverviewView';
import { ProspectingView } from './components/ProspectingView';
import { QualificationView } from './components/QualificationView';
import { SequencesView } from './components/SequencesView';
import type {
  AccountItem,
  ActorContext,
  ActorRole,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  BackgroundJobItem,
  ContactItem,
  CrmDealItem,
  CrmSyncJobItem,
  CrmWebhookEventItem,
  DuplicateCandidateItem,
  HealthStatus,
  InboundReplyItem,
  KnowledgeChunkItem,
  OverviewSummary,
  QualificationItem,
  SequenceItem,
  SuppressionEntryItem,
} from './types/sdr';

const NAV_TABS = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'prospecting', label: 'Prospecting', icon: Radar },
  { id: 'qualification', label: 'Qualification', icon: Award },
  { id: 'sequences', label: 'Sequences & Approvals', icon: Mail },
  { id: 'crm', label: 'CRM Hygiene', icon: GitMerge },
  { id: 'audit', label: 'Audit & Guardrails', icon: ShieldCheck },
] as const;

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [actor, setActor] = useState<ActorContext>({
    email: 'manager@acme-sdr.local',
    role: 'sales_manager',
  });
  const [banner, setBanner] = useState<{ text: string; isError: boolean } | null>(null);
  const [busy, setBusy] = useState(false);

  const [showLogin, setShowLogin] = useState(false);
  const [loginEmail, setLoginEmail] = useState('manager@acme-sdr.local');
  const [loginPassword, setLoginPassword] = useState('DemoPassword123!');

  const [overview, setOverview] = useState<OverviewSummary | null>(null);
  const [accounts, setAccounts] = useState<AccountItem[]>([]);
  const [contacts, setContacts] = useState<ContactItem[]>([]);
  const [suppressions, setSuppressions] = useState<SuppressionEntryItem[]>([]);
  const [knowledgeDocs, setKnowledgeDocs] = useState<KnowledgeChunkItem[]>([]);
  const [qualifications, setQualifications] = useState<QualificationItem[]>([]);
  const [sequences, setSequences] = useState<SequenceItem[]>([]);
  const [replies, setReplies] = useState<InboundReplyItem[]>([]);
  const [deals, setDeals] = useState<CrmDealItem[]>([]);
  const [duplicates, setDuplicates] = useState<DuplicateCandidateItem[]>([]);
  const [webhooks, setWebhooks] = useState<CrmWebhookEventItem[]>([]);
  const [syncJobs, setSyncJobs] = useState<CrmSyncJobItem[]>([]);
  const [backgroundJobs, setBackgroundJobs] = useState<BackgroundJobItem[]>([]);
  const [metrics, setMetrics] = useState<Record<string, number> | null>(null);
  const [approvals, setApprovals] = useState<ApprovalRequestItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEventItem[]>([]);
  const [chainStatus, setChainStatus] = useState<AuditChainVerify | null>(null);

  const notify = useCallback((text: string, isError = false) => {
    setBanner({ text, isError });
  }, []);

  const refreshWorkspace = useCallback(async () => {
    try {
      const [
        ov,
        accs,
        conts,
        sups,
        docs,
        quals,
        seqs,
        inReplies,
        crmDeals,
        dups,
        hooks,
        sJobs,
        bJobs,
        met,
        apps,
        evs,
        chain,
      ] = await Promise.all([
        fetchOverview(actor),
        fetchAccounts(actor),
        fetchContacts(actor),
        fetchSuppressions(actor),
        fetchKnowledgeDocuments(actor),
        fetchQualifications(actor),
        fetchSequences(actor),
        fetchInboundReplies(actor),
        fetchDeals(actor),
        fetchDuplicateCandidates(actor),
        fetchWebhooks(actor),
        fetchCrmSyncJobs(actor),
        fetchBackgroundJobs(actor),
        fetchMetrics(actor),
        fetchApprovals(actor),
        fetchAuditEvents(actor),
        verifyAuditChain(actor),
      ]);
      setOverview(ov);
      setAccounts(accs);
      setContacts(conts);
      setSuppressions(sups);
      setKnowledgeDocs(docs);
      setQualifications(quals);
      setSequences(seqs);
      setReplies(inReplies);
      setDeals(crmDeals);
      setDuplicates(dups);
      setWebhooks(hooks);
      setSyncJobs(sJobs);
      setBackgroundJobs(bJobs);
      setMetrics(met);
      setApprovals(apps);
      setAuditEvents(evs);
      setChainStatus(chain);
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Failed to refresh workspace data', true);
    }
  }, [actor, notify]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const h = await fetchHealth();
        if (!cancelled) {
          setHealth(h);
          setOffline(false);
        }
        await refreshWorkspace();
      } catch {
        if (!cancelled) {
          setOffline(true);
        }
      }
    }
    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [refreshWorkspace]);

  async function handleLoadDemo(reset = false) {
    setBusy(true);
    try {
      const res = await seedDemoData(actor, reset);
      notify(res.message);
      await refreshWorkspace();
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Demo seed failed', true);
    } finally {
      setBusy(false);
    }
  }

  function handleRoleChange(role: ActorRole) {
    const emailMap: Record<ActorRole, string> = {
      sales_manager: 'manager@acme-sdr.local',
      sdr: 'sdr@acme-sdr.local',
      viewer: 'viewer@acme-sdr.local',
    };
    const email = emailMap[role];
    setActor({ email, role });
    notify(`Switched active actor to ${email} (${role}).`);
  }

  async function handleLoginSubmit(e: FormEvent) {
    e.preventDefault();
    try {
      const res = await loginUser(loginEmail, loginPassword);
      setActor({
        email: res.actor.email,
        role: res.actor.role,
        token: res.access_token,
      });
      setShowLogin(false);
      notify(`Signed in with JWT as ${res.actor.email} (${res.actor.role}).`);
    } catch (err) {
      notify(err instanceof Error ? err.message : 'Sign-in failed', true);
    }
  }

  function handleLogout() {
    setActor({
      email: 'manager@acme-sdr.local',
      role: 'sales_manager',
    });
    notify('Signed out of JWT session; reverted to local dev actor.');
  }

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
              Phase 1–2 — Autonomous AI SDR Operations
            </p>
            <h1 className="mt-0.5 text-xl font-bold tracking-tight text-slate-900">AI SDR</h1>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            {actor.token ? (
              <div className="flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
                <KeyRound className="h-3.5 w-3.5" />
                <span>JWT: {actor.email}</span>
                <button
                  type="button"
                  onClick={handleLogout}
                  aria-label="Sign Out"
                  className="ml-1 text-emerald-700 hover:text-emerald-950"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              </div>
            ) : (
              <>
                <label className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                  <span>Role:</span>
                  <select
                    aria-label="Actor Role"
                    value={actor.role}
                    onChange={(e) => handleRoleChange(e.target.value as ActorRole)}
                    className="bg-transparent font-semibold text-indigo-700 focus:outline-none"
                  >
                    <option value="sales_manager">Sales Manager</option>
                    <option value="sdr">SDR</option>
                    <option value="viewer">Viewer</option>
                  </select>
                </label>

                <button
                  type="button"
                  disabled={offline}
                  onClick={() => setShowLogin(true)}
                  className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:opacity-50"
                >
                  <KeyRound className="h-3.5 w-3.5" />
                  Sign In
                </button>
              </>
            )}

            <button
              type="button"
              onClick={() => handleLoadDemo(true)}
              disabled={busy || offline || actor.role !== 'sales_manager'}
              className="inline-flex items-center gap-1.5 rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              <Database className="h-3.5 w-3.5" />
              {busy ? 'Loading...' : 'Reset Demo Data'}
            </button>

            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1.5 text-xs font-medium">
              <Activity
                className={`h-3.5 w-3.5 ${
                  health?.status === 'ok'
                    ? 'text-emerald-600'
                    : offline
                    ? 'text-amber-600'
                    : 'text-slate-400'
                }`}
              />
              <span>
                {health?.status === 'ok'
                  ? `API Healthy (${health.llm_provider})`
                  : offline
                  ? 'Offline Starter Preview'
                  : 'Checking API...'}
              </span>
            </div>
          </div>
        </div>

        <nav
          aria-label="AI SDR Modules"
          className="mx-auto flex max-w-6xl gap-1 overflow-x-auto px-6 pb-2"
        >
          {NAV_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${
                  active
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                {tab.label}
              </button>
            );
          })}
        </nav>
      </header>

      {showLogin && (
        <div
          role="dialog"
          aria-label="Sign In with JWT"
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
        >
          <form
            onSubmit={handleLoginSubmit}
            className="w-full max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-lg"
          >
            <h2 className="text-sm font-semibold text-slate-900">Sign In with JWT</h2>
            <p className="text-xs text-slate-500">
              Demo credentials: <code>manager@acme-sdr.local</code> /{' '}
              <code>DemoPassword123!</code>
            </p>
            <input
              required
              type="email"
              aria-label="Login Email"
              value={loginEmail}
              onChange={(e) => setLoginEmail(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <input
              required
              type="password"
              aria-label="Login Password"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowLogin(false)}
                className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white"
              >
                Sign In Now
              </button>
            </div>
          </form>
        </div>
      )}

      <main className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {banner && (
          <div
            role="status"
            className={`flex items-center justify-between rounded-xl border px-4 py-2.5 text-xs font-medium ${
              banner.isError
                ? 'border-rose-200 bg-rose-50 text-rose-800'
                : 'border-emerald-200 bg-emerald-50 text-emerald-800'
            }`}
          >
            <span>{banner.text}</span>
            <button
              type="button"
              onClick={() => setBanner(null)}
              className="ml-4 text-xs underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewView
            overview={overview}
            approvals={approvals}
            onNavigate={setActiveTab}
            onLoadDemo={() => handleLoadDemo(false)}
            busy={busy}
            offline={offline}
          />
        )}

        {activeTab === 'prospecting' && (
          <ProspectingView
            actor={actor}
            accounts={accounts}
            contacts={contacts}
            suppressions={suppressions}
            knowledgeDocs={knowledgeDocs}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'qualification' && (
          <QualificationView
            actor={actor}
            accounts={accounts}
            contacts={contacts}
            qualifications={qualifications}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'sequences' && (
          <SequencesView
            actor={actor}
            accounts={accounts}
            contacts={contacts}
            sequences={sequences}
            replies={replies}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'crm' && (
          <CrmHygieneView
            actor={actor}
            accounts={accounts}
            deals={deals}
            duplicates={duplicates}
            webhooks={webhooks}
            qualifications={qualifications}
            syncJobs={syncJobs}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}

        {activeTab === 'audit' && (
          <AuditView
            actor={actor}
            approvals={approvals}
            events={auditEvents}
            backgroundJobs={backgroundJobs}
            metrics={metrics}
            chainStatus={chainStatus}
            onChainVerified={setChainStatus}
            onRefresh={refreshWorkspace}
            onNotify={notify}
          />
        )}
      </main>
    </div>
  );
}

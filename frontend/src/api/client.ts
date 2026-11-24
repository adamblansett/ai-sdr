import type {
  AccountItem,
  ActorContext,
  ApprovalRequestItem,
  AuditChainVerify,
  AuditEventItem,
  ContactItem,
  CrmDealItem,
  CrmWebhookEventItem,
  CsvImportResult,
  DuplicateCandidateItem,
  HealthStatus,
  OverviewSummary,
  PiiRedactionResult,
  QualificationItem,
  SequenceItem,
  SequenceTouchItem,
  SignalItem,
  SuppressionEntryItem,
} from '../types/sdr';

async function requestJson<T>(
  path: string,
  actor?: ActorContext,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (actor) {
    headers.set('X-Actor-Email', actor.email);
    headers.set('X-Actor-Role', actor.role);
  }
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const errBody = (await response.json()) as { detail?: unknown };
      if (typeof errBody.detail === 'string') {
        detail = errBody.detail;
      } else if (errBody.detail !== undefined) {
        detail = JSON.stringify(errBody.detail);
      }
    } catch {
      // Keep HTTP status detail fallback
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export function fetchHealth(): Promise<HealthStatus> {
  return requestJson<HealthStatus>('/api/v1/health');
}

export function fetchOverview(actor: ActorContext): Promise<OverviewSummary> {
  return requestJson<OverviewSummary>('/api/v1/overview', actor);
}

export function seedDemoData(
  actor: ActorContext,
  reset = false,
): Promise<{ seeded: boolean; message: string }> {
  return requestJson<{ seeded: boolean; message: string }>(
    `/api/v1/seed/demo?reset=${reset ? 'true' : 'false'}`,
    actor,
    { method: 'POST' },
  );
}

export function fetchAccounts(actor: ActorContext): Promise<AccountItem[]> {
  return requestJson<AccountItem[]>('/api/v1/prospecting/accounts', actor);
}

export function createAccount(
  actor: ActorContext,
  payload: {
    name: string;
    domain: string;
    industry: string;
    employee_count: number;
    tech_stack: string[];
  },
): Promise<AccountItem> {
  return requestJson<AccountItem>('/api/v1/prospecting/accounts', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchAccountSignals(
  actor: ActorContext,
  accountId: string,
): Promise<SignalItem[]> {
  return requestJson<SignalItem[]>(
    `/api/v1/prospecting/accounts/${accountId}/signals`,
    actor,
  );
}

export function addAccountSignal(
  actor: ActorContext,
  accountId: string,
  payload: {
    signal_type: string;
    title: string;
    summary: string;
    source_url: string;
    weight: number;
  },
): Promise<SignalItem> {
  return requestJson<SignalItem>(
    `/api/v1/prospecting/accounts/${accountId}/signals`,
    actor,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}

export function researchAccount(
  actor: ActorContext,
  accountId: string,
): Promise<{ account: AccountItem; llm_provider: string }> {
  return requestJson<{ account: AccountItem; llm_provider: string }>(
    `/api/v1/prospecting/accounts/${accountId}/research`,
    actor,
    { method: 'POST' },
  );
}

export function fetchContacts(actor: ActorContext): Promise<ContactItem[]> {
  return requestJson<ContactItem[]>('/api/v1/prospecting/contacts', actor);
}

export function createContact(
  actor: ActorContext,
  payload: {
    account_id: string;
    first_name: string;
    last_name: string;
    email: string;
    title: string;
    phone?: string;
  },
): Promise<ContactItem> {
  return requestJson<ContactItem>('/api/v1/prospecting/contacts', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function importContactsCsv(
  actor: ActorContext,
  csvText: string,
): Promise<CsvImportResult> {
  return requestJson<CsvImportResult>('/api/v1/prospecting/contacts/import-csv', actor, {
    method: 'POST',
    body: JSON.stringify({ csv_text: csvText }),
  });
}

export function fetchSuppressions(actor: ActorContext): Promise<SuppressionEntryItem[]> {
  return requestJson<SuppressionEntryItem[]>('/api/v1/prospecting/suppressions', actor);
}

export function addSuppression(
  actor: ActorContext,
  payload: { scope: 'email' | 'domain'; value: string; reason: string },
): Promise<{ entry: SuppressionEntryItem; contacts_affected: number; touches_blocked: number }> {
  return requestJson<{
    entry: SuppressionEntryItem;
    contacts_affected: number;
    touches_blocked: number;
  }>('/api/v1/prospecting/suppressions', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function deactivateSuppression(
  actor: ActorContext,
  entryId: string,
): Promise<SuppressionEntryItem> {
  return requestJson<SuppressionEntryItem>(
    `/api/v1/prospecting/suppressions/${entryId}`,
    actor,
    { method: 'DELETE' },
  );
}

export function fetchQualifications(actor: ActorContext): Promise<QualificationItem[]> {
  return requestJson<QualificationItem[]>('/api/v1/qualification/records', actor);
}

export function evaluateLead(
  actor: ActorContext,
  payload: { account_id: string; contact_id?: string | null; discovery_notes: string },
): Promise<QualificationItem> {
  return requestJson<QualificationItem>('/api/v1/qualification/evaluate', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchSequences(actor: ActorContext): Promise<SequenceItem[]> {
  return requestJson<SequenceItem[]>('/api/v1/sequences', actor);
}

export function generateSequence(
  actor: ActorContext,
  payload: {
    account_id: string;
    contact_id: string;
    channel: 'email' | 'linkedin' | 'multi_channel';
    goal: string;
    num_steps: number;
  },
): Promise<SequenceItem> {
  return requestJson<SequenceItem>('/api/v1/sequences/generate', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateSequenceTouch(
  actor: ActorContext,
  touchId: string,
  payload: { subject?: string; body?: string },
): Promise<SequenceTouchItem> {
  return requestJson<SequenceTouchItem>(`/api/v1/sequences/touches/${touchId}`, actor, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function sendSequenceTouch(
  actor: ActorContext,
  touchId: string,
): Promise<SequenceTouchItem> {
  return requestJson<SequenceTouchItem>(`/api/v1/sequences/touches/${touchId}/send`, actor, {
    method: 'POST',
  });
}

export function fetchDeals(actor: ActorContext): Promise<CrmDealItem[]> {
  return requestJson<CrmDealItem[]>('/api/v1/crm/deals', actor);
}

export function createDeal(
  actor: ActorContext,
  payload: {
    account_id: string;
    primary_contact_id?: string | null;
    name: string;
    stage: string;
    amount_usd: number;
    close_date?: string | null;
    next_step: string;
  },
): Promise<CrmDealItem> {
  return requestJson<CrmDealItem>('/api/v1/crm/deals', actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function validateDealHygieneAll(
  actor: ActorContext,
): Promise<{ deals_checked: number; deals_flagged: number; avg_hygiene_score: number }> {
  return requestJson<{ deals_checked: number; deals_flagged: number; avg_hygiene_score: number }>(
    '/api/v1/crm/hygiene/validate',
    actor,
    { method: 'POST' },
  );
}

export function synthesizeDealNextStep(
  actor: ActorContext,
  dealId: string,
): Promise<CrmDealItem> {
  return requestJson<CrmDealItem>(`/api/v1/crm/deals/${dealId}/next-step`, actor, {
    method: 'POST',
  });
}

export function fetchDuplicateCandidates(
  actor: ActorContext,
): Promise<DuplicateCandidateItem[]> {
  return requestJson<DuplicateCandidateItem[]>('/api/v1/crm/hygiene/duplicates', actor);
}

export function scanDuplicates(
  actor: ActorContext,
): Promise<{ candidates_created: number; candidates: DuplicateCandidateItem[] }> {
  return requestJson<{ candidates_created: number; candidates: DuplicateCandidateItem[] }>(
    '/api/v1/crm/hygiene/deduplicate',
    actor,
    { method: 'POST' },
  );
}

export function fetchWebhooks(actor: ActorContext): Promise<CrmWebhookEventItem[]> {
  return requestJson<CrmWebhookEventItem[]>('/api/v1/crm/webhooks', actor);
}

export function simulateWebhook(
  actor: ActorContext,
  source: string,
  payload: { event_id: string; event_type: string; data: Record<string, unknown> },
): Promise<CrmWebhookEventItem> {
  return requestJson<CrmWebhookEventItem>(`/api/v1/crm/webhooks/${source}`, actor, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchApprovals(actor: ActorContext): Promise<ApprovalRequestItem[]> {
  return requestJson<ApprovalRequestItem[]>('/api/v1/audit/approvals', actor);
}

export function decideApproval(
  actor: ActorContext,
  approvalId: string,
  decision: 'approved' | 'rejected',
  notes = '',
): Promise<ApprovalRequestItem> {
  return requestJson<ApprovalRequestItem>(`/api/v1/audit/approvals/${approvalId}/decide`, actor, {
    method: 'POST',
    body: JSON.stringify({ decision, notes }),
  });
}

export function fetchAuditEvents(actor: ActorContext): Promise<AuditEventItem[]> {
  return requestJson<AuditEventItem[]>('/api/v1/audit/events', actor);
}

export function verifyAuditChain(actor: ActorContext): Promise<AuditChainVerify> {
  return requestJson<AuditChainVerify>('/api/v1/audit/verify', actor);
}

export function previewPiiRedaction(
  actor: ActorContext,
  text: string,
): Promise<PiiRedactionResult> {
  return requestJson<PiiRedactionResult>('/api/v1/audit/pii-preview', actor, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

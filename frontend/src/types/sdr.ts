export type ActorRole = 'sales_manager' | 'sdr' | 'viewer';

export interface ActorContext {
  email: string;
  role: ActorRole;
  token?: string;
}

export interface HealthStatus {
  status: string;
  service: string;
  app_name: string;
  version: string;
  environment: string;
  llm_provider: string;
  database?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  actor: {
    email: string;
    role: ActorRole;
    auth_method: string;
  };
}

export interface OverviewSummary {
  accounts_total: number;
  suppressed_accounts: number;
  signals_total: number;
  contacts_active: number;
  contacts_suppressed: number;
  active_suppressions: number;
  qualifications_total: number;
  high_intent_leads: number;
  avg_icp_score: number;
  sequences_total: number;
  touches_pending_approval: number;
  touches_approved: number;
  touches_sent: number;
  touches_blocked: number;
  deals_open: number;
  avg_hygiene_score: number;
  hygiene_issues_open: number;
  pending_merges: number;
  pending_approvals: number;
  audit_events_total: number;
}

export interface AccountItem {
  id: string;
  name: string;
  domain: string;
  industry: string;
  employee_count: number;
  annual_revenue_usd: number;
  headquarters: string;
  tech_stack: string[];
  icp_fit_score: number;
  signal_score: number;
  research_summary: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface SignalItem {
  id: string;
  account_id: string;
  signal_type: string;
  title: string;
  summary: string;
  evidence_excerpt: string;
  source_url: string;
  confidence: number;
  weight: number;
  observed_at: string;
  verified: boolean;
  created_at: string;
}

export interface ContactItem {
  id: string;
  account_id: string;
  first_name: string;
  last_name: string;
  email: string;
  title: string;
  seniority: string;
  department: string;
  phone: string;
  linkedin_url: string;
  do_not_contact: boolean;
  opt_out_reason: string | null;
  status: string;
  merged_into_id: string | null;
  crm_external_id: string | null;
  is_suppressed: boolean;
  suppression_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SuppressionEntryItem {
  id: string;
  scope: 'email' | 'domain';
  value: string;
  reason: string;
  source: string;
  active: boolean;
  created_by: string;
  created_at: string;
}

export interface CsvImportResult {
  accounts_created: number;
  contacts_created: number;
  contacts_skipped: number;
  suppressed_flagged: number;
  errors: string[];
}

export interface KnowledgeChunkItem {
  id: string;
  account_id: string | null;
  source_type: string;
  source_ref_id: string | null;
  title: string;
  content: string;
  source_url: string;
  embedding_dim: number;
  created_by: string;
  created_at: string;
}

export interface KnowledgeSearchHit {
  chunk: KnowledgeChunkItem;
  score: number;
}

export interface RubricDimension {
  dimension: string;
  weight: number;
  score: number;
  max_score: number;
  reason: string;
}

export interface EvidenceCitation {
  signal_id: string;
  signal_type: string;
  title: string;
  source_url: string;
  excerpt: string;
  confidence: number;
}

export interface QualificationItem {
  id: string;
  account_id: string;
  contact_id: string | null;
  icp_score: number;
  intent_tier: string;
  grade: string;
  bant: Record<string, string>;
  meddic: Record<string, string>;
  rubric_breakdown: RubricDimension[];
  evidence_citations: EvidenceCitation[];
  rationale: string;
  llm_provider: string;
  llm_model: string;
  pii_redacted: boolean;
  created_by: string;
  created_at: string;
}

export interface SequenceTouchItem {
  id: string;
  sequence_id: string;
  step_number: number;
  delay_days: number;
  channel: string;
  subject: string;
  body: string;
  unsubscribe_footer_included: boolean;
  cited_signal_ids: string[];
  grounded_facts: string[];
  status: string;
  approval_id: string | null;
  llm_provider: string;
  llm_model: string;
  pii_redacted: boolean;
  approved_by: string | null;
  approved_at: string | null;
  scheduled_for?: string | null;
  sent_at: string | null;
  delivery_provider?: string | null;
  provider_message_id: string | null;
  created_at: string;
}

export interface SequenceItem {
  id: string;
  name: string;
  account_id: string;
  contact_id: string;
  channel: string;
  goal: string;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  touches: SequenceTouchItem[];
}

export interface InboundReplyItem {
  id: string;
  sequence_id: string | null;
  touch_id: string | null;
  contact_id: string | null;
  sender_email: string;
  subject: string;
  body: string;
  classification: string;
  confidence: number;
  auto_action_taken: string;
  received_at: string;
}

export interface HygieneIssue {
  code: string;
  severity: string;
  message: string;
}

export interface CrmDealItem {
  id: string;
  external_id: string | null;
  account_id: string;
  primary_contact_id: string | null;
  name: string;
  stage: string;
  amount_usd: number;
  close_date: string | null;
  owner_email: string;
  next_step: string;
  last_activity_at: string;
  hygiene_score: number;
  hygiene_issues: HygieneIssue[];
  created_at: string;
  updated_at: string;
}

export interface DuplicateCandidateItem {
  id: string;
  primary_contact_id: string;
  duplicate_contact_id: string;
  primary_email: string;
  duplicate_email: string;
  primary_name: string;
  duplicate_name: string;
  match_reason: string;
  confidence: number;
  status: string;
  approval_id: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CrmWebhookEventItem {
  id: string;
  idempotency_key: string;
  source: string;
  event_type: string;
  payload_hash: string;
  status: string;
  result_summary: string;
  duplicate_ignored: boolean;
  received_at: string;
  processed_at: string;
}

export interface CrmSyncJobItem {
  id: string;
  provider: string;
  operation: string;
  entity_type: string;
  entity_id: string;
  idempotency_key: string;
  status: string;
  external_record_id: string | null;
  response_summary: string;
  attempts: number;
  created_by: string;
  created_at: string;
  completed_at: string | null;
}

export interface BackgroundJobItem {
  id: string;
  job_type: string;
  execution_mode: string;
  status: string;
  celery_task_id: string | null;
  result_json: Record<string, unknown>;
  error_message: string | null;
  requested_by: string;
  created_at: string;
  completed_at: string | null;
}

export interface ApprovalRequestItem {
  id: string;
  entity_type: string;
  entity_id: string;
  action_requested: string;
  summary: string;
  risk_level: string;
  status: string;
  requested_by: string;
  decided_by: string | null;
  decision_notes: string | null;
  created_at: string;
  decided_at: string | null;
}

export interface AuditEventItem {
  id: string;
  sequence_no: number;
  event_type: string;
  actor_email: string;
  actor_role: string;
  entity_type: string;
  entity_id: string;
  action: string;
  details_json: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditChainVerify {
  valid: boolean;
  total_events: number;
  head_hash: string;
  broken_sequence_no: number | null;
  message: string;
}

export interface PiiRedactionResult {
  redacted_text: string;
  findings: Array<{ category: string; count: number; placeholder: string }>;
  total_redactions: number;
}

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';

function jsonResponse(data: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    json: async () => data,
  });
}

function buildApiMock() {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.endsWith('/api/v1/health')) {
      return jsonResponse({
        status: 'ok',
        service: 'ai-sdr',
        app_name: 'AI SDR',
        version: '0.1.0',
        environment: 'test',
        llm_provider: 'mock',
        database: 'ok',
      });
    }
    if (url.endsWith('/api/v1/overview')) {
      return jsonResponse({
        accounts_total: 4,
        suppressed_accounts: 1,
        signals_total: 7,
        contacts_active: 3,
        contacts_suppressed: 2,
        active_suppressions: 2,
        qualifications_total: 2,
        high_intent_leads: 2,
        avg_icp_score: 84.5,
        sequences_total: 1,
        touches_pending_approval: 3,
        touches_approved: 0,
        touches_sent: 0,
        touches_blocked: 0,
        deals_open: 3,
        avg_hygiene_score: 76.0,
        hygiene_issues_open: 4,
        pending_merges: 1,
        pending_approvals: 4,
        audit_events_total: 9,
      });
    }
    if (url.endsWith('/api/v1/prospecting/accounts')) {
      return jsonResponse([
        {
          id: 'acc-1',
          name: 'Helios Cloud Systems',
          domain: 'helioscloud.io',
          industry: 'Cloud Infrastructure',
          employee_count: 340,
          annual_revenue_usd: 48000000,
          headquarters: 'Austin, TX',
          tech_stack: ['Salesforce', 'Snowflake'],
          icp_fit_score: 88,
          signal_score: 72,
          research_summary: 'Series B cloud leader.',
          status: 'active',
          created_at: '2026-11-24T00:00:00Z',
          updated_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/prospecting/contacts')) {
      return jsonResponse([
        {
          id: 'cnt-1',
          account_id: 'acc-1',
          first_name: 'Elena',
          last_name: 'Rostova',
          email: 'elena.rostova@helioscloud.io',
          title: 'VP of Revenue Operations',
          seniority: 'vp',
          department: 'RevOps',
          phone: '+1-512-555-0142',
          linkedin_url: '',
          do_not_contact: false,
          opt_out_reason: null,
          status: 'active',
          merged_into_id: null,
          crm_external_id: 'sf-9001',
          is_suppressed: false,
          suppression_reason: null,
          created_at: '2026-11-24T00:00:00Z',
          updated_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/prospecting/suppressions')) {
      return jsonResponse([
        {
          id: 'sup-1',
          scope: 'domain',
          value: 'apexrival.io',
          reason: 'Direct competitor exclusion policy',
          source: 'compliance_blocklist',
          active: true,
          created_by: 'manager@acme-sdr.local',
          created_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/qualification/records')) {
      return jsonResponse([
        {
          id: 'qual-1',
          account_id: 'acc-1',
          contact_id: 'cnt-1',
          icp_score: 88,
          intent_tier: 'high',
          grade: 'A',
          bant: { budget: 'Series B allocated', authority: 'VP RevOps', need: 'Outbound automation', timeline: 'Q2' },
          meddic: { metrics: '35% SQL lift', economic_buyer: 'Elena Rostova', decision_criteria: 'PII redaction', decision_process: 'Pilot', identify_pain: 'Manual research', champion: 'Elena Rostova' },
          rubric_breakdown: [],
          evidence_citations: [
            {
              signal_id: 'sig-1',
              signal_type: 'funding',
              title: 'Closed $42M Series B',
              source_url: 'https://news.helioscloud.io/series-b',
              excerpt: 'Doubling outbound team.',
              confidence: 0.95,
            },
          ],
          rationale: 'High-intent Series B expansion.',
          llm_provider: 'mock',
          llm_model: 'deterministic-sdr-v1',
          pii_redacted: false,
          created_by: 'manager@acme-sdr.local',
          created_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/sequences')) {
      return jsonResponse([
        {
          id: 'seq-1',
          name: 'Helios Q2 Sequence',
          account_id: 'acc-1',
          contact_id: 'cnt-1',
          channel: 'email',
          goal: 'Schedule 15-min review',
          status: 'pending_approval',
          created_by: 'manager@acme-sdr.local',
          created_at: '2026-11-24T00:00:00Z',
          updated_at: '2026-11-24T00:00:00Z',
          touches: [
            {
              id: 'touch-1',
              sequence_id: 'seq-1',
              step_number: 1,
              delay_days: 0,
              channel: 'email',
              subject: 'Quick question on Helios Cloud Systems',
              body: "Hi Elena,\n\nReply 'UNSUBSCRIBE' to opt out.",
              unsubscribe_footer_included: true,
              cited_signal_ids: ['sig-1'],
              grounded_facts: ['FUNDING: Closed $42M Series B'],
              status: 'pending_approval',
              approval_id: 'app-1',
              llm_provider: 'mock',
              llm_model: 'deterministic-sdr-v1',
              pii_redacted: false,
              approved_by: null,
              approved_at: null,
              sent_at: null,
              provider_message_id: null,
              created_at: '2026-11-24T00:00:00Z',
            },
          ],
        },
      ]);
    }
    if (url.endsWith('/api/v1/crm/deals')) {
      return jsonResponse([
        {
          id: 'deal-1',
          external_id: 'sf-opp-101',
          account_id: 'acc-1',
          primary_contact_id: 'cnt-1',
          name: 'Helios Cloud Pilot',
          stage: 'proposal',
          amount_usd: 64000,
          close_date: '2026-12-20',
          owner_email: 'manager@acme-sdr.local',
          next_step: 'Deliver security architecture brief.',
          last_activity_at: '2026-11-22T00:00:00Z',
          hygiene_score: 100,
          hygiene_issues: [],
          created_at: '2026-11-24T00:00:00Z',
          updated_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/crm/hygiene/duplicates')) {
      return jsonResponse([]);
    }
    if (url.endsWith('/api/v1/crm/webhooks')) {
      return jsonResponse([]);
    }
    if (url.endsWith('/api/v1/audit/approvals')) {
      return jsonResponse([
        {
          id: 'app-1',
          entity_type: 'sequence_touch',
          entity_id: 'touch-1',
          action_requested: 'send_outbound_touch',
          summary: 'Step 1 (email) to Elena Rostova at Helios Cloud Systems',
          risk_level: 'medium',
          status: 'pending',
          requested_by: 'sdr@acme-sdr.local',
          decided_by: null,
          decision_notes: null,
          created_at: '2026-11-24T00:00:00Z',
          decided_at: null,
        },
      ]);
    }
    if (url.endsWith('/api/v1/audit/approvals/app-1/decide') && init?.method === 'POST') {
      return jsonResponse({
        id: 'app-1',
        entity_type: 'sequence_touch',
        entity_id: 'touch-1',
        action_requested: 'send_outbound_touch',
        summary: 'Step 1 (email) to Elena Rostova at Helios Cloud Systems',
        risk_level: 'medium',
        status: 'approved',
        requested_by: 'sdr@acme-sdr.local',
        decided_by: 'manager@acme-sdr.local',
        decision_notes: 'approved via Audit queue',
        created_at: '2026-11-24T00:00:00Z',
        decided_at: '2026-11-24T00:05:00Z',
      });
    }
    if (url.endsWith('/api/v1/audit/events')) {
      return jsonResponse([
        {
          id: 'ev-1',
          sequence_no: 1,
          event_type: 'seed.demo_loaded',
          actor_email: 'manager@acme-sdr.local',
          actor_role: 'sales_manager',
          entity_type: 'workspace',
          entity_id: 'ai-sdr-demo',
          action: 'seeded',
          details_json: {},
          prev_hash: 'GENESIS',
          event_hash: 'abcdef1234567890abcdef1234567890',
          created_at: '2026-11-24T00:00:00Z',
        },
      ]);
    }
    if (url.endsWith('/api/v1/audit/verify')) {
      return jsonResponse({
        valid: true,
        total_events: 9,
        head_hash: 'abcdef1234567890abcdef1234567890',
        broken_sequence_no: null,
        message: 'All 9 audit events verified intact.',
      });
    }
    if (url.endsWith('/api/v1/audit/pii-preview') && init?.method === 'POST') {
      return jsonResponse({
        redacted_text: 'Reach [REDACTED_EMAIL] safely.',
        findings: [{ category: 'email', count: 1, placeholder: '[REDACTED_EMAIL]' }],
        total_redactions: 1,
      });
    }
    return jsonResponse({});
  });
}

describe('AI SDR Phase 1 workspace', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders live API health, overview KPIs, and navigates all 6 modules', async () => {
    const mockFetch = buildApiMock();
    vi.stubGlobal('fetch', mockFetch);
    const user = userEvent.setup();

    render(<App />);

    expect(screen.getByRole('heading', { name: 'AI SDR' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/API Healthy \(mock\)/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Target Accounts & Signals')).toBeInTheDocument();
    expect(screen.getByText(/Pending Human-in-the-Loop Approvals/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Prospecting/i }));
    expect(screen.getByText('Helios Cloud Systems')).toBeInTheDocument();
    expect(screen.getByText(/Suppression & Opt-Out Compliance List/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Qualification/i }));
    expect(screen.getByText(/BANT Extraction/i)).toBeInTheDocument();
    expect(screen.getByText(/Closed \$42M Series B/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Sequences & Approvals/i }));
    expect(screen.getByText(/Quick question on Helios Cloud Systems/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CRM Hygiene/i }));
    expect(screen.getByText('Helios Cloud Pilot')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Audit & Guardrails/i }));
    expect(screen.getByText(/Immutable SHA-256 Audit Trail/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Test Cloud PII Scrubbing/i }));
    await waitFor(() => {
      expect(screen.getByText(/Reach \[REDACTED_EMAIL\] safely\./i)).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /^Approve$/i }));
    await waitFor(() => {
      expect(screen.getByText(/Approval approved\./i)).toBeInTheDocument();
    });
  });

  it('supports role switching and resilient offline starter preview', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));

    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Offline Starter Preview/i)).toBeInTheDocument();
    });
    expect(screen.getByText('Outbound Prospecting')).toBeInTheDocument();

    const roleSelect = screen.getByLabelText('Actor Role');
    await user.selectOptions(roleSelect, 'sdr');
    expect(screen.getByText(/Switched active actor to sdr@acme-sdr\.local/i)).toBeInTheDocument();
  });
});

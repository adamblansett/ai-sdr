import { useState, type FormEvent } from 'react';
import { Check, Edit3, Mail, Send, ShieldCheck, X } from 'lucide-react';
import {
  decideApproval,
  generateSequence,
  sendSequenceTouch,
  updateSequenceTouch,
} from '../api/client';
import type {
  AccountItem,
  ActorContext,
  ContactItem,
  SequenceItem,
  SequenceTouchItem,
} from '../types/sdr';
import { StatusBadge } from './StatusBadge';

interface SequencesViewProps {
  actor: ActorContext;
  accounts: AccountItem[];
  contacts: ContactItem[];
  sequences: SequenceItem[];
  onRefresh: () => Promise<void>;
  onNotify: (text: string, isError?: boolean) => void;
}

export function SequencesView({
  actor,
  accounts,
  contacts,
  sequences,
  onRefresh,
  onNotify,
}: SequencesViewProps) {
  const [accountId, setAccountId] = useState('');
  const [contactId, setContactId] = useState('');
  const [channel, setChannel] = useState<'email' | 'linkedin' | 'multi_channel'>('email');
  const [goal, setGoal] = useState('Schedule a 15-minute discovery workflow review');
  const [numSteps, setNumSteps] = useState(3);
  const [busy, setBusy] = useState(false);

  const [editingTouchId, setEditingTouchId] = useState<string | null>(null);
  const [editSubject, setEditSubject] = useState('');
  const [editBody, setEditBody] = useState('');

  const selectedAccountId = accountId || accounts[0]?.id || '';
  const eligibleContacts = contacts.filter((c) => c.account_id === selectedAccountId);
  const selectedContactId =
    contactId && eligibleContacts.some((c) => c.id === contactId)
      ? contactId
      : eligibleContacts[0]?.id || '';

  const accountMap = new Map(accounts.map((a) => [a.id, a]));
  const contactMap = new Map(contacts.map((c) => [c.id, c]));
  const canWrite = actor.role !== 'viewer';
  const isManager = actor.role === 'sales_manager';

  async function handleGenerate(e: FormEvent) {
    e.preventDefault();
    if (!selectedAccountId || !selectedContactId) {
      onNotify('Select both an account and contact first.', true);
      return;
    }
    setBusy(true);
    try {
      const seq = await generateSequence(actor, {
        account_id: selectedAccountId,
        contact_id: selectedContactId,
        channel,
        goal,
        num_steps: numSteps,
      });
      onNotify(
        `Generated ${seq.touches.length}-touch sequence queued for human approval.`,
      );
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Sequence generation failed', true);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(touch: SequenceTouchItem) {
    setEditingTouchId(touch.id);
    setEditSubject(touch.subject);
    setEditBody(touch.body);
  }

  async function handleSaveEdit(touchId: string) {
    try {
      await updateSequenceTouch(actor, touchId, {
        subject: editSubject,
        body: editBody,
      });
      setEditingTouchId(null);
      onNotify('Updated touch draft (re-approval required if previously approved).');
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Touch update failed', true);
    }
  }

  async function handleApproval(approvalId: string, decision: 'approved' | 'rejected') {
    try {
      await decideApproval(actor, approvalId, decision, `${decision} in Sequences workspace`);
      onNotify(`Touch ${decision}.`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Approval action failed', true);
    }
  }

  async function handleSend(touchId: string) {
    try {
      const res = await sendSequenceTouch(actor, touchId);
      onNotify(`Sent touch (${res.provider_message_id}).`);
      await onRefresh();
    } catch (err) {
      onNotify(err instanceof Error ? err.message : 'Send failed', true);
    }
  }

  return (
    <div className="space-y-6">
      <form
        onSubmit={handleGenerate}
        className="space-y-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <div className="flex items-center gap-2">
          <Mail className="h-4 w-4 text-indigo-600" />
          <h2 className="text-sm font-semibold text-slate-900">
            Generate Grounded Multi-Touch Sequence
          </h2>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <select
            value={selectedAccountId}
            onChange={(e) => {
              setAccountId(e.target.value);
              setContactId('');
            }}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.status})
              </option>
            ))}
          </select>

          <select
            value={selectedContactId}
            onChange={(e) => setContactId(e.target.value)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            {eligibleContacts.map((c) => (
              <option key={c.id} value={c.id}>
                {c.first_name} {c.last_name} {c.is_suppressed ? '[SUPPRESSED]' : ''}
              </option>
            ))}
          </select>

          <select
            value={channel}
            onChange={(e) =>
              setChannel(e.target.value as 'email' | 'linkedin' | 'multi_channel')
            }
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          >
            <option value="email">email</option>
            <option value="linkedin">linkedin</option>
            <option value="multi_channel">multi_channel</option>
          </select>

          <input
            type="number"
            min={1}
            max={5}
            value={numSteps}
            onChange={(e) => setNumSteps(Number(e.target.value) || 3)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
        </div>

        <div className="flex flex-wrap gap-2">
          <input
            required
            placeholder="Sequence goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            className="min-w-[260px] flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs"
          />
          <button
            type="submit"
            disabled={!canWrite || busy || !selectedContactId}
            className="rounded-lg bg-indigo-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? 'Generating...' : 'Generate Sequence Drafts'}
          </button>
        </div>
      </form>

      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-900">
          Outbound Sequences &amp; Approval Queue ({sequences.length})
        </h2>

        {sequences.map((seq) => {
          const acc = accountMap.get(seq.account_id);
          const contact = contactMap.get(seq.contact_id);
          return (
            <article
              key={seq.id}
              className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">{seq.name}</h3>
                  <p className="text-xs text-slate-500">
                    {acc?.name || seq.account_id} ·{' '}
                    {contact ? `${contact.first_name} ${contact.last_name} (${contact.email})` : seq.contact_id}{' '}
                    · Goal: {seq.goal}
                  </p>
                </div>
                <StatusBadge value={seq.status} />
              </div>

              <div className="space-y-3">
                {seq.touches.map((touch) => {
                  const isEditing = editingTouchId === touch.id;
                  return (
                    <div
                      key={touch.id}
                      className="space-y-2.5 rounded-lg border border-slate-200 bg-slate-50 p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="font-semibold text-slate-900">
                            Step {touch.step_number} (Day +{touch.delay_days} · {touch.channel})
                          </span>
                          <StatusBadge value={touch.status} />
                          {touch.unsubscribe_footer_included && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                              <ShieldCheck className="h-3 w-3" />
                              Unsubscribe Footer
                            </span>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5">
                          {canWrite &&
                            touch.status !== 'sent' &&
                            touch.status !== 'blocked_suppressed' && (
                              <button
                                type="button"
                                onClick={() => startEdit(touch)}
                                className="inline-flex items-center gap-1 rounded border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
                              >
                                <Edit3 className="h-3 w-3" />
                                Edit
                              </button>
                            )}

                          {isManager &&
                            touch.status === 'pending_approval' &&
                            touch.approval_id && (
                              <>
                                <button
                                  type="button"
                                  onClick={() => handleApproval(touch.approval_id!, 'approved')}
                                  className="inline-flex items-center gap-1 rounded bg-emerald-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-700"
                                >
                                  <Check className="h-3 w-3" />
                                  Approve
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleApproval(touch.approval_id!, 'rejected')}
                                  className="inline-flex items-center gap-1 rounded bg-rose-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-rose-700"
                                >
                                  <X className="h-3 w-3" />
                                  Reject
                                </button>
                              </>
                            )}

                          {isManager && touch.status === 'approved' && (
                            <button
                              type="button"
                              onClick={() => handleSend(touch.id)}
                              className="inline-flex items-center gap-1 rounded bg-indigo-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-indigo-700"
                            >
                              <Send className="h-3 w-3" />
                              Send Touch
                            </button>
                          )}
                        </div>
                      </div>

                      {isEditing ? (
                        <div className="space-y-2">
                          <input
                            value={editSubject}
                            onChange={(e) => setEditSubject(e.target.value)}
                            className="w-full rounded border border-slate-300 bg-white px-2.5 py-1 text-xs font-medium"
                          />
                          <textarea
                            rows={5}
                            value={editBody}
                            onChange={(e) => setEditBody(e.target.value)}
                            className="w-full rounded border border-slate-300 bg-white p-2.5 text-xs"
                          />
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => handleSaveEdit(touch.id)}
                              className="rounded bg-indigo-600 px-3 py-1 text-xs font-semibold text-white"
                            >
                              Save Draft
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingTouchId(null)}
                              className="rounded border border-slate-300 bg-white px-3 py-1 text-xs"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <p className="text-xs font-semibold text-slate-900">
                            Subject: {touch.subject}
                          </p>
                          <pre className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-700">
                            {touch.body}
                          </pre>
                        </>
                      )}

                      {touch.grounded_facts.length > 0 && (
                        <p className="text-[11px] text-slate-500">
                          Grounded in: {touch.grounded_facts.join(' · ')}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}

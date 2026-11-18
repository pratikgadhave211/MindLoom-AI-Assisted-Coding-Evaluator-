import React, { useEffect, useState } from 'react';
import { createWorkspaceApi } from '../workspaceApi';

export default function SubmissionReport({ token, attempt, submissionId, onClose }) {
  const [submission, setSubmission] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const previous = document.activeElement;
    const closeOnEscape = event => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => { window.removeEventListener('keydown', closeOnEscape); previous?.focus(); };
  }, [onClose]);
  useEffect(() => {
    let cancelled = false;
    let timer;
    async function refresh() {
      try {
        const result = await createWorkspaceApi(token).submission(attempt, submissionId);
        if (cancelled) return;
        setSubmission(result);
        setError('');
        if (['preparing', 'running', 'testing', 'reviewing'].includes(result.status)) timer = setTimeout(refresh, 2500);
      } catch {
        if (!cancelled) setError('Could not load the report. Close and reopen it to retry.');
      }
    }
    refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [token, attempt, submissionId]);

  const report = submission?.report;
  const status = { preparing: 'Preparing submission…', running: 'Preparing submission…', testing: 'Running challenge checks…',
    reviewing: 'Reviewing your approach…', interrupted: 'Evaluation was interrupted.', failed: 'Evaluation could not complete.' };
  const result = { passed: 'Passed', partially_passed: 'Partially passed', not_passed: 'Not passed',
    could_not_evaluate: 'Could not evaluate' };
  return <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Submission report">
    <section className="bg-ide-sidebar border border-ide-border rounded-lg p-5 w-full max-w-2xl max-h-[90vh] overflow-auto space-y-4">
      <div className="flex justify-between items-center"><h2 className="text-lg font-semibold">Submission report</h2>
        <button autoFocus onClick={onClose} className="border border-ide-border rounded px-2 py-1">Close</button></div>
      {error && <p role="alert">{error}</p>}
      {!report && <p role="status">{status[submission?.status] || 'Loading…'}</p>}
      {report && <>
        <div><h3 className="font-semibold">Solution: {result[report.result] || 'Could not evaluate'}</h3>
          <p className="text-sm text-ide-textMuted">Behavior checks: {report.correctness.passed ?? '—'} / {report.correctness.total ?? '—'} passed</p>
          <p className="text-sm text-ide-textMuted">Visible tests: {report.correctness.visible_tests?.status?.replaceAll('_', ' ') || 'unavailable'} (candidate-controlled)</p>
          <ul className="mt-2 text-sm space-y-1">{(report.correctness.behaviors || []).map(item => <li key={item.name}>{item.status === 'passed' ? '✓' : '✗'} {item.name}</li>)}</ul>
        </div>
        <div><h3 className="font-semibold">AI-assisted process</h3>
          {report.process_review?.status === 'unavailable' && <p className="text-sm">{report.process_review.reason}</p>}
          {report.process_review?.status === 'partial' && <p className="text-sm">Feedback is incomplete: {report.process_review.reason}</p>}
          {report.process_review?.status === 'ready' && !(report.process_review.summary?.observations || []).length &&
            !(report.process_review.summary?.improvements || []).length && <p className="text-sm">No supported process findings were available.</p>}
          <ul className="text-sm space-y-2">{(report.process_review?.summary?.observations || []).map((item, index) =>
            <li key={index}><strong>{item.area || 'Observation'}:</strong> {item.finding} <span className="text-ide-textMuted">({(item.evidence_ids || []).join(', ')})</span></li>)}</ul>
          {(report.process_review?.summary?.improvements || []).length > 0 && <>
            <h4 className="font-semibold mt-3">Suggestions for improvement</h4>
            <ul className="text-sm space-y-2">{report.process_review.summary.improvements.map((item, index) =>
              <li key={index}>{item.suggestion} <span className="text-ide-textMuted">({item.evidence_ids.join(', ')})</span></li>)}</ul>
          </>}
          {(report.process_review?.summary?.unresolved || []).length > 0 && <p className="text-sm text-ide-textMuted">Some questions remain unresolved.</p>}
          {(report.evidence || []).length > 0 && <details className="text-sm mt-2"><summary className="cursor-pointer">Review cited evidence</summary>
            {report.evidence.map(item => <div key={item.id} className="mt-2"><strong>{item.id}</strong><pre className="whitespace-pre-wrap break-words text-ide-textMuted">{item.text}</pre></div>)}
          </details>}
        </div>
        <div><h3 className="font-semibold">Usage</h3>
          <p className="text-sm">Prompts: {report.statistics.prompts} · Model calls: {report.statistics.model_calls} · Failed tool calls: {report.statistics.failed_tool_calls}</p>
          <p className="text-sm">Agent tokens: {report.statistics.tokens.input ?? '—'} input · {report.statistics.tokens.output ?? '—'} output · {report.statistics.tokens.total ?? 'unavailable'} total ({report.statistics.tokens.coverage})</p>
          <p className="text-sm">Judge tokens: {report.process_review?.usage?.total ?? 'unavailable'} · Estimated cost: unavailable</p>
          <ul className="text-sm">{Object.entries(report.statistics.tools || {}).map(([name, count]) => <li key={name}>{name}: {count}</li>)}</ul>
        </div>
        <div><h3 className="font-semibold">Changed files</h3><p className="text-sm break-words">{report.changed_files?.join(', ') || 'No changes available.'}</p></div>
        {report.evidence_incomplete && <p className="text-sm text-ide-textMuted">Some activity or file changes could not be fully tracked.</p>}
        {report.activity_order_incomplete && <p className="text-sm text-ide-textMuted">The timing of editor and terminal activity relative to chat may be incomplete.</p>}
      </>}
    </section>
  </div>;
}

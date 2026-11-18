# Live Predictometer Implementation Plan

**Goal:** Show an experimental live score for whether the current attempt may solve its challenge, using Jev direction, reference-change comparison, and configured rules.

**Architecture:** Reuse the existing FastAPI attempt manager, PostgreSQL, agent event stream and IDE. Evaluate bounded, versioned evidence outside the coding-agent model loop. Keep author guidance, reference code and rule details on the server. This document is the proposed design; provider and model suitability must be checked before implementation choices are locked.

**Stack:** Python, FastAPI, PostgreSQL, existing Docker workspace, React, Jev API and a code comparison model to be selected after a feasibility check.

## Constraints

- No test pass/fail in the predictometer or its rules. Run and Submit and final evaluation are separate work.
- Preserve the existing Jev coding-request sanity check and agent behavior.
- Use simple functions and focused comments. Do not add a separate service, LangGraph node, queue or model server unless a verified need requires one.
- Score and weights are experimental; a weighted score is not a calibrated probability. No fabricated model outputs or false confidence.
- A reference fix is one possible solution. Missing an expected file or pattern is unknown/no match, not proof of an incorrect solution. Agent limits are a workflow obstacle, not evidence of user incompetence.
- Preserve attempt-wide prompt counts across chats, resumes and idempotent retries. Prompt count and maximum are sent to Jev; count only accepted, distinct requests. No new prompt-limit enforcement without a separate decision.
- Do not expose the reference solution, private approach, exact hidden rules or detailed comparisons in browser responses or logs. Never send private material to the coding agent. Verify the selected provider is acceptable before sending private data outside the server.
- An update must correspond to a specific workspace version and event revision; stale results cannot overwrite a newer result. Refresh after accepted prompt, tool result/limit, saved user edit and completed agent edit; debounce rapid saves. Unsaved browser drafts and arbitrary terminal writes are not yet captured reliably and must be shown as coverage gaps.
- Failures or slow evaluation never block prompt submission or agent execution. State may be pending, unavailable, stale or ready.

## Current integration points

- `src/coding_agent/jev.py`: existing `check_with_jev` sends a prompt to SystemOne and reads a 0–1 `coding_request.noul` result. It does not evaluate challenge direction.
- `src/coding_agent/attempts.py`: attempt manager starts turns and shares one workspace across chats. It currently uses a fixed Flask challenge template. Existing request IDs support deduplication.
- `src/coding_agent/agent.py`: publishes tool start/finish events; finished events carry a limited result. Tool arguments and a structured limit event are not currently guaranteed.
- `src/coding_agent/graph.py`: existing model/tool limits are 25 per turn; it currently returns a text error for limit conditions. Treat this as separate from the attempt-wide prompt counter.
- `src/coding_agent/api.py`: authenticated endpoints and SSE, plus editor-save route and terminal websocket.
- `src/coding_agent/memory.py`: current database setup, chats and persisted chat events. Existing chat events alone do not cover reliable file versions, tool args and all workspace changes.
- `cloud-ide-reference/client/src/WorkspaceApp.jsx`, `workspaceApi.js`, `agentStream.js` and `components/AIPanel.jsx`: existing workspace, HTTP calls and turn stream.

## Proposed files

Create:
- `coding-agent/src/coding_agent/predictometer.py`: small orchestration functions; combine available component scores, track state, revision and reasons. No network calls or workspace operations inside the scoring formula.
- `coding-agent/src/coding_agent/predictometer_rules.py`: evaluate safe, challenge-specific path/tool/content rules against structured events and bounded workspace evidence; return matches and unknowns.
- `coding-agent/src/coding_agent/code_compare.py`: isolated adapter for the selected comparison model; bounded context, validated result, timeout and explicit unavailable state. No invented score normalization.
- `coding-agent/challenges/flaskr-login/predictometer.json`: local developer example containing prompt limit, problem description, server-only author approach, relevant paths, allowed bounded patterns and comparison settings. It must never be copied into the workspace or sent to the client. Real private assessment definitions must not be committed publicly.
- `coding-agent/challenges/flaskr-login/reference.patch`: developer example of the intended fix, derived from verified original and correct behavior. It must stay outside the candidate workspace; real hidden material must be privately stored.
- `coding-agent/tests/test_predictometer.py`: scoring, missing/stale data and privacy cases.
- `coding-agent/tests/test_predictometer_rules.py`: file, tool, pattern, limit and unknown cases.
- `coding-agent/tests/test_code_compare.py`: mocked comparison adapter and invalid outputs.
- `cloud-ide-reference/client/src/components/Predictometer.jsx`: accessible live display for experimental score, states and safe generic reasons.
- `cloud-ide-reference/client/src/components/Predictometer.test.jsx`: UI states where the existing test environment supports it; otherwise exercise the existing frontend test tooling without adding a new framework solely for this component.

Modify:
- `coding-agent/src/coding_agent/jev.py`: add `check_direction(problem, approach, prompt, prompt_number, prompt_limit, api_key)` separately from `check_with_jev`. Confirm SystemOne supports the comparison with documentation and a controlled sample; validate and bound returned score, otherwise mark unavailable. An assessment score is a feature, not a probability.
- `coding-agent/src/coding_agent/memory.py`: persist attempt metadata, accepted prompt count, revision, structured events and latest component results. Use dedupe keys and transactions; never silently turn database failure into a normal score.
- `coding-agent/src/coding_agent/attempts.py`: assign fixed challenge definition to attempt, count accepted unique prompts across chats transactionally, collect tool and limit events, schedule a debounced evaluation, persist/recover latest results. Preserve current request idempotency and attempt isolation.
- `coding-agent/src/coding_agent/agent.py` and `graph.py`: expose bounded tool paths/arguments where available and a structured tool-limit event; redact unnecessary contents. Keep graph shape and current per-turn 25-call limits unchanged.
- `coding-agent/src/coding_agent/api.py`: record successful editor saves; add authenticated `GET /attempts/{attempt_id}/predictometer`; expose only safe fields. Stream updates via existing turn events where available; frontend may poll the endpoint for edits outside a turn. Scope access to current attempt and keep existing auth limits explicit.
- `coding-agent/src/coding_agent/config.py` and `pyproject.toml`: add only settings and model dependencies required by the actual selected adapter after feasibility checks; document requirements without secrets.
- `cloud-ide-reference/client/src/workspaceApi.js`: add `getPredictometer(attempt)`.
- `cloud-ide-reference/client/src/WorkspaceApp.jsx`: display the panel and refresh on accepted prompt, turn completion and editor save, plus bounded polling while open. Clean up polling on unmount/attempt change.
- `cloud-ide-reference/client/src/index.css`: only minimal component styling if existing styles are insufficient.
- `coding-agent/README.md`: local setup, optional model requirements, provider data-sharing and known gaps.

## Component contract and calculation

Each component returns `{status, score, evidence_revision, safe_reason}`. A score is `0..100` only when the provider/model output has an explicitly tested mapping; otherwise score is null and status unavailable. Do not expose author content in safe reasons. API example:

```json
{"status":"ready","score":76,"label":"Experimental predictometer score","prompt_count":5,"prompt_limit":10,"components":{"direction":{"status":"ready","score":80},"comparison":{"status":"ready","score":70},"rules":{"status":"ready","score":78}},"evidence_quality":"partial","updated_at":"2026-01-01T00:00:00Z","reasons":["Relevant files have been inspected","Agent reached its tool limit"]}
```

Initial candidate weights: Jev 20%, code comparison 35%, rules 45%. Calculate weighted mean across available scores, renormalizing available weights. Require at least two available components and label partial; fewer yields insufficient evidence. If a component is stale, mark it unavailable for the current calculation until refreshed. Store evidence revision and discard delayed responses for older revisions. If the attempt is too new to provide useful evidence, return insufficient evidence. Weights and scores are experimental, and confidence is only evidence coverage/freshness, not numeric statistical confidence.

Rule configuration initially evaluates: relevant file read, expected file changed, allowed expected code pattern detected in bounded content, and a structured per-turn tool-limit event. Match/not observed/unknown are distinct: path/pattern absence is not proof the solution is wrong; uncovered terminal edits make results incomplete. Tool-limit occurrence is marked as a workflow obstacle with a small experimental deduction, not an assessment of user ability. No parsing or use of test outcomes. Revisit numeric rule points after model and Jev contracts are verified rather than treating invented thresholds as calibrated.

## Tasks and checks

### 1. Feasibility and challenge definition
- [ ] Verify Jev SystemOne supports evaluating problem + private author approach + prompt + prompt counter, and determine actual request shape, output meaning, data handling and cost. Use a synthetic challenge first; preserve existing coding-request behavior. If unsupported, mark direction unavailable and report the blocker; do not substitute a different judge without approval.
- [ ] Select and test a small comparison model against examples of equivalent fixes, misleading similar fixes and unrelated changes. Confirm license, latency, hardware, context length and a defensible score mapping. If no viable model or hardware is available, return comparison unavailable and report why rather than fabricating a result.
- [ ] Create one local Flask challenge configuration and independently verify its original/reference pair and patterns. Record author guidance and reference outside user workspace.

### 2. Attempt evidence and counters
- [ ] Add attempt-wide accepted-prompt counter and event/revision records. Count each request once across chats, retries, resume and legacy paths; do not count rejected prompts.
- [ ] Capture relevant structured tool calls and tool-limit outcome, user saves and agent edits, with source and attempt isolation. Define event dedupe IDs. Do not promise attribution or coverage of uncontrolled terminal writes.
- [ ] Tests: multiple chats, duplicate request, rejected prompt, resumed attempt, file save, agent tool and limit, failed persistence, attempt isolation.

### 3. Rules and score
- [ ] Implement bounded rule evaluation on configured paths and patterns without accepting arbitrary user regex. Distinguish false, not observed and unknown; exclude all test results.
- [ ] Combine Jev, comparison and rules using candidate weights and minimum available components. Show partial/stale/error states instead of using fake zeros or confidence percentages.
- [ ] Tests: expected/alternative path, missing file, unsafe/oversized input, tool limit, incomplete coverage, all/missing/stale signals, rounding and zero-division.

### 4. Jev and comparison integration
- [ ] Invoke Jev separately from the existing sanity check, passing problem, approach, accepted prompt and prompt count/limit; do not delay the coding agent. Apply timeout, validate responses and redact private data from client/logs.
- [ ] Load the verified comparison model once, compare bounded original/current/reference changes and return unavailable on errors. Consider resource budget and no network to serve model unless approved; model execution stays outside candidate container.
- [ ] Debounce repeated edits; tag work with evidence revision and ignore late/outdated outputs. Ensure failure never blocks editing or a turn.
- [ ] Tests: fake Jev contract and timeout, mocked model, private-data leakage, concurrent updates, outdated responses and provider/model outages. Live smoke tests only when configured and permitted.

### 5. API and IDE
- [ ] Add authenticated attempt-scoped GET endpoint, persist latest score and resume after reload. Do not expose private config, reference content, or exact hidden patterns.
- [ ] Show score labelled experimental, generic reasons, prompt count and loading/partial/unavailable/stale states. Refresh after turn/save and with bounded polling; no polling leaks.
- [ ] Tests: authorization, attempt isolation, no hidden content, dedupe, reload/resume, accessible UI and state updates.

### 6. Validate and report
- [ ] Run focused backend and frontend tests, plus existing agent/chat/idempotency tests affected by the changes.
- [ ] Run one controlled end-to-end local attempt with a synthetic challenge; verify all three signals, editor save, agent event, limit event, timeout and attempt resume. Record actual timings and unavailable components.
- [ ] Review alternative valid fixes and misleading similar fixes. Collect future outcomes before calling score a calibrated probability; show calibration limitations.

## Review gates

User approval is required before starting implementation. The Jev comparison capability, prompt counter limit source, model choice/hosting and private data handling must be resolved or explicitly marked unavailable; do not silently change providers or introduce a paid dependency. No separate Run/Submit feature or final report is included in this plan.

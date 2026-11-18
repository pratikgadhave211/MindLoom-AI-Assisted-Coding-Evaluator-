# Submission Evaluation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement these tasks in order. The user reviews this plan before implementation.

**Goal:** Let a user solve a substantial Flask challenge, submit a saved workspace snapshot, and receive correctness, process, and usage feedback with traceable evidence.

**Architecture:** Extend the existing FastAPI attempt manager, PostgreSQL records, Docker workspace and React IDE. Run correctness checks against an isolated snapshot, then assess an evidence package with sequential, token-budgeted judge calls. Persist and show a report even if the judge fails.

**Tech stack:** Python, FastAPI, PostgreSQL, Docker, the existing LangChain model integration, pytest, React and Vite. Reuse installed packages; add a tokenizer only if it is required and suitable for the selected judge model.

**Spec:** The approved chat design: correctness and AI-assisted process shown separately; sequential batches carry a bounded summary and evidence IDs; simple code and comments. The challenge and rubric below are the proposed first instance.

## Global constraints

- Wait for the user's approval before implementation. Do not change the existing active challenge or user workspace while authoring the new challenge.
- Use simple functions, existing patterns and focused comments. No new queue, service or agent graph for the first version.
- Existing predictometer remains separate from the final submission report; its score does not determine correctness.
- The judge receives the problem, rubric and relevant saved evidence. The test engine determines correctness; model output cannot override it.
- A correct alternative implementation must be accepted by behavior checks; do not grade by exact reference-code match.
- Results must distinguish test failure, test infrastructure failure, missing evidence and judge failure.
- Never put real private reference solutions or hidden tests in candidate workspaces, client responses or public repositories. The local development example is not secret.
- Agent and evaluator token usage are separate; missing usage and prices are explicitly unavailable or partial.
- The platform is a local prototype; its shared API token and Docker isolation are not multi-tenant production security.

## Review focus

1. A snapshot cannot change after submission and must not silently omit saved source files.
2. Hidden tests and credentials cannot be exposed through the candidate workspace, API or unsanitized output.
3. A failed test runner is not classified as a failed solution.
4. Long or oversized events cannot exceed the judge budget or silently disappear.
5. Crash, retry and duplicate submission cannot run two different evaluations under one submission ID or mislabel an interrupted report as complete.

## Proposed first substantial question

**Candidate-facing title:** Secure, searchable blog posts.

**Context:** The Flaskr blog lets logged-in users write posts. Several users report that post management and discovery do not behave as expected.

**Requirements:**
1. Only the author can update or delete a post. A different logged-in user gets HTTP 403; logged-out users are redirected to login. The author can still manage their own posts.
2. Add a `q` search parameter to the blog index. Ignore leading/trailing spaces and match titles and post bodies case-insensitively. An empty or missing search returns all posts. Search text must be handled as data, including quotes and SQL wildcard characters; define literal-substring matching and test it.
3. Add `page` navigation with a fixed page size of five. Results are newest first with an explicit stable ID tie-breaker. Search must be applied before pagination; navigation must preserve `q`.
4. Invalid page values and requests beyond the last page have a specified, tested response: HTTP 404. Existing create, edit, delete and login flows must continue working.

The question page will include setup commands, examples, acceptance criteria, constraints and how to run visible tests. It will not reveal which source lines to change or the reference fix. The author creates this as a **new template copied from the existing Flask project**, with independent authorization and search/pagination defects that require changes in multiple relevant files. Confirm the initial state actually violates all intended behaviors and that normal setup runs before using it as an assessment.

**Reference:** A server-side example patch or solution plus a rubric describes the intended behavior, not a required implementation. Challenge-specific hidden behavior checks decide correctness. An alternative valid fix should pass.

## Proposed file map

Create:
- `broken-repos/flaskr-secure-search/`: new independent broken challenge template and candidate-visible tests/instructions.
- `coding-agent/challenges/flaskr-secure-search/question.md`: complete candidate-facing problem.
- `coding-agent/challenges/flaskr-secure-search/challenge.json`: challenge ID, setup/runtime and named behavior IDs.
- `coding-agent/challenges/flaskr-secure-search/rubric.json`: process-review criteria and safe wording.
- `coding-agent/challenges/flaskr-secure-search/reference.patch`: local example solution, kept outside candidate workspace.
- `coding-agent/challenges/flaskr-secure-search/hidden/`: local developer-only black-box checks and expected behaviors; not secret when committed publicly.
- `coding-agent/src/coding_agent/submissions.py`: submission lifecycle, snapshot coordination and report persistence using the existing manager pattern.
- `coding-agent/src/coding_agent/submission_tests.py`: isolated candidate runtime and host-side black-box check orchestration, with bounded/sanitized outputs.
- `coding-agent/src/coding_agent/submission_evidence.py`: bounded event selection, submitted diff and deterministic usage counts.
- `coding-agent/src/coding_agent/submission_judge.py`: token-budgeted sequential batching, validated summary and report feedback.
- `coding-agent/tests/test_submissions.py`, `test_submission_tests.py`, `test_submission_evidence.py`, `test_submission_judge.py`: focused backend checks and opt-in Docker/PostgreSQL end-to-end tests.
- `cloud-ide-reference/client/src/components/ChallengePanel.jsx`: question and acceptance criteria.
- `cloud-ide-reference/client/src/components/SubmissionReport.jsx`: progress, correctness, process, evidence and usage report.

Modify:
- `coding-agent/src/coding_agent/attempts.py`: associate the selected challenge with an attempt, use existing busy/terminal guards and publish/persist required bounded events.
- `coding-agent/src/coding_agent/api.py`: authenticated question, submit and submission-status/report endpoints.
- `coding-agent/src/coding_agent/memory.py`: small tables for attempt challenge association, submission status/report and deduplicated usage; keep code out of PostgreSQL.
- `coding-agent/src/coding_agent/agent.py` and `graph.py`: record actual per-model-call usage when the provider returns it and necessary tool evidence; retain missing/partial status.
- `coding-agent/src/coding_agent/config.py` and `model.py`: explicit judge model configuration and known context budget; reuse the existing hosted provider initially. Do not infer limits from `openrouter/free`.
- `coding-agent/src/coding_agent/container_workspace.py`: reuse Docker patterns for safely copying snapshots; do not alter active volumes.
- `coding-agent/tests/test_api.py`, `test_attempts.py` and relevant existing tests: authorization, state, snapshot and compatibility coverage.
- `cloud-ide-reference/client/src/workspaceApi.js`, `WorkspaceApp.jsx` and `components/AIPanel.jsx`: challenge fetch, submit control, prevent unsaved submissions, status and report access; preserve the current chat/predictometer.
- `cloud-ide-reference/client/src/workspaceApi.test.js` and existing frontend test setup: request and failure-state checks; add UI tests only with existing tooling or the smallest suitable test.
- `coding-agent/README.md`: setup, local use, known isolation/coverage and provider data-sharing limitations.

## Task 1: Author the complete challenge

**Consumes:** Existing Flask challenge template and its setup/tests. **Produces:** New question, broken template, example solution, visible and hidden checks, rubric.

- [ ] Copy the existing challenge to the new template without changing its active workspace or the original baseline.
- [ ] Write the full question and acceptance criteria above, including example inputs/outputs and literal search semantics.
- [ ] Introduce independently verifiable defects and create behavior checks for each acceptance criterion plus existing regressions.
- [ ] Verify the broken template fails the intended checks, the example fix passes them, and a different correct implementation is accepted.
- [ ] Verify the candidate template includes neither hidden checks nor reference patch.

## Task 2: Submission snapshot and lifecycle

**Interfaces:** `create_submission(attempt_id, request_id)` returns a stable submission ID; `get_submission(attempt_id, submission_id)` returns status/report. The snapshot helper creates one immutable saved copy.

- [ ] Add persistent `submissions` records with ID, attempt/challenge ID, request ID, snapshot identifier, status and bounded report JSON. Add a unique attempt/request key for safe retries.
- [ ] Reject submissions while a turn or terminal is active, or while a frontend draft is unsaved. Keep user workspace and snapshot separate.
- [ ] Copy safely: validate source/target, handle symlinks and archive paths, exclude only explicit generated/dependency paths, and fail rather than silently dropping source files. Bound size/time and record failures.
- [ ] Add authenticated endpoints scoped to the attempt: retrieve candidate question, start submission and get status/report. Return 404 for mismatched IDs.
- [ ] Start a background worker after snapshot creation. On restart, mark orphaned `running` records as interrupted; a deliberate retry uses an explicit new or idempotent request policy. Persist failures and clean temporary containers, retaining snapshots according to documented local cleanup rules.
- [ ] Test duplicate requests, busy/terminal guards, snapshot stability after later edits, cross-attempt access, restart and snapshot failure.

## Task 3: Isolated correctness checks

**Interface:** `run_checks(snapshot, challenge)` returns status, behavior outcomes, counts and sanitized diagnostics; it does not return hidden source or raw private paths.

- [ ] Start candidate code in an ephemeral container using an isolated copy of the snapshot, no host mounts, credentials or Docker socket, and bounded CPU, memory, processes, time and output. Disable external network access.
- [ ] For hidden behavior checks, prefer a separate trusted host-side test harness talking to the candidate app over a controlled local channel; do not mount hidden tests into the candidate container. Map results to generic behavior IDs. Candidate responses and output are untrusted and sanitized.
- [ ] Run visible/regression checks where practical and record their results separately from hidden behavior checks. Classify setup errors, timeouts and crashes as evaluation errors when correctness cannot be determined.
- [ ] Verify correct, partial and wrong implementations and a test crash/timeout. Verify hidden files, reference patch and credentials do not appear in the workspace or API responses.
- [ ] Document that Docker is not a strong boundary against an actively hostile multi-tenant workload; production needs stronger isolation and independently reviewed test security.

## Task 4: Evidence and usage

**Interface:** `collect_submission_evidence(attempt_id, snapshot)` returns ordered events with stable IDs, bounded relevant diffs, deterministic statistics and coverage notes.

- [ ] Extend existing event collection for needed prompt, response, tool outcome and verification evidence without storing secrets or unbounded outputs. Preserve existing chat/request idempotency.
- [ ] Record each model call's provider/model and input/output usage when present; do not treat missing values as zero. Track evaluator calls separately.
- [ ] Compare snapshot to the original template safely and bound diff/file output. Mark terminal edits and actor attribution unknown where necessary.
- [ ] Aggregate counts directly; show estimated cost only with reliable pricing and usage. No judge counting.
- [ ] Test repeated request IDs, mixed available/missing usage, long tool outputs, evidence gaps and multi-chat attempt ordering.

## Task 5: Sequential judge batches

**Interfaces:** `make_batches(problem, rubric, events, budget)` returns chronological token-sized batches; `review_batches(...)` carries a validated summary sequentially; `make_report(...)` joins correctness, feedback, counts and coverage.

- [ ] Configure an explicit supported judge model and verified usable context limit; use its tokenizer if available. If sizing cannot be established reliably, mark judge feedback unavailable rather than guessing a safe size. Do not use total agent token burn as context size.
- [ ] Reserve tokens for full message formatting, problem, rubric, carried summary, response and safety margin. Pack chronological related events together where possible; split or bounded-summarize an oversized event and retain original event IDs.
- [ ] For each batch in order, send problem + rubric + previous structured summary + current batch. Return observations, evidence IDs, unresolved points and gaps. A later batch may revise earlier findings.
- [ ] Bound/compact the carried summary without dropping evidence references silently. If the summary or a single item cannot fit safely, return partial/unavailable feedback with a reason. The last batch produces the process assessment used by the report generator.
- [ ] Validate judge output and referenced event IDs; treat prompts, code and tool output as untrusted data. On timeout, malformed output or missing batch, preserve earlier results and label feedback partial/unavailable. Never invent test results, user thoughts or provider usage.
- [ ] Test short one-call input, boundary fits, oversized single events, sequential dependencies, summary growth, fake tokenizer/model, invalid evidence IDs and judge failure.

## Task 6: IDE question, submit and report

- [ ] Display the full question and acceptance criteria in the IDE, independent of chat. Show the correct challenge for the active attempt.
- [ ] Add Submit with clear disabled/explanatory states for unsaved drafts, active agent/terminal and in-progress submission. Use a stable request ID for retries.
- [ ] Poll the authenticated submission endpoint without overlapping requests and stop polling on unmount/completion. Allow re-opening the saved report.
- [ ] Show progress: preparing snapshot, running checks, reviewing process and completed/failed. Never show hidden test source, private rubric or raw judge prompts.
- [ ] Report correctness separately from AI-assisted approach, verification, code activity, reflection and usage. Show safe evidence references, unknowns and partial token/evidence coverage. Do not label an experimental aggregate as a success probability.
- [ ] Test empty/loading/error/partial/success states, retry, unsaved-draft guard, attempt isolation and keyboard accessibility. Run the frontend build.

## Task 7: End-to-end acceptance

- [ ] Run focused backend and frontend tests, then Docker/PostgreSQL tests on temporary attempts.
- [ ] Submit broken, partially fixed, reference-fixed and alternative-correct snapshots; confirm behavior results and that later edits cannot change an existing report.
- [ ] Run short and long synthetic timelines through a fake judge, verifying one request vs sequential batches and evidence IDs. Separately perform a clearly labeled hosted-judge smoke test only with synthetic data and configured credentials.
- [ ] Test judge outage, test-container timeout, unavailable usage and server restart. Confirm a report clearly identifies what could and could not be evaluated.
- [ ] Update the README and report exact test results, skipped cases and remaining production limitations. Ask the user for review before further phases if requested.

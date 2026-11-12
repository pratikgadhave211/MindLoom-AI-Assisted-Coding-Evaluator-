# Standalone Coding Agent Implementation Plan

> **Updated direction:** The user chose LangChain and LangGraph and wants to build only prompt validation → model → placeholder tool selection first. [Phase 1 plan](PHASE_1_PLAN.md) replaces the implementation choices below for that phase. Treat the remaining sections as an earlier full-system draft: revise them for LangChain/LangGraph before executing later phases.

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. This document is a plan; do not treat it as evidence that the agent exists.

**Goal:** Build a terminal-first coding agent that uses an OpenRouter free model to inspect and change a private copy of the Flask challenge, run tests, and report evidence.

**Architecture:** A host-side controller owns the API key, conversation, prompt counter, and model/tool loop. A disposable Docker workspace contains a fresh repo copy and preinstalled dependencies; it executes workspace operations but never receives the model API key. A CLI displays events and results. Later an IDE can call the same controller interface.

**Tech stack:** Python 3.11+, Docker, OpenRouter chat completions API, pytest, SQLite for local session metadata. The existing Flask challenge image provides Python 3.13, Flask, and pytest.

**Spec:** This plan records the user's discussed workflow: prompt sanity → model → sequential/parallel tools → tool results and history → model → checker → result. The user chose OpenRouter free API and terminal-first execution. “JEV” was mentioned for sanity checking but remains undefined; do not assume an additional classifier or library.

## Scope and constraints

- No IDE integration, scoring, profiles, or multi-user production deployment in this milestone.
- Preserve `broken-repos/broken-flaskr-blog` as a template; use its baseline commit `0ddde74d7d86a0d39603b45162efc889eb34b72d` for copies. Never let the agent edit the template.
- Use only the configured free OpenRouter model (`openrouter/free` by default or an explicit `:free` model); disable paid fallbacks. Confirm tool calling is supported at runtime. The router can change models between requests, so record the actual model when supplied.
- OpenRouter credentials are loaded from `OPENROUTER_API_KEY` by the controller; never bake or mount them into the workspace or write them to logs.
- One prompt is one accepted user message, not a model call or tool invocation. Default to 50 prompts per attempt, configurable to 100. Persist and enforce the count locally across CLI reconnects; production identity and quotas remain future work.
- The workspace container has no Docker socket, host project root, credentials, hidden tests, or outbound network. Run as non-root with a writable session workspace and temporary directory, plus resource and execution limits. Docker isolation is a local prototype, not a claim of production-grade untrusted-code isolation.
- Default limits for the prototype: prompt ≤ 12,000 characters; ≤ 12 model calls per user turn; ≤ 30 seconds per command; ≤ 64 KiB captured output per tool; at most 3 concurrent read-only tools. Expose these as configuration, and report limit hits.
- Token usage is recorded when returned by OpenRouter; missing usage is `unknown`, not zero. Free-model API request quotas are distinct from user prompt limits.

## Planned structure

```text
coding-agent/
├── IMPLEMENTATION_PLAN.md
├── pyproject.toml                    # dependencies, package and test configuration
├── README.md                         # startup, limits, sample flow and security scope
├── src/coding_agent/
│   ├── cli.py                        # interactive terminal; display and cancellation
│   ├── config.py                     # configuration and startup validation
│   ├── session.py                    # SQLite attempt, history and atomic prompt count
│   ├── sanity.py                     # deterministic prompt validation
│   ├── model.py                      # OpenRouter requests and response normalization
│   ├── agent.py                      # bounded model/tool/checker loop
│   ├── tools.py                      # schemas, argument validation and scheduling
│   ├── workspace.py                  # workspace/container lifecycle and session binding
│   └── runner.py                     # container-side file/command operations
├── docker/
│   └── Dockerfile.workspace          # agent runner and challenge dependencies
└── tests/
    ├── test_session.py
    ├── test_model.py
    ├── test_agent.py
    ├── test_tools.py
    └── test_workspace.py
```

Runtime workspace copies and SQLite data live under an ignored `coding-agent/.runtime/` directory. The controller and runtime data are never mounted inside the workspace. The future IDE must mount only the relevant session workspace.

## Main function flow

1. `cli.main()` loads configuration, creates or resumes an attempt, and starts a private workspace.
2. `sanity.validate_prompt(text, max_chars)` rejects empty/oversize input. `session.accept_prompt(attempt_id, request_id, text)` atomically checks/increments the quota exactly once; duplicate request IDs return their original outcome and never start a second model call. A user cancellation before acceptance consumes no prompt. An accepted request remains counted even if the provider fails; display that policy.
3. `agent.run_turn(session, prompt, model, tools)` adds the user turn to history and sends messages plus tool schemas to `model.complete(messages, schemas)`. Preserve the complete assistant tool-call message, including provider-specific reasoning fields required for continuation. Never claim that history captures hidden model reasoning.
4. A response can contain zero or multiple tool calls. Validate each name, JSON arguments, path, and schema. Unknown/malformed requests produce a bounded tool-error result rather than executing arbitrary code. Match each result to its `tool_call_id`, retaining model order, then append every result before the next request.
5. `tools.execute_batch(calls, runner)` runs contiguous batches of independent read-only operations concurrently (up to 3), then joins them before any write/command. All edits and commands run sequentially in request order. Never run a read concurrently with a write or command. If dependency between reads is expressed only in the model's reasoning, they must arrive in separate model turns; do not infer missing arguments.
6. Tools: `list_files(path)`, `search_files(query, path)`, `read_file(path, start_line, max_lines)`, `apply_patch(patch)`, `run_command(command)` and `run_checks()`. The checker runs the configured visible `python -m pytest -q`; it reports command, status, output and timeout, not a universal truth about correctness. Validate paths including symlinks, patch boundaries, stale file content and output size. Workspace isolation is enforced by the container boundary, not path validation alone.
7. The runner returns structured results (`ok`, `exit_code` or null, `stdout`, `stderr`, `timed_out`, `truncated`). The controller adds them to history and emits user-visible events. Keep detailed tool output out of default logs; do not log credentials.
8. After edits for a coding task, request the configured checker before reporting verified success. Failed checks return to the model while budget remains. If checking is unavailable, times out, or fails, the final response must report that outcome; don't silently claim success. Do not force code changes or tests for a simple question.
9. On model final response, cancellation, provider failure, or exhausted limit, return a result with summary, changed-file diff, checks actually run, actual model and reported token usage. A missing final answer at the step limit is an incomplete run, not success.

## Review focus

- Concurrent submissions or retried request IDs cannot exceed or double-consume the attempt quota (Task 2).
- `..`, absolute paths, symlinks, malformed patches and stale edits cannot escape the session or overwrite unexpected content (Task 3).
- A model reply with multiple tool calls produces one matched result for each; reads parallelize without racing a write (Task 4).
- A failed/timeout checker, missing provider usage, cancellation or step limit yields a truthful result and leaves no runaway process (Tasks 3, 5).
- Two workspace attempts start from the same committed template and cannot see each other's changes or the controller credentials (Task 3).

## Task 1 — CLI, config and OpenRouter adapter

**Files:** `pyproject.toml`, `src/coding_agent/{cli,config,model}.py`, `tests/test_model.py`, `README.md`.

**Interfaces:** `load_config(env) -> Config`; `complete(messages, schemas) -> ModelResponse`; `main() -> int`. `ModelResponse` preserves the assistant message and tool calls, actual model, optional usage and provider error.

- [ ] Write a fake HTTP transport test for a text response, multi-tool response, missing usage, malformed JSON and HTTP 429; assert secrets are absent from errors.
- [ ] Implement the OpenRouter `POST /api/v1/chat/completions` adapter using bounded request timeouts; require a configured free model, validate startup configuration, and expose rate-limit and unsupported-tool errors without silent paid fallbacks.
- [ ] Verify `python -m pytest tests/test_model.py -q` passes without a network call or API key. Document `OPENROUTER_API_KEY` as an environment variable; never print its value.

## Task 2 — Prompt sanity and session state

**Files:** `src/coding_agent/{sanity,session}.py`, `tests/test_session.py`.

**Interfaces:** `validate_prompt(text, max_chars) -> str`; `SessionStore.accept_prompt(attempt_id, request_id, text) -> Acceptance`; `append_messages(attempt_id, messages) -> None`; `load_history(attempt_id) -> list[Message]`. Persist assistant tool calls and tool results in order so completed turns can be resumed; never replay an in-flight model call on duplicate request ID.

- [ ] Test empty/oversize input, prompt 50 accepted and 51 rejected, configurable 100, duplicate request IDs, persistence after reopening, and two concurrent acceptance attempts with one remaining slot.
- [ ] Implement normalized prompt validation and SQLite transactions with a unique `(attempt_id, request_id)` key. Persist the limit and accepted count per attempt; reserve once before any model call.
- [ ] Verify `python -m pytest tests/test_session.py -q` passes. Invalid prompts do not consume quota; provider errors after acceptance do.

## Task 3 — Private workspace and tools

**Files:** `docker/Dockerfile.workspace`, `src/coding_agent/{workspace,runner}.py`, `tests/test_workspace.py`.

**Interfaces:** `create_workspace(attempt_id, template_revision) -> Workspace`; `run_tool(workspace, name, args) -> ToolResult`; `close_workspace(workspace) -> None`.

- [ ] Test two independently created workspaces against the same baseline: changing one leaves the other and template unchanged. Test `..`, absolute paths, symlink escapes, failed patch context, and secret/host-project access.
- [ ] Copy the committed template into a unique session directory; start a session container using the preinstalled dependencies. Validate the resolved session directory before cleanup. Expose only that copy in `/workspace/challenge`; never mount the Docker socket or controller directories.
- [ ] Implement the six workspace operations, bounded output, command timeout and cancellation cleanup. Container-side file edits must reject ambiguous patches and preserve files on error; commands run inside the container, never silently on the host.
- [ ] Verify `python -m pytest tests/test_workspace.py -q` using Docker; explicit skip with reason if Docker is unavailable. An attempted escape must fail, and timeout/cancellation must leave no active child command.

## Task 4 — Tool dispatch and ordering

**Files:** `src/coding_agent/tools.py`, `tests/test_tools.py`.

**Interfaces:** `tool_schemas() -> list[dict]`; `execute_batch(calls, runner) -> list[ToolMessage]`.

- [ ] Test two simultaneous independent reads, ordered read→edit→test, conflicting writes, multiple `tool_call_id`s, unknown tools, invalid JSON/arguments, and capped tool output. Assert no write/command overlaps any other operation.
- [ ] Implement schema validation, bounded read-only parallel batches, sequential mutations and commands, and result ordering/correlation.
- [ ] Verify `python -m pytest tests/test_tools.py -q` passes using a fake runner.

## Task 5 — Model loop and checker

**Files:** `src/coding_agent/agent.py`, `tests/test_agent.py`.

**Interfaces:** `run_turn(session, prompt, model, tools, limits) -> TurnResult`; `TurnResult` contains completion state, final message, recorded tool events, checks and optional usage.

- [ ] Test fake model sequences for text-only answer; read→edit→failing test→repair→passing test; multiple tool calls; provider 429; cancellation; model-call limit; missing usage; and unavailable/failed checker. Assert tool results are sent with matching IDs and verification claims follow actual results.
- [ ] Implement the bounded loop and required post-edit check. Stream concise progress to the CLI; store only agreed session metadata by default.
- [ ] Verify `python -m pytest tests/test_agent.py -q` passes offline. A failed check is visible and never reported as passing.

## Task 6 — End-to-end proof

**Files:** `README.md`, end-to-end test additions under `tests/`.

- [ ] Run the full offline suite (`python -m pytest -q`) including a scripted fake model against a disposable Flask workspace. Confirm it inspects the broken code, applies a controlled repair, runs pytest, reports success, and leaves the template unchanged. Independently confirm a deliberately failing check reports failure.
- [ ] With an explicitly configured OpenRouter key and tool-capable free model, perform one optional live smoke test against a *new disposable copy*. Record actual model, accepted tool calls, final diff, test output, token usage when returned, and rate-limit errors. A free model is not guaranteed to solve the task: report the observed result rather than treating model output as proof.
- [ ] Verify no API key is present in the workspace, process logs, or recorded events; verify no workspace is left running after explicit cleanup. Document commands and measured results.

## Complexity and operational notes

- Prompt validation is O(P) in prompt length P. SQLite quota acceptance uses one indexed transaction; concurrency is serialized by SQLite for the short write.
- Listing/searching is O(N) in visited files or bytes; bound results and do not load the whole repository into the model. Reading/editing is O(F) in touched file size F.
- A turn makes at most M model calls and K tool calls; token/time cost depends on the accumulated context and tool outputs, not only the user's prompt. Output limits and the M cap keep growth bounded. Never silently discard tool-call/result pairs when trimming context; stop with an explicit context-limit error until a tested compaction design exists.
- Read-only concurrency improves latency for independent I/O; it does not change total work and is capped at 3. Serial writes prioritize consistency.
- Temporary workspace copies cost approximately repo size per attempt; the prebuilt dependency image layers are shared, while each container has its own writable state.

## References

- OpenRouter tool-call contract: https://openrouter.ai/docs/guides/features/tool-calling
- Multiple calls, IDs and model support: https://openrouter.ai/blog/tutorials/tool-calling/
- Free model availability and rate limits: https://openrouter.ai/collections/free-models/

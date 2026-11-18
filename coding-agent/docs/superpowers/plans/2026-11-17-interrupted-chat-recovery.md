# Interrupted Chat Recovery Implementation Plan

**Goal:** Let a user continue an interrupted chat in the same workspace by sending a new prompt, while giving the model honest context about unfinished tools.

**Architecture:** Before the existing graph starts a new turn, inspect the chat checkpoint and prepare a consistent message history. Preserve confirmed `ToolMessage` results and add one explicit interrupted/unknown `ToolMessage` for each unresolved tool-call ID. Do not automatically replay the unfinished calls. After safely closing the old checkpoint's scheduled graph work, run the existing graph with the user's new prompt. No recovery graph node or conditional edge is added.

**Stack:** Existing Python, LangGraph, LangChain messages, PostgreSQL checkpointer, FastAPI and Docker workspace. Use the standard library and existing dependencies.

**Spec:** The user's agreed design in this conversation: restore the saved conversation, separately identify unfinished tools, and let the model decide how to proceed when the user sends a new prompt. A prompt may be any valid request; no literal `try again` trigger is required.

## Constraints and review focus

- Keep the solution simple and use the existing graph shape. No new queue, LLM judge, automatic replay, or model/tool limit changes.
- Preserve completed messages, confirmed tool results, prior chats, workspace files and the user's new prompt. Never manufacture a successful result.
- A checkpoint is not proof of a tool's real-world outcome. Existing `tool_started` / `tool_finished` UI/debug events may be missing, are not a reliable exactly-once execution log, and can contain truncated results. Only use a complete matching checkpointed ToolMessage as a confirmed result; otherwise say outcome unknown, not 'did not run'.
- An unresolved edit or command may have modified files. Tell the model to inspect the current workspace before deciding what to do; do not execute any recovered tool automatically.
- A graph interrupted inside a node may have `state.next` set; a graph ended with pending calls may have an empty `state.next`. Both need safe repair. A conditional edge reached only from START cannot by itself intercept an already scheduled node.
- Prevent an old process from continuing to edit the workspace concurrently: confirm the old turn is no longer active before repair. After an API crash, use only verified attempt/workspace information to identify and stop the old agent-owned workspace container before reusing its volume. If it cannot be determined safe, return an actionable error and do not start recovery. Never stop unrelated containers or delete volumes.
- Existing request idempotency must not cause retries to create duplicate recovered messages or duplicate model turns. Recovery must be serialized per attempt/chat. Do not re-execute side-effecting tools while restoring state.
- Preserve message ordering: the original AI tool-request message, exactly one matching ToolMessage per tool-call ID, and only then the new HumanMessage. Reject ambiguous duplicate/missing IDs safely instead of sending an invalid provider message.
- Existing workspace and conversation events may be incomplete, especially for older or legacy chats; describe unknown outcomes honestly.
- This change does not prove exactly-once execution and does not add per-tool execution state tracking. A durable tool ledger can be a later project if reliable proof is required.

## Existing behavior

- `src/coding_agent/agent.py` builds the graph then rejects a checkpoint with `graph.get_state(config).next`.
- `src/coding_agent/graph.py` checks `pending_calls` during `check_prompt` and returns 'start a new conversation'. Its `execute_tool` writes a ToolMessage after running a tool and removes it from the pending queue.
- `src/coding_agent/tracing.py` invokes the graph with a fresh prompt; it does not currently repair unfinished state.
- `src/coding_agent/attempts.py` serializes the workspace and persists chat UI events; API restart can mark requests interrupted. The CLI has a separate guard in `main.py`.
- A small isolated LangGraph experiment confirmed that, for a simple graph, `update_state(..., as_node='finish')` can create a checkpoint with `next == ()` without executing the interrupted node. This is only a feasibility observation: test that exact approach against our actual graph, state reducers, real PostgreSQL, graph versions and both interrupted/ended cases before relying on it.

## File structure and responsibilities

- **Create `src/coding_agent/recovery.py`:** small functions to inspect checkpoint messages/pending calls, find unresolved IDs, add honest ToolMessages, and safely prepare a completed checkpoint. Do not call a workspace tool or model. Return a small summary for the UI. Use the existing `finish` routing only if integration tests demonstrate `update_state` creates a finished checkpoint without executing scheduled nodes; verify checkpoint after updating and fail closed otherwise.
- **Modify `src/coding_agent/agent.py`:** invoke recovery before `stream_graph` instead of rejecting `state.next`; publish a short, non-sensitive progress event; then send the user's new prompt once through the existing graph.
- **Modify `src/coding_agent/graph.py`:** allow a properly repaired state to start a new prompt while retaining a defensive error for unresolved/invalid history. Keep normal tool execution and model loop unchanged.
- **Modify `src/coding_agent/attempts.py` and `container_workspace.py` only as needed:** coordinate recovery with active turns, prevent concurrent attempts, verify the prior tool process/container is stopped using the exact saved attempt volume, and retain the volume. No silent cleanup of unrelated resources.
- **Modify `src/coding_agent/main.py` and `tracing.py` only where necessary:** either use the same recovery helper for CLI and API, or explicitly document and test any different behavior; do not claim CLI recovery if it is not wired.
- **Modify `cloud-ide-reference/client/src/agentStream.js` only if needed:** existing `progress_update` can show 'Previous turn was interrupted; checking the workspace'. Do not invent a new event/UI if the existing event suffices.
- **Create `tests/test_recovery.py`:** focused message-repair, checkpoint-routing and idempotency tests. Extend `test_agent.py`, `test_idempotency.py` and PostgreSQL/Docker tests only where needed.
- **Update `coding-agent/README.md`:** explain the new behavior and the unknown-outcome boundary.

## Recovery example

Saved AI message requested `call-1` read, `call-2` edit and `call-3` read. A ToolMessage for `call-1` is already saved, but there are no ToolMessages for `call-2` or `call-3`. After ensuring no old process remains active, keep `call-1` exactly as recorded, add for `call-2` an error ToolMessage saying the edit was interrupted and its outcome is unknown, and add for `call-3` an error ToolMessage saying it was not completed and may have run unless reliable records prove otherwise. Preserve tool-call IDs and arguments in the original AI message. Complete/repair the checkpoint and send the user's new prompt normally. The model can then inspect the workspace and decide what to do next.

## Task 1 — Define and test history repair

- [ ] Add failing unit tests using real `AIMessage`, `ToolMessage`, and the actual saved `pending_calls` shape `[(invalid_flag, call), ...]`.
- [ ] Cover one/multiple unfinished calls, a mixture of completed and unfinished results, preserved ordering and exact IDs, unknown previous outcomes, and no double ToolMessage for already completed IDs.
- [ ] Cover malformed or missing IDs, duplicate IDs, unknown call names, no pending calls but an unmatched model tool request, and user messages containing instructions. Unsafe/ambiguous history returns a clear error without executing a tool or calling the provider.
- [ ] Implement the minimal helper in `recovery.py`; pass these tests. No database writes or tool calls in the pure message-building helper.

## Task 2 — Repair actual checkpoints and start the new turn

- [ ] Add failing tests for both (a) an interrupted graph with a scheduled tool node and (b) a graph ended with pending calls. Use the actual `build_graph` and `InMemorySaver`, not just a made-up graph.
- [ ] Verify the exact `update_state` operation preserves messages and clears `pending_calls`, produces `state.next == ()`, and does not execute the scheduled tool. Do not rely on behavior of a checkpoint from a different graph version without testing it.
- [ ] Replace the `agent.py` guard with the helper. After repair, let the normal `check_prompt` append the new user message exactly once. A clean conversation follows the existing path unchanged.
- [ ] Test an old checkpoint with no evidence records, a normal provider/tool error that already has a ToolMessage, failed checkpoint writes, interrupted repair followed by retry, and the remaining 25 model-call limit resetting for the new turn.

## Task 3 — Prevent active old tools and duplicate retries

- [ ] Add failing tests for an active old turn, an orphaned attempt-owned container after API failure, a stopped workspace, and two simultaneous retry requests. Do not stop or remove any container until its identity and attempt volume are verified.
- [ ] Reuse attempt locking and request IDs. Ensure an interrupted non-idempotent command is not reissued. If process/volume ownership is ambiguous or workspace cannot be made safe, surface an actionable error and do not pass a false result to the model.
- [ ] Preserve the workspace volume and all edits. Add an observable recovery progress update using the existing event type if sufficient.
- [ ] Document and test the difference between retrying the same request ID (existing interrupted request status) and sending a new 'try again' prompt with a new request ID.

## Task 4 — Integration, CLI and verification

- [ ] Add a real PostgreSQL checkpoint integration test for both scheduled-next and ended-with-pending states; simulate interruption before a tool, during an uncertain edit/command, and after a saved ToolMessage. Verify same chat and workspace, all tool IDs matched once, no repeated command/edit and exactly one new user message.
- [ ] Add a Docker workspace integration test proving a prior applied edit survives recovery without being applied twice, and a queued read is reported as unfinished for the model to decide on rather than executed by the harness.
- [ ] Verify normal chat history, idempotency, editor, terminal and graph tests; verify recovery progress is shown using the existing UI event.
- [ ] Check whether CLI can share the same helper; wire it if safe within scope, otherwise explicitly leave the CLI's existing behavior unchanged and report it.
- [ ] Report changed files, tests passed, remaining limitations and whether the old already-interrupted chat can be recovered. Restart the local API only after checking no turn is active.

## Acceptance criteria

The user sends a new prompt to an interrupted chat and the agent continues in the same conversation and workspace with accurate recovery context. Each prior model tool-call ID has one matching ToolMessage before the next model request. No unresolved edit or terminal command is silently replayed. The solution handles scheduled-next and already-ended checkpoints, duplicate requests and incomplete historical evidence. If the harness cannot ensure that the prior process is stopped or cannot safely repair the checkpoint, it reports the specific problem instead of guessing.

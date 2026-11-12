# Agent Progress Updates Implementation Plan

**Goal:** Show useful model-authored progress updates in the IDE while preserving the existing LangGraph tool loop and chat history.

**Architecture:** The model can return user-facing text with a tool call. The agent observes the completed model step, applies simple display rules, and publishes a `progress_update` through the existing event stream. The IDE renders saved and live activity in order.

**Constraints:** No new graph node or chat tool; no additional model calls; keep tool and model limits; do not display private reasoning; use the existing PostgreSQL event table; preserve existing chats and workspaces.

## 1. Guide the model

- Update the coding assistant system instruction in `src/coding_agent/graph.py` to request concise updates at meaningful findings, changes in direction, blockers, and before verification. Ask it to provide the update with its next tool call and to make claims consistent with tool results.
- Update only the known original agent system message when restoring an older checkpoint; preserve the rest of the conversation and any unfamiliar system messages. New chats get the new instruction. Test both cases.
- Keep `ask_model -> tool -> ask_model -> finish` and existing routing. Text-only responses still finish the turn.

## 2. Publish a progress event

- In `src/coding_agent/agent.py`, process completed `ask_model` debug events before filtering for tool names. Use the returned AIMessage's public text only when it also requests a tool; do not show reasoning metadata or final responses as progress.
- Publish `{type: 'progress_update', message: text}` before the corresponding tool event. Ignore empty text and exact duplicate updates within a turn. Keep updates concise; never label a tool result as successful based on commentary.
- Do not force an update every N tools; meaningfulness is guided by the model. If no update arrives, keep the existing neutral working indicator. Check NVIDIA's actual returned content format before exposing it.
- Add tests to `tests/test_agent.py` for ordering, empty text, repeated text, final-answer separation, unchanged tool execution, and no extra model calls.

## 3. Restore messages and stream in order

- In `src/coding_agent/attempts.py`, restore persisted `progress_update` events in `chat_history()` as progress messages. Use the existing event storage and preserve user, tool, error, and final-answer events.
- Reuse SSE in `src/coding_agent/api.py`; change it only if needed. Preserve turn IDs and Last-Event-ID behavior.
- Update `client/src/components/AIPanel.jsx` to display progress and tool activity in event order live and in restored history. Ensure reconnects do not duplicate messages; reset per-turn state for new prompts and preserve pending-request recovery.
- Extend existing backend and frontend tests to check ordering, reload, reconnect, failed tools and existing chats. Avoid adding tables or dependencies.

## 4. Validate end to end

- Run focused graph, agent, API/history and frontend tests and build the client.
- Use a simulated model and a disposable workspace to verify model text -> progress event -> tool -> final answer, including reopening the chat. Do not modify the user's challenge.
- If credentials and connectivity permit, run one small NVIDIA tool-call experiment in a disposable workspace. Report whether it actually produced commentary, not just whether it called a tool. Explain that message timing and truthfulness are not guaranteed by prompt rules.

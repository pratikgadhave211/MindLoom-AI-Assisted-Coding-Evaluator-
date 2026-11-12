# Agent API and Theia Integration Implementation Plan

> **For implementers:** Use superpowers:executing-plans after the user requests implementation. Work one milestone at a time. Keep code beginner-friendly and use Ponytail: reuse the current agent and Theia UI, avoid unnecessary abstractions, and add short explanatory comments.

**Goal:** Let a user open one challenge in a browser-based Theia IDE, choose our coding agent in chat, and see the agent work on the same challenge files shown in the editor.

**Architecture:** Theia's existing chat hosts a custom chat-agent adapter. A small Python API accepts prompts and streams progress from the existing LangGraph agent. The API owns the attempt ID, PostgreSQL checkpointer, and Docker agent workspace; a Theia backend accesses that same attempt's named workspace volume. IDE process and agent process are separate, so explicitly verify their working directories, runtime dependencies and file visibility.

**Stack:** Existing Python, LangChain/LangGraph, PostgreSQL checkpointer, LangSmith and Docker; FastAPI/Uvicorn for the local API; the existing Theia 1.77 browser application and a small TypeScript Theia extension. Pin tested API dependency versions during implementation.

**Related plan:** `2026-11-09-agent-api-ide-bridge.md`; this document adds Theia setup, integration, and the concrete shared-workspace approach. If the older plan assumes an API file bridge alone is a complete Theia filesystem, this plan takes precedence.

## Verified local starting point

- `theia-ide/` is a clean checkout of `https://github.com/eclipse-theia/theia-ide.git`, commit `93b8b13` (Theia 1.77.0). `applications/browser/package.json` includes Theia AI chat packages.
- The documented local command is `yarn browser start` in `theia-ide/`. On this machine it failed because `yarn` is not installed. `applications/browser/lib/backend/main.js` is missing, so there is no built browser application to start.
- The checkout requires Node >=24 and Yarn 1.x; the installed Windows Node reported 22.17.1. No Theia container or Theia image appeared in Docker inventory at the time of this check. The existing `theia-ide/browser.Dockerfile` uses Node 24 and builds from source, but its build and startup have not been verified here.
- The coding agent exists, uses PostgreSQL checkpoints and preserves a workspace volume per conversation. It currently starts from a CLI, runs one prompt, and stops the attempt container after that prompt. The Agent API and Theia adapter do not yet exist.
- Current known agent limitations: multiline exact-text edits can fail for CRLF/LF differences; the workflow stops at five model calls per turn. Show these honestly and decide specific fixes separately if they block the integration demo.

## Global boundaries

- This is a **local single-user prototype**, not public multi-user deployment. Bind local services to `127.0.0.1`; require a local API token and restrict origins. Do not expose a Docker socket, host project root, model credentials or hidden tests to the challenge container.
- Keep repository content and installed dependencies in the attempt's Docker storage. PostgreSQL stores conversation checkpoints and the conversation-to-volume mapping; checkpointed tool outputs can contain repository snippets.
- Preserve the agent's existing tool loop, Jev, OpenRouter settings, LangSmith trace names, and PostgreSQL thread IDs. Theia must invoke our Agent API; it must not silently run a second independent Theia/Copilot coding agent for the same prompt.
- One attempt at a time for the first demo; a separate named volume per attempt. Reject overlapping agent turns. Do not promise safe concurrent editing: unsaved Theia buffers, autosave, terminal writes, file watchers and agent edits require explicit handling and tests.
- Never build an image with `coding-agent/.env`, the host project, or Docker credentials in its build context. Theia's browser/backend credentials and the Agent API token are not available to the agent execution container.
- Keep implementation simple and easy to review: normal functions, clear names, minimal files, small TypeScript extension, short comments, and no replacement model/tool framework.

## Proposed user flow

1. Start PostgreSQL and the local Agent API; start a fresh challenge attempt through the API.
2. Start the browser Theia application for that attempt, with its backend pointed at `/workspace/challenge` on the **same named Docker volume** used by the agent.
3. Open the existing Theia AI chat and select or address our `Agentic` agent. A Theia chat-agent extension forwards the prompt and attempt ID to the Agent API.
4. The API invokes the existing LangGraph agent and streams real tool events and the final answer. Theia shows these in the chat; the editor and file tree observe saved workspace changes.
5. A second prompt uses the same PostgreSQL thread ID and workspace. When the user ends the attempt, stop its containers; retain the workspace volume and checkpoints until deliberately deleted.

## API contract

Use the contract in the related Agent API plan: authenticated `POST /attempts`, `POST /attempts/{attempt_id}/turns`, `GET /attempts/{attempt_id}/turns/{turn_id}/events` (SSE), and `DELETE /attempts/{attempt_id}`. Include an explicit authenticated resume endpoint or return a clear unsupported response until implemented. Events include `turn_started`, `tool_started`, `tool_finished`, `answer`, `error`, and `turn_finished`, with actual tool names, call IDs and status. Stream while the agent runs; do not send the full internal state.

The API stores no API key in its responses. Client requests never specify host paths, Docker names, image names, or another user's volume. Maintain PostgreSQL advisory locking and map the attempt to its existing checkpoint thread ID and Docker volume.

## Workspace integration decision

For the initial local prototype, use two per-attempt containers with the same Docker **named volume** mounted at `/workspace/challenge`: the existing isolated agent container and a Theia browser/backend container. The agent keeps its current `--network none` boundary. The Theia backend requires a reachable local port for its browser UI; bind the published port to loopback and configure/test its own network and access separately. Do not mount the host workspace or the Docker socket into either challenge-facing container.

Sharing a volume shares files, not processes or global installed software. Build or derive the two runtime images from compatible prepared dependencies so the Theia terminal and agent command runner can both run this Flask challenge without reinstalling dependencies. Verify that explicitly; do not claim processes, servers, environment variables, or packages installed outside the shared workspace are shared. Port forwarding and a common terminal runtime remain follow-up design work if this two-container setup cannot satisfy them.

Theia's file tree should open only `/workspace/challenge` by default; the container still has its own system filesystem, so this is not a guarantee that a malicious user cannot see anything else in that container. Preserve the stronger public-isolation work for a later phase.

## Files and responsibilities

### Python agent and API

- Create `coding-agent/src/coding_agent/api.py`: authenticated FastAPI endpoints, request validation, response and SSE serialization.
- Create `coding-agent/src/coding_agent/attempts.py`: active attempt/turn registry, one-turn-at-a-time locking, event buffers and lifecycle; use existing `memory.py` for checkpoint and workspace mapping.
- Create `coding-agent/src/coding_agent/agent.py`: reusable prompt/turn operation called by API and CLI.
- Modify `graph.py`, `tracing.py` and `main.py`: expose real progress, retain messages across turns via the existing checkpointer, and preserve the current CLI.
- Modify `container_workspace.py` and the workspace image setup: keep the agent attempt container alive while the IDE is connected; support explicit stop/reopen and return a server-side-only volume mapping for starting Theia.
- Update `coding-agent/pyproject.toml`, `README.md`, and Python tests. Reuse `compose.yaml` for PostgreSQL; add Theia/API orchestration separately without passing secrets into the Theia build context.

### Theia UI and adapter

- Create `theia-ide/theia-extensions/agentic-assistant/package.json` and `tsconfig.json`: register the local Theia extension in the existing Yarn workspace, using the exact Theia version from the checkout.
- Create `theia-ide/theia-extensions/agentic-assistant/src/browser/agentic-chat-agent.ts`: register an `Agentic` chat agent, forward the user message, display tool progress, answer, and errors in the existing chat. Verify the exact Theia 1.77 interfaces before implementation; do not assume the latest online example has the identical API.
- Create `theia-ide/theia-extensions/agentic-assistant/src/browser/agentic-frontend-module.ts`: bind/register the agent and its command/selection with the existing Theia application.
- Create `theia-ide/theia-extensions/agentic-assistant/src/common/agentic-protocol.ts`: small typed request/event shapes only if needed by both sides.
- Create `theia-ide/theia-extensions/agentic-assistant/src/node/agent-api-client.ts` and backend bindings only if required to keep the API credential out of the browser. Ensure credentials are not inherited by user terminals; a production solution needs separate identity/process boundaries.
- Modify `theia-ide/applications/browser/package.json` to include the local extension. Add the minimum build registration that this checkout actually requires; follow existing `theia-extensions/product` patterns.
- Add focused extension tests for event handling and an end-to-end browser test. No visual redesign, profile UI, evaluation layer, or unrelated Theia features in this milestone.

## Milestone 1 — Make local Theia start

- [ ] Choose the local-source development route: either provision Node >=24 and Yarn 1.x on Windows, or build the checked-out source with the Node 24 Dockerfile. Prefer the existing Dockerfile for a reproducible Linux prototype; document that local source edits require rebuilding or a configured dev watcher.
- [ ] Before downloading or installing, verify available resources and existing caches. Follow this checkout's documented build steps without running destructive cleanup commands. Record install/build failures with their real cause.
- [ ] Build the browser app from the local checkout and run it bound to loopback. Check HTTP response and visually confirm the editor, file tree, terminal and existing chat load. Do not claim readiness based solely on a process starting.
- [ ] Record the exact working commands, source commit, runtime versions, build time and whether the application uses a local build or image. Stop only test-owned processes/containers.

## Milestone 2 — Agent API and persistent attempt

- [ ] Add focused failing tests, then extract one agent turn from `main.py` without changing its user-facing CLI behavior. Reuse the PostgreSQL checkpointer and thread-to-volume mapping.
- [ ] Implement attempt create/resume/close, per-attempt lock and local authorization. Reject concurrent turns and fail clearly if Docker or PostgreSQL is unavailable. Do not restart an attempt with a new empty volume when its saved volume is missing.
- [ ] Stream actual graph/tool progress and final results as SSE, preserving trace context during stream consumption. Use a bounded event buffer, event IDs, reconnect behavior, clear terminal status and a visible error when a replay gap occurs.
- [ ] Run offline tests and disposable PostgreSQL/Docker tests. Verify two turns share conversation and workspace; another attempt remains independent. The CLI still works.

## Milestone 3 — Shared Theia and agent workspace

- [ ] Prototype the two-container, one-volume arrangement for one attempt. Generate the volume name and editor port server-side; ensure the Theia container is opened at `/workspace/challenge`, uses a non-root user, and has no host project mount or Docker socket.
- [ ] Verify permissions and runtimes: the Theia user and agent user can read and write the same challenge files; Python, Flask, pytest and any specifically required terminal runtime are available in the appropriate container without per-attempt installs.
- [ ] In a real browser session: user saves a file in Theia → agent reads the saved change; agent edits a file → Theia detects/reloads the changed file. Test file tree refresh, line endings and unsaved-buffer conflict behavior. Do not silently overwrite unsaved user changes.
- [ ] Test stop, timeout, restart and two separate attempts. Do not delete retained user volumes automatically. If Theia's terminal environment differs from the agent command environment, show/document that limitation and do not claim they are the same terminal.

## Milestone 4 — Add the agent option to Theia chat

- [ ] Confirm the Theia 1.77 `ChatAgent`/agent registry APIs and how an external agent can supply progress without invoking Theia's own model. First try registering our agent in the existing AI chat; if the installed version cannot support the required behavior, document the finding and use a small Theia widget rather than replacing the workbench.
- [ ] Add the `Agentic` option and API client. Submit a prompt to the existing attempt, display named tool events, answer and actual errors, and keep the composer disabled while a turn is active.
- [ ] Handle missing API, authorization failure, model rate limit, stopped container, disconnect and stale event replay. Never show an unsuccessful edit or failed test as a successful one; show actual results.
- [ ] Test message rendering using fake events and prove progress appears before the agent finishes. Verify the chat does not send a request through a second Theia model provider.

## Milestone 5 — End-to-end verification

- [ ] Use a fake scripted model for a deterministic integration: create attempt → open Theia → send prompt → read/edit/test → see real-time progress and changed file in the editor → send a follow-up prompt → observe persisted conversation and same workspace.
- [ ] Repeat with a second attempt and verify isolation, retained files after stop/reopen, no secrets in challenge containers, no host filesystem mounts, no unwanted container leftovers, and correct behavior when tests fail.
- [ ] Optionally try a live free OpenRouter model after the deterministic checks. Report actual rate limits, call-limit stops, or model mistakes; never treat the model's answer as proof of a successful edit.
- [ ] Update the README with exact start/stop, authentication, URLs, thread IDs, volume retention and cleanup, limitations, and testing steps. Verify LangSmith contains our individually named tool traces.

## References

- The checked-out `theia-ide/README.md`, `applications/browser/package.json`, and `browser.Dockerfile`.
- [Theia AI custom agents and chat](https://theia-ide.org/docs/theia_ai/)
- [Theia extension architecture](https://theia-ide.org/docs/extensions/)
- [Theia widgets](https://theia-ide.org/docs/widgets/)
- [FastAPI streaming](https://fastapi.tiangolo.com/advanced/stream-data/)

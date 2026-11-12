# Isolated Minimal IDE Implementation Plan

**Goal:** Open one question in a private, browser-based coding workspace with an editor, terminal and our AI agent panel.

**Architecture:** Use the pinned code-server source as the editor foundation. Start a separate workspace container for each user and question session, initially with a deliberately limited IDE layout. Build the agent sidebar as a VS Code extension and keep the trusted evaluator outside the workspace. Hiding UI elements does not remove their underlying code or enforce isolation; isolation is provided by the workspace boundary.

**Technology:** code-server, VS Code extension API, Docker, TypeScript, FastAPI; one sample Git repository.

**Reference:** `AGENTIC_IDE_CODEX_CONTEXT (1).md`, sections 3–6, 9, 11 and 14.

## Constraints

- Keep the pinned upstream checkout available for modification. Do not strip VS Code subsystems or patch internals without proving a need.
- Each session opens only its assigned repository, with independent writable files and terminal.
- No Docker socket, platform credentials or hidden tests in a user workspace.
- A loopback-only unauthenticated development server is for local development only; it is not the multi-user access model.
- The current source install was interrupted after upstream patches were applied; npm downloads timed out. Do not assume the source build has succeeded.

## Task 1: Establish a source-based IDE

- [ ] Inspect the state of the interrupted dependency install and applied patch stack; preserve existing files and avoid applying patches twice.
- [ ] Finish a reproducible Node 24/Linux source setup using the pinned checkout and its documented build prerequisites. Address the Windows checkout line endings and retry network failures with a persistent cache. Verify any omitted optional dependencies before relying on them.
- [ ] Start the source checkout in development mode on a local-only port. Verify an editor page loads, a file from a sample workspace opens and the integrated terminal can execute a command.
- [ ] Document the exact source revision, startup and stop commands, prerequisites and known limitations. Do not label the prebuilt Docker image as a source build.

## Task 2: Prove isolated question workspaces

- [ ] Create a small sample Git repository and a local workspace launcher that makes a separate copy and container for each session. Point each editor at its own repository directory, not at code-server source.
- [ ] Limit resources and execution time; keep secrets, hidden tests and the host Docker socket outside the container. Bind local development access to loopback.
- [ ] Launch two sessions, edit a file and run a terminal command in one, and verify the other session's files and terminal are unaffected. Verify stopping or reconnecting a session does not silently overwrite its work.
- [ ] Define cleanup and expiry behavior and verify it does not delete another session's files.

## Task 3: Minimal IDE experience

- [ ] Configure the default layout around the repository explorer, editor, terminal and agent sidebar. Use supported settings and extension APIs first; record any UI elements that cannot be removed that way.
- [ ] If an essential UI requirement cannot be met through supported APIs, document the smallest necessary source change and verify it against the pinned checkout before applying it.
- [ ] Check that a new session opens the assigned repository and that changing the UI does not become the security boundary.

## Task 4: Agent panel and workspace tools

- [ ] Create the separate TypeScript extension with a sidebar for prompts, messages and tool output. Install it into the source-based IDE environment.
- [ ] Connect it to a single backend agent with a configurable model provider and session-scoped workspace runner. Implement file read/edit and terminal/test commands with approvals and structured events.
- [ ] Verify a real prompt can produce an observable file change and test output in the same assigned workspace; verify another session cannot be accessed through those tools.

## Task 5: Platform launch and evaluation

- [ ] Add authenticated challenge selection and bind session creation to the server-verified user and question. Provide an authorized IDE route; do not expose the local unauthenticated development configuration.
- [ ] Capture an immutable snapshot on submit and evaluate it with protected tests in a separate sandbox. Store the result for the correct user and question.
- [ ] Verify separate users, repeat attempts, snapshot immutability and safe feedback. Keep hidden tests out of the IDE and candidate filesystem.

## Review focus

- Two users or questions cannot read or modify each other's workspace.
- Workspace restart and reconnect preserve work; cleanup is scoped to the correct session.
- Terminal commands cannot reach host controls, platform credentials or hidden tests.
- The editor, terminal and agent refer to the same session and repository.
- Source build, authentication and evaluator behavior are tested separately from UI appearance.

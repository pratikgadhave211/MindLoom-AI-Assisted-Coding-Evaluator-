# Code-server Foundation Implementation Plan

**Goal:** Establish a local, reproducible upstream code-server checkout as the base for the project IDE.

**Architecture:** Keep code-server in its own upstream Git checkout at `code-server/`. Integrate the project's extension through supported APIs in a later step; avoid modifying upstream internals for now.

**Tech stack:** Git, code-server, Docker or the upstream-supported development environment.

**Reference:** Project handoff `AGENTIC_IDE_CODEX_CONTEXT (1).md`, sections 3, 10 and 14.

## Steps

- [x] Clone `https://github.com/coder/code-server.git` into `code-server/`.
- [x] Verify the origin URL, checked-out commit, working tree and any submodule requirements; record the exact revision for reproducibility.
- [x] Read the checked-out upstream documentation and license. Identify the supported prerequisites and the appropriate Windows/WSL2 or Docker startup path.
- [x] Start the official Docker image and verify the login page and mounted workspace. A source checkout alone is not a running IDE.
- [ ] Later, add our separate VS Code extension and integrate the agent, challenge workspace, platform and evaluator in their own steps.

## Constraints

- Preserve the upstream checkout and do not patch IDE internals without a demonstrated need.
- Keep credentials and hidden tests outside user workspaces.
- Do not treat the clone as completion of the custom IDE, agent or challenge platform.

## Checkout recorded

- Upstream revision: `e609bb06e33ab50764959d34a406b069337275dc` (detached HEAD, shallow history).
- The `lib/vscode` submodule is checked out at `a717861c07586a53d83b80d742cd3f59b20a6273`.
- The prebuilt Docker image is running; it is separate from the local source, which has not been built.

# Edit, Command, and Test Tools Implementation Plan

> **For implementers:** Use superpowers:executing-plans after the user approves implementation. Implement each task in order, keeping code and comments beginner-friendly.

**Goal:** Let the terminal agent safely attempt a small Flask challenge using real edit, command, and test tools in a per-attempt container.

**Architecture:** Keep the current prompt → Jev → LangGraph → model → tool → model loop and the `@tool` definitions. A host-side controller owns the model and API keys; one disposable Linux container owns the workspace for one CLI attempt. Route all six file and command tools to the same container workspace so the model sees its edits on later reads. Use Docker as a local development isolation boundary, not a claim of production-grade untrusted-code security.

**Tech stack:** Python 3.11+, existing LangChain and LangGraph, Python standard library, Docker CLI, pytest, Flask. No additional Python package unless a verified necessity arises.

**Spec:** This plan and the previously approved Phase 2 plan `2026-11-07-workspace-read-tools.md` describe the intended workflow. The user requested a plan now; do not implement until they request execution.

## Current facts and scope

- `tools.py` supplies model-facing descriptions and dispatches to `@tool` workspace operations. `graph.py` has a sequential bounded loop and matching tool-result IDs. `workspace.py` currently runs read tools on a host folder, so this must change when arbitrary commands can alter the workspace.
- The challenge is `broken-repos/broken-flaskr-blog`; its normal test command is `python -m pytest -q`. Each attempt starts from a fresh copy. Preserve the template.
- Docker CLI is installed, but its Linux engine was unreachable when this plan was written. Verify Docker Desktop and available images at implementation time; do not claim an image was checked or running.
- One CLI run is one attempt with one prompt. Persistent conversation, Code Mode, evaluation, quotas, UI, cloud deployment, and semantic search are later work.
- Use ordinary Python functions, clear `if` statements and loops, descriptive names, brief section comments, and the standard library. Preserve necessary validation and error handling.

## Proposed flow

1. Validate the prompt and load credentials in the controller.
2. Create a unique challenge copy and start a per-attempt container. Copy only the challenge into its `/workspace/challenge`; no agent keys or controller folder go into the container.
3. The existing model loop selects one of six tools. The dispatcher uses the current attempt handle, never a model-provided container or workspace.
4. Execute each tool sequentially in the same container. Return a result with its tool-call ID to the model. The model can inspect, edit, run checks, and respond from actual results.
5. Stop and remove the attempt container when the CLI exits or fails. Keep its uniquely named Docker workspace volume for inspection, display the attempt ID and edit diffs, and document how to inspect or explicitly delete that volume. Do not automatically copy arbitrary container file trees to the host.

## Files to create or modify

- Create `docker/Dockerfile.workspace`: small Linux Python image with pinned Flask, pytest and a non-root user; install dependencies during image build, not every attempt. Copy the trusted runner into a root-owned, non-writable image location.
- Create `src/coding_agent/container_runner.py`: code run inside the container for list, search, read, and exact-text editing; reuse or move existing workspace functions so every tool sees the same files. Run it with `python` using structured JSON on stdin, not shell interpolation.
- Create `src/coding_agent/container_workspace.py`: host controller functions for start, call, and cleanup using Docker CLI with argument lists. Docker itself stays accessible only to the trusted controller.
- Modify `src/coding_agent/tools.py`: replace the three placeholder schemas with accurate descriptions and route six tools to the attempt controller. Preserve `@tool` and avoid allowing the model to choose a workspace/container ID.
- Modify `src/coding_agent/graph.py`: update the system instructions and preserve sequential execution, IDs, error messages and limits. Add tests for nonzero exits and timeout so the model cannot be told a failed check passed.
- Modify `src/coding_agent/main.py`: create the attempt after validation, pass its handle into the graph, and stop/remove its container in a `finally` block. Show actual tool results and final answer.
- Update `README.md`; add `tests/test_container_workspace.py`, `tests/test_container_runner.py`, and extend `tests/test_tools.py`, `tests/test_graph.py`, `tests/test_main.py`.

## Tool contracts

- `edit_file(path: str, old_text: str, new_text: str)`: change one existing UTF-8 file. Reject an empty `old_text`, missing or repeated matches, paths outside the workspace, symlink escapes, binary files, and oversized files; leave the file unchanged on any failure. Preserve its newline style and permissions; use an atomic replacement after validation. Return a bounded diff. File creation and deletion are later extensions.
- `run_command(command: str)`: run the requested command with `/workspace/challenge` as its initial directory in the container. Return stdout/stderr, exit code and whether output was truncated. A shell is needed for normal project commands, but it runs **inside** the container; send the command as a Docker argument, never interpolate it into a host shell.
- `run_tests()`: use the same container command runner with the trusted fixed command `python -m pytest -q`. Return actual exit code and output; do not infer success from the model's text.
- For reads, preserve current behavior and limits: workspace-relative paths, bounded output, keyword search, list cap, and explicit truncated/skipped notices.
- Model-facing tool argument schemas do not include host paths, attempt IDs, credentials, or Docker options. Preserve tool call IDs in LangChain `ToolMessage` results.

## Container boundaries and limits

- Per attempt: no outbound network, no Docker socket or host project mount, no host credentials or hidden evaluation tests, non-root user for user commands, read-only container root filesystem, writable workspace volume and bounded temporary directory; drop capabilities, enable `no-new-privileges`, limit memory, CPUs, processes and disk usage where the chosen Docker backend supports it. Treat unsupported disk quotas as an explicitly reported limitation, not an enforced limit.
- For the prototype use: command time limit 30 seconds, output cap 64 KiB, memory 512 MiB, 1 CPU, 128 processes. Keep existing 5-model-call and 10-tool-call limits unless deliberately revised.
- Stream and cap output while the process runs; do not collect unlimited output in memory. When output is capped, continue draining or safely stop the command so the process cannot deadlock.
- A timed-out or interrupted command stops the **whole attempt container**, including child processes; mark the attempt unavailable and stop the loop. Do not claim cleanup until confirmed. Use unique controller-created labels/IDs and only remove the current attempt's container; retain its workspace volume for review unless the user explicitly deletes it.
- Containers alone are not enough for hostile multi-tenant production use. Stronger isolation and authenticated ownership are separate work.

## Tasks and verification

### 1. Isolated workspace lifecycle

**Interfaces:** `start_workspace(template: Path) -> Attempt` and `stop_workspace(attempt: Attempt) -> None` in `container_workspace.py`; the attempt handle is created by the controller and never supplied by the model.

- [ ] Add tests for a fresh attempt, two independent attempts, unchanged template, missing Docker/image, container cleanup after start failure or graph error, and volume retention for an initialized attempt. Use fake Docker interactions for routine tests and an explicitly marked real-Docker integration test.
- [ ] Implement lifecycle with a unique attempt ID, container and volume; use a trusted image and copy only the challenge contents. Ensure the container's non-root user can modify its workspace; do not mount the host workspace into the untrusted container.
- [ ] Verify two attempts can alter their own workspace independently, the template stays unchanged, and no credentials or Docker socket are present. If Docker is unavailable, report the integration test as skipped, not passed.

### 2. Move existing reads into the attempt container

**Interface:** `run_workspace_tool(attempt: Attempt, name: str, args: dict) -> dict`, returning status, output, and execution details. Controller → runner messages use JSON over stdin; stdout is structured output, not a shell command.

- [ ] Write tests for list, case-insensitive literal search, read, missing files, traversal, absolute paths, symlinks, binary/large files, and output limits. A file created or changed inside the container must be visible to later reads in that same attempt.
- [ ] Move/reuse the Phase 2 operations in the container runner. Keep the `@tool` model definitions and dispatch logic understandable; do not expose internal workspace path as a model argument.
- [ ] Verify the existing graph read loop still works with a fake model and the actual container runner; verify no host read follows a link created by an attempt command.

### 3. Exact-text edit tool

**Interface:** `edit_file(path: str, old_text: str, new_text: str) -> str` at the model boundary. Change the existing `changes` schema to these explicit fields; update validation and tests together.

- [ ] Test one unique replacement, zero matches, duplicate matches, empty old text, same text, Unicode, Windows and Linux newline handling, a rejected outside/symlink path, and a write failure. On every failure the original bytes must remain unchanged.
- [ ] Implement the bounded atomic edit inside the container workspace; display the actual path and a bounded unified diff. No fuzzy replacement, file creation, or silent overwrite.
- [ ] Verify a subsequent `read_file` call returns the updated content, while another attempt and the template remain unchanged.

### 4. Command and test execution

**Interfaces:** `run_command(command: str) -> CommandResult` and `run_tests() -> CommandResult`; `CommandResult` contains output, exit code, timeout and truncation status. These are routed by the controller to the attempt container.

- [ ] Test successful and failed commands; quotes and shell operators stay inside the container; blank commands, large output, missing test runner, timeout with a child process, and interruption produce clear results. Confirm no attempt survives a timeout or cancellation.
- [ ] Implement one container command runner with bounded streaming and cleanup, then implement `run_tests` by calling that same runner with `python -m pytest -q`. Never fall back to host execution when Docker fails.
- [ ] Verify a test failure returns its real nonzero code, and a model-produced claim cannot replace the actual recorded output. No dependency installation occurs during the attempt.

### 5. Connect the loop and prove the complete flow

- [ ] Update graph instructions to reflect working tools; keep sequential dispatch and send actual errors and exit codes to the model. Do not let a command failure be automatically described as success.
- [ ] Use a fake model sequence: search → read → edit → failing test → further edit → passing test → final answer. Verify result IDs, ordering, real file content and exit codes, and that output reflects failure and success honestly.
- [ ] Run the existing offline suite and the Docker integration suite. Check the template and a second attempt remain unchanged, all attempt containers are removed, and keys are absent from the container.
- [ ] Document setup, how to run, limits, the one-prompt lifecycle, retained workspace volumes, how to inspect the diff and delete a specific attempt's volume, skipped integration tests, and the production-isolation limitation. Only attempt a live OpenRouter smoke test when the user requests or existing authorization supports it; report actual rate limits or model behavior.

## Review focus

- Host escape or credential leak from model-supplied commands: all execution and reads stay within a container with no host mount or Docker socket; no API keys in its environment.
- Ambiguous or failed edit: no partial writes; report the error and leave original bytes intact.
- Prompt cancellation or command timeout: stop the container and descendants; explicitly report cleanup failures.
- Output flooding, hung commands, or dependent tool calls: bound output and time, execute sequentially, preserve each ID and status.
- Docker unavailable or workspace lost: fail visibly with no host fallback; generated changes are shown as a bounded diff and remain in the attempt's Docker volume until explicitly deleted.

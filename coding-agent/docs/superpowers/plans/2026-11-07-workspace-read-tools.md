# Workspace and Read Tools Implementation Plan

> **For implementers:** Use superpowers:executing-plans to implement the approved plan one task at a time. Keep the code beginner-friendly and add short section comments.

**Goal:** Let the terminal agent inspect an independent challenge copy, gather context with keyword search, and use the results to answer.

**Architecture:** First create a fresh local workspace and implement three read-only tools. Then extend the LangGraph workflow with a bounded model/tool loop, sending each tool result back to the model with its call ID. Docker-isolated writes and commands follow in a later milestone.

**Tech stack:** Python 3.11+, LangChain tools, LangGraph, Python standard library, pytest. No new dependency is planned.

**Design:** `coding-agent/PHASE_2_DESIGN.md` (proposed, subject to review).

## Simplicity and readability

- Follow the Ponytail approach: use the smallest solution that meets the task, reuse existing project code, and prefer Python's standard library to new dependencies.
- Use beginner-friendly names, ordinary functions, clear `if` statements and simple loops. Avoid clever one-liners, unnecessary abstractions, advanced Python syntax, and extra frameworks.
- Add short comments to explain the purpose of important sections and any logic that is not obvious. Keep the comments accurate and avoid repeating what the code already says.
- Keep the existing LangChain and LangGraph structure, and preserve necessary validation, error handling, and isolation boundaries even when a shorter alternative exists.
- After each task, review the changed code for simpler wording or logic without changing its behavior; explain unfamiliar constructs in the README when they cannot reasonably be avoided.

## Global constraints

- Preserve the existing prompt check, advisory Jev behavior, free OpenRouter configuration, and terminal-first interface.
- Use `broken-repos/broken-flaskr-blog` as the initial template; never change it. No API keys or agent configuration are copied to the workspace.
- Each CLI run is one local attempt and receives a distinct directory under `coding-agent/.runtime/workspaces/`; the CLI still accepts one prompt per run. Local path validation is not a sandbox for hostile users or concurrent filesystem tampering.
- This milestone runs only `list_files`, `search_files`, and `read_file`. Do not execute editing, shell commands, or tests requested by the model.
- Execute multiple read requests sequentially. Show each tool's actual result or error. After Task 6, feed results back to the model; before then, do not claim the model has used them.
- Limit read and search output to 64 KiB; report truncation. List at most 200 entries. Reject absolute paths, parent traversal, and links resolving outside the workspace.
- Search file contents by case-insensitive literal substring; return matching paths, one-based line numbers, and snippets. No matches is a normal result. Skip `.git`, `.venv`, `node_modules`, caches, binary files, and symlinks during recursive search. Semantic search and indexing are out of scope.
- When creating copies, omit `.git`, `.venv`, `node_modules`, caches, and generated `instance` data; preserve challenge source, instructions, and tests. Reject template symlinks rather than following links outside the template.
- The model loop accepts at most 5 model calls and 10 tool calls per prompt. Stop with an explicit limit message when exceeded. These are prototype defaults, not product prompt quotas.
- No production multi-user security claims; Docker workspace isolation precedes future command execution.

## Files

- Create `src/coding_agent/workspace.py`: create a copy, check paths, and perform bounded listing, reading and searching.
- Modify `src/coding_agent/tools.py`: keep existing LangChain schemas and add a dispatcher for the three supported operations; report other tools as not implemented.
- Modify `src/coding_agent/graph.py`: execute validated calls using an explicitly supplied workspace; Task 6 adds message history and a bounded model/tool loop.
- Modify `src/coding_agent/main.py`: create a workspace for an accepted prompt, pass it to the graph, and display the workspace and tool results.
- Modify `.gitignore` and `README.md`: ignore runtime copies and explain setup, behavior, cleanup and limitations.
- Add `tests/test_workspace.py`; update `tests/test_tools.py`, `tests/test_graph.py`, and `tests/test_main.py`.

## Task 1: Independent local workspace

**Interface:** `create_workspace(template: Path, runtime_dir: Path) -> Path` in `workspace.py`. Return a newly created workspace path; fail clearly if the template is missing. Copy the challenge files, not the agent directory or its credentials. Keep workspace copies after the run for inspection; document their location and manual cleanup.

- [ ] Write a test creating two workspaces from a small temporary template. Change a file in one copy and assert the second copy and template remain unchanged; assert the two paths differ.
- [ ] Check excluded dependency, cache, Git, and instance directories are not copied; check a template symlink is rejected.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_workspace.py -q` and confirm it fails because the workspace function is missing.
- [ ] Implement the smallest copy function using standard-library utilities and add `.runtime/` to `.gitignore`.
- [ ] Run the test again and confirm it passes. Test a missing template produces a clear error.

## Task 2: Safe, bounded read operations

**Interfaces:** `resolve_workspace_path(workspace: Path, path: str) -> Path`; `list_files(workspace: Path, path: str) -> str`; `read_file(workspace: Path, path: str) -> str`; `search_files(workspace: Path, query: str, path: str) -> str` in `workspace.py`.

- [ ] Write tests using real temporary files for directory listing, text reading, case-insensitive literal search matches with file names and line numbers, excluded directories, and no matches.
- [ ] Add tests rejecting absolute paths, `..`, a symlink that escapes the workspace, missing paths, binary or invalid UTF-8 files, and empty search queries. Skip the symlink test only if the OS does not permit creating one.
- [ ] Add tests proving long file or search output is capped at 64 KiB and labelled truncated, and listing is capped at 200 entries with a truncation notice.
- [ ] Run the tests and confirm the missing operations fail. Implement the functions with `pathlib`; skip unreadable and binary files during recursive search and return a clear error for a direct read.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_workspace.py -q` and confirm all cases pass.

## Task 3: Dispatch actual tool requests

**Interface:** `execute_tool_call(workspace: Path, call: dict) -> dict` in `tools.py`; return the validated call ID, name, arguments, status (`completed`, `error`, or `not implemented`), and result text.

- [ ] Write tests dispatching each read tool against a temporary workspace, reporting an invalid path as an error, rejecting an unknown or malformed call, and leaving `edit_file`, `run_command`, and `run_tests` unexecuted.
- [ ] Run the tool tests and confirm the new dispatcher tests fail. Implement dispatch using the existing validation and Task 2 operations; process each request separately so one failed call is reported.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_tools.py -q` and confirm all tests pass. Keep the existing LangChain tool argument schemas unchanged.

## Task 4: Connect the graph and terminal

**Interface:** `build_graph(model, jev_checker=None, workspace=None)`; the graph executes tool calls only when a workspace is provided. `main()` creates a workspace from the configured initial challenge path and displays real results.

- [ ] Write fake-model tests for a plain answer, one read request, multiple sequential requests, a rejected path, a placeholder request, invalid tool inputs, and Jev failure. Assert model invocation occurs once and tool call IDs are preserved.
- [ ] Write a terminal test proving the workspace path and actual tool result are shown, and a workspace-creation failure stops with a clear message.
- [ ] Run graph and terminal tests and confirm new cases fail. Implement the graph and terminal changes; preserve existing behavior when no workspace is supplied.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_graph.py tests/test_main.py -q` and confirm all tests pass.

## Task 5: Verify the read-only foundation

- [ ] Add a fake-model end-to-end test that asks for a known file from a disposable template, verifies the displayed file content, and confirms the template remains unchanged. This test requires no network or keys.
- [ ] Update the README with the terminal command, workspace location, what happens for an unavailable tool, cleanup instructions, and the current local-only security limitation.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q` and record the actual result. Optionally try a real configured free model in a fresh workspace; report rate limits or unexpected model choices honestly.

## Task 6: Feed tool results back to the model

**Files:** `src/coding_agent/graph.py`, `src/coding_agent/main.py`, `tests/test_graph.py`, `tests/test_main.py`, `README.md`.

**Interface:** Keep `build_graph(model, jev_checker=None, workspace=None)`. When a workspace is provided, state carries LangChain messages, model-call and tool-call counts, tool results, and the final answer. Add a tool execution node and conditional edges between the model and tool nodes.

- [ ] Write a fake-model test: first request `search_files` for a term with no matches, then request a related term, then `read_file` on the match, then return an answer. Assert each model call receives all earlier assistant messages and matching `ToolMessage` results with correct IDs.
- [ ] Write tests for a normal answer without tools, multiple calls in one model response, one failing read among successful calls, unimplemented edit/command requests, malformed calls, Jev failure, and model failure. Errors and unimplemented results must be visible to the model; preserve every tool-call/result pair.
- [ ] Write tests for the 5-model-call and 10-tool-call limits. Stop with a clear incomplete status when either limit would be exceeded; never present a limit stop as a completed fix.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_graph.py tests/test_main.py -q` and confirm the new tests fail for the expected missing loop.
- [ ] Implement the bounded sequential loop and terminal progress output. Update the system message to distinguish working read tools from unavailable edit, command, and test tools.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q` and confirm all tests pass. Update the README to explain the loop, limits, and that file contents sent to the model provider become part of its context.

## Review focus

- Missing challenge template or runtime directory: show a clear failure, never fall back to the original for writes.
- Large, binary, inaccessible, or non-UTF-8 files: bound output and report or skip as specified.
- Windows paths, `..`, and links escaping the workspace: reject them, including cross-drive paths.
- Multiple tool calls or one bad call: retain IDs, process sequentially, and show each actual outcome.
- Requested edit or command: report not implemented; never run it on the host.

## Later milestones

1. **Isolated execution:** Create a fresh container per attempt, with the copied challenge, no controller credentials or Docker socket, limited resources, no outbound network, command timeout and bounded output. Add editing, commands and tests only inside that container. Verify cleanup and independence of two sessions.
2. **Multi-user platform:** Add authenticated attempt ownership and stronger isolation appropriate for untrusted users before exposing execution publicly. Prompt limits, usage accounting, evaluation and IDE integration are separate later work.

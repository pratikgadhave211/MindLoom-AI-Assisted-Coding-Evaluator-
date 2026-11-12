# Coding Agent: Phase 1 Plan

**Goal:** From a terminal, accept a prompt, check it with Jev, call a free OpenRouter model using LangChain, and show any tools the model asks to use. Tool handlers are placeholders; they do not access files or execute commands.

**Approach:** Use a small LangGraph workflow with ordinary Python functions. Use LangChain's OpenRouter integration and tool descriptions. Keep the code understandable to a beginner; add short comments for the purpose of each major section, and explain any necessary Python type annotations in the README.

**Framework references:** [LangGraph workflows](https://docs.langchain.com/oss/python/langgraph/graph-api), [OpenRouter LangChain integration](https://openrouter.ai/blog/tutorials/langchain-chatopenrouter-setup/), [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling).

## User-visible flow

```text
Enter prompt → validate → Jev advisory check → ask the model → show answer/tool requests → stop
```

An empty or oversized prompt stops at validation. A model response can be an ordinary answer, one tool request, or several tool requests; we show what it actually returned. Tool names and arguments are validated before display. A selected tool is shown as `not implemented`—never as a successful read, edit, or command.

## Folder structure to create during implementation

```text
coding-agent/
├── IMPLEMENTATION_PLAN.md       # Earlier full-system draft
├── PHASE_1_PLAN.md              # This plan
├── pyproject.toml               # Python dependencies and test settings
├── README.md                    # Setup, explanation, and examples
├── src/coding_agent/
│   ├── __init__.py
│   ├── main.py                  # Terminal input and output
│   ├── config.py                # Model and API-key configuration
│   ├── sanity.py                # Check prompt text
│   ├── jev.py                   # Advisory prompt check with TypeSafe Jev
│   ├── tools.py                 # Tool names, descriptions, and placeholders
│   ├── model.py                 # LangChain/OpenRouter model setup
│   └── graph.py                 # LangGraph nodes and workflow
└── tests/
    ├── test_sanity.py
    ├── test_jev.py
    ├── test_tools.py
    └── test_graph.py
```

## What each file does

- `config.py`: `load_config()` checks `OPENROUTER_API_KEY` and the model name without printing the key. Default to `openrouter/free`; allow a configurable `:free` model. Do not configure paid model fallbacks. Explain that `openrouter/free` can route to different models and that a tool-capable endpoint is required.
- `sanity.py`: `check_prompt(text)` removes surrounding whitespace and returns a clear error for empty text or input over the configurable 12,000-character prototype limit.
- `jev.py`: `check_with_jev(prompt, api_key)` asks TypeSafe Jev for an advisory score on whether the prompt concerns software development. It does not block the model. Missing keys or failed checks are shown as unavailable.
- `tools.py`: define LangChain tools with short descriptions and simple inputs: `list_files(path)`, `search_files(query, path)`, `read_file(path)`, `edit_file(path, changes)`, `run_command(command)`, `run_tests()`. If a placeholder is invoked during an explicit test, it returns `not implemented` and has no side effects. Phase 1 only displays requests and does not invoke these handlers.
- `model.py`: `make_model(config, tools)` creates a LangChain OpenRouter chat model and binds the tool definitions. Use `langchain-openrouter` if a compatible pinned release works; verify it against the provider docs during implementation. Map unavailable model, rate limit, timeout and missing tool support to understandable errors.
- `graph.py`: `build_graph(model)` assembles the LangGraph nodes `check_prompt`, `ask_model`, and `show_result`. Graph state holds the prompt, answer, requested tools and any error. A conditional edge stops invalid prompts before the model node. `show_result` validates and displays every tool call rather than assuming the model returns exactly one. One model call per prompt in this phase.
- `main.py`: collect one prompt, run the graph, and print a direct answer or the requested tool names and arguments, with `not executed` next to each. Do not print API keys or raw provider errors that contain credentials.
- `tests/`: use fake models and local inputs so the default tests do not need internet, an API key, Docker, or a workspace.

## Tasks and checks

1. **Setup.** Add `langchain`, `langgraph`, `langchain-openrouter` and `pytest` through the Python project configuration. Pin compatible versions after checking the actual installation. Add only the configuration needed for this phase.
2. **Sanity checks.** Test empty, whitespace-only, oversized, and valid input. A rejected prompt must not call the model.
3. **Tool definitions.** Test that all six descriptions have the expected simple input fields and that placeholder handlers never perform I/O.
4. **Model connection.** Configure `ChatOpenRouter` with `bind_tools`; keep network access behind a small model function so tests can replace it with a fake. Preserve returned tool IDs and validate malformed or unknown calls.
5. **Graph and CLI.** Use `StateGraph` with the three named nodes. Test a plain text answer, one tool call, multiple calls, invalid tool arguments, and a model error. Display actual output without claiming a placeholder ran successfully.
6. **Verify.** Run `python -m pytest -q` offline. Only when a real key is available, run a separate live smoke test using a confirmed tool-capable free model and record which tool it selected. A model can choose the wrong tool or no tool; report the observed result instead of claiming guaranteed correctness.

## Later phases

- **Phase 2:** Add real list/search/read tools using a disposable challenge workspace.
- **Phase 3:** Add file edits and command/test execution within an isolated workspace.
- **Phase 4:** Extend the graph to feed tool results and conversation history back to the model; add sequential/parallel scheduling, cancellation, a checker, and loop limits.
- **Phase 5:** Add persistent prompt limits, token usage when available, and eventual IDE integration. Evaluation and scoring are separate later work.

Defaults such as the prompt size are implementation proposals, not fixed product rules. An OpenRouter user prompt may result in multiple API calls in later phases, so API rate limits and the user's prompt limit are separate.

## Implementation status

The Phase 1 files and a local Python environment have been created. Jev is an advisory step before the coding model; a low score or Jev error does not block the prompt. A live sample returned a Jev score and a `read_file` request without executing the tool. The local `.venv` uses already-installed system packages; the README describes how to create a fresh environment on another machine.

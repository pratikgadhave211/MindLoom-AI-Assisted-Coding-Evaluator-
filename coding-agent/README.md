# Coding Agent — Isolated Workspace Prototype

This version checks a prompt with Jev and lets an OpenRouter, Groq, or NVIDIA model list, search, read, and edit files and run commands and tests in a separate Docker workspace.

## Setup on Windows PowerShell

From this folder, with Python 3.11 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Set `OPENROUTER_API_KEY` and optionally `TYPESAFE_API_KEY` in the local `.env` file or in your environment. Environment variables take priority. Never commit the keys or paste them into a prompt. The default model is `openrouter/free`; optionally set `OPENROUTER_MODEL` to a specific free model ID ending in `:free`.

To use Groq instead, set these values in `.env`:

```text
MODEL_PROVIDER=groq
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=openai/gpt-oss-120b
```

The Groq model value is optional and defaults to `openai/gpt-oss-120b`. Groq hosts the model and its free plan has account-specific limits. To switch back, set `MODEL_PROVIDER=openrouter`. Restart the agent API after changing providers.

To use NVIDIA Nemotron, set `MODEL_PROVIDER=nvidia` and `NVIDIA_API_KEY` in `.env`. The default is `nvidia/nemotron-3-ultra-550b-a55b`; `NVIDIA_MODEL` can override it. The NVIDIA-hosted API has its own account and usage limits.

## Conversation memory

The agent uses LangGraph's PostgreSQL checkpointer to save conversation messages and graph state. The database also stores the workspace volume name for each conversation; repository files and installed dependencies stay in Docker volumes, not PostgreSQL.

Set `POSTGRES_PASSWORD` and `CHECKPOINT_DATABASE_URL` in `.env`. For the provided Compose setup, the local URL has the form `postgresql://agent:YOUR_PASSWORD@127.0.0.1:15432/agent_checkpoints`. Use the same password in both settings, keep it private, and do not change it for an existing database volume without updating PostgreSQL separately.

Start Docker Desktop, then start the checkpoint database:

```powershell
docker compose up -d --wait
```

Run the agent normally for a new conversation. It prints a `Conversation ID` and accepts one prompt. To continue with the same history and workspace in a later run, copy the printed ID:

```powershell
python -m coding_agent.main --thread-id YOUR_CONVERSATION_ID
```

Keep the PostgreSQL volume and the printed workspace volume to retain the conversation and its files. `docker compose down` stops the database without deleting its volume; do not add `-v` if you want to keep memory. Checkpoints can contain prompts, model responses, tool inputs, and tool output, so protect access to the database.

If a prior turn was interrupted while tools were pending, the agent records their outcome as unknown and lets the model inspect the saved workspace on the next prompt. It does not blindly replay those tools. This local setup is not yet user authentication or a multi-user production service.

As a prototype limit, the agent stops before another model call if serialized conversation history exceeds 200,000 UTF-8 bytes. This is not a token count; a model may have a smaller context limit. The agent does not silently delete old messages.

When the TypeSafe key is set, the user's prompt is sent to Jev to score whether it relates to software development. The score is advisory: the prompt still goes to the coding model, including when Jev is unavailable. Jev and the chosen model provider receive the prompt.

## LangSmith tracing

Set `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY`, and `LANGSMITH_PROJECT` in `.env` to send the graph, model calls, and workspace tool calls to LangSmith. For example, the project name can be `agentic ide tracing`. The agent reads these settings from `.env`; process environment variables take priority. Set `LANGSMITH_TRACING=false` to turn tracing off. Keep the API key private.

Each requested tool appears under its own name, such as `read_file` or `run_tests`, in the workflow trace. Multiple tools in one model response still run one at a time.

Traces can contain prompts, model messages, tool inputs and outputs, repository contents, and command output. Only enable tracing for content you are allowed to send to your LangSmith workspace. The test suite disables live tracing and does not send test data to LangSmith.

The predictometer evidence collector records newly accepted prompts, tool names and paths, editor saves, and terminal openings by attempt. Older tool-limit events remain in saved history. A repeated request ID is counted once, including across chats and reopening. The collector does not backfill older attempts, track unsaved editor drafts, or reliably identify file changes made through the terminal or agent commands; these activities make the evidence incomplete. Evidence records do not contain file contents. The prompt limit is not enforced.

`predictometer_rules.py` looks for a relevant file read, changes to expected files, configured literal text added by a change, and historical tool-limit events. It does not consume test results. File paths and text matches are clues rather than correctness checks; an alternative valid fix may not match. `predictometer.py` combines at least two available, current signals using provisional weights; the resulting score is not a calibrated probability. The IDE refreshes the experimental score through the attempt-scoped API.

When a Jev key is configured, the agent starts a background assessment after each accepted turn and after an editor save or terminal disconnect when a saved chat prompt exists. One request asks separately about the prompt direction and the code, using the prompt counter, challenge guidance, original code, reference patch and current workspace files. Results are stored against the prompt's turn; older results do not replace newer prompts, and later recorded edits mark the code result stale until refreshed. This request is separate from the existing Jev coding-request sanity check. The local challenge's 10-prompt limit is an example, not an enforced limit. The hosted provider receives the user prompt, relevant code and author guidance; review its data handling for real challenges. No cross-encoder is connected.

## Submitting a challenge

After entering the API token, select **Secure, searchable blog posts** from the challenge list to open a new workspace. Existing workspaces retain their original challenge; choose **Continue previous workspace** to reopen the latest one. Open the challenge panel for the full question. Save editor drafts and disconnect the terminal before pressing **Submit**. The authenticated `GET /challenges` endpoint supplies the list.

Submission freezes a separate Docker volume, runs visible tests without network access, and runs behavior checks from a separate checker container on an internal Docker network. The report shows correctness separately from AI-assisted process feedback. Visible tests are candidate-controlled and are identified as such. A test environment failure is reported as unavailable, not a failed solution. A repeated submission request ID refers to the same submission. If the API is interrupted, an unfinished submission is marked interrupted when the attempt reopens; create a new submission to retry.

The first judge integration supports `MODEL_PROVIDER=nvidia` with `nvidia/nemotron-3-ultra-550b-a55b`. It uses a conservative 8,192-token window and NVIDIA's matching tokenizer to choose sequential batch sizes; the tokenizer is loaded from the local Hugging Face cache and is not downloaded automatically. Install the project dependencies and download the tokenizer once if needed:

```powershell
python -c "from huggingface_hub import hf_hub_download; hf_hub_download('nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-NVFP4', 'tokenizer.json')"
```

The judge sends the challenge, example reference patch, submitted code diff, selected chat events and behavior outcomes to NVIDIA. Judge tracing is disabled to avoid sending the reference to LangSmith. A missing tokenizer, unsupported model, invalid response or provider error leaves process feedback unavailable; correctness results remain available. Token statistics show only provider-reported usage and can be partial. Tool output and terminal activity are not completely captured, and the report cannot reliably attribute every line to the user or agent.

Snapshots are retained in Docker volumes named `coding-agent-submission-<id>` so they can be associated with saved reports. Remove a snapshot only after confirming the corresponding report is no longer needed. The bundled reference and behavior checks are local development examples stored in this repository, so they are not secret. Production assessments require private challenge storage, stronger isolation and independent security review; Docker and the single local API token do not provide multi-user security.

```powershell
python -m coding_agent.main
```

Start Docker Desktop before running the agent. The workspace image was built from the existing local `agentic_ide_evaluator-code-server:latest` image, which already has Python, Flask and pytest. To rebuild it after runner changes:

```powershell
docker build -f docker/Dockerfile.workspace -t coding-agent-workspace:latest .
```

Enter a prompt such as `Inspect and fix the authorization bug in the project`. For a new conversation the program creates a fresh attempt workspace; with `--thread-id` it reopens that conversation's saved workspace. It prints the Docker volume name, tool results, and model answer. Each run accepts one prompt.

Free models have request limits and availability can change. The default `openrouter/free` router can choose different models, and not every free model supports tool calling. A live request needs a valid OpenRouter key and an available tool-capable free model.

## Run tests without a key

```powershell
python -m pytest -q
```

Most tests use simulated model responses and do not make network requests. The opt-in package installation test downloads small packages. The small `AgentState` type in `graph.py` lists the information passed between those steps.

## Current flow

```text
Prompt → check → Jev → model → workspace tools → model → answer
```

The model may repeat the tool step. There is no separate tool-call limit, but the agent still stops after at most 25 model calls per prompt. Search checks text in files without caring about letter case; it does not use semantic indexing. Search reports when it skips files larger than 1 MiB. Tool results, including file contents, are sent to the selected model provider as context.

Each conversation uses a separate Docker volume and temporary container. The container is removed after the run; its named volume is retained for inspection and continuation. The original template in `../broken-repos/broken-flaskr-blog` stays unchanged. To inspect an attempt, replace `VOLUME_NAME` with the exact name printed by the agent:

```powershell
docker run --rm -it --network none --read-only -w /workspace/challenge --mount type=volume,source=VOLUME_NAME,target=/workspace/challenge,readonly --entrypoint sh coding-agent-workspace:latest
```

To delete only that attempt's volume after review, use `docker volume rm VOLUME_NAME`. Deleting a volume prevents that saved conversation from reopening its workspace. Be careful to select the intended name. Previous Phase 2 copies may still be in `.runtime/workspaces/`.

Workspace containers have outbound network access, no host project mount, and a 120-second command timeout with bounded output. A timeout stops the whole attempt. Python packages installed using `pip` go into `.agent-deps/python` in that workspace volume and are available to both the agent and terminal. npm installs use the project's usual `node_modules`; its cache is in `.agent-deps/npm-cache`. The dependency folder is hidden from the explorer and search. Reopen an existing workspace to use the updated image and network settings.

Pip is configured to replace existing target-folder packages when installing, so version changes take effect. This can upgrade a package on a repeated install. Editable installs and packages that rely on `.pth` startup files are not supported by this target-folder setup; use a project virtual environment for those cases.

Docker has memory, CPU, and process limits; volume disk usage is not limited by this prototype. Network access is not restricted to package registries: the shared Docker bridge may also reach other workspace containers and host services. Docker containers alone are not a sufficient security boundary for a public multi-user platform.

Docker integration tests are opt-in because they create disposable containers and volumes:

```powershell
$env:AGENT_DOCKER_TEST='1'
python -m pytest tests/test_docker_integration.py -q
```

To test real package downloads using temporary workspaces, set `AGENT_NETWORK_TEST=1` and run `python -m pytest tests/test_workspace_packages.py -q`.

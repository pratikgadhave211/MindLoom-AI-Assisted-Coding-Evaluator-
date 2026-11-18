# Mindthread

**AI-Assisted Coding Evaluator**

Mindthread is a local prototype for exploring how developers work with an AI coding agent. A user opens a broken project in a browser IDE, works on it with the agent, and can inspect the agent's tool activity. The planned evaluation layer will assess the submitted solution and provide evidence-based feedback on how the user guided and verified the agent.

> **Status:** The IDE, coding agent, workspace tools, and chat history are prototypes. Submission scoring, an AI judge, and the evaluation report are planned; they are not implemented yet.

## What works today

- Browser IDE with a file explorer, editor, terminal, and agent chat.
- Coding agent built with LangChain and LangGraph. It can list, search, read, and edit files, run commands, and run Python tests in its workspace.
- Workspace copies stored in Docker volumes. New chats have separate conversation histories but share the same workspace for that attempt.
- PostgreSQL-backed conversation checkpoints and saved chat events.
- Tool progress and occasional model-generated updates in the chat when the model provides them.
- Optional Jev prompt checks and LangSmith tracing. Model providers include NVIDIA, Groq, and OpenRouter.

## Architecture

```text
Browser IDE ──→ Agent API ──→ LangGraph ──→ Model provider
                   │              │
                   │              └── Workspace tools ──┐
                   │                                    ↓
                   ├── File API and terminal ──→ Docker workspace
                   │                                    │
                   └── PostgreSQL                 Docker volume
                       chat and checkpoints       files and packages
```

Workspace files and installed dependencies live in Docker volumes, not PostgreSQL. The current prototype uses the broken Flaskr blog in `broken-repos/broken-flaskr-blog` as its challenge template.

## Project layout

```text
mindthread/
├── coding-agent/          # Agent, FastAPI service, tools and tests
├── cloud-ide-reference/   # Browser IDE and its source repository
├── broken-repos/          # Challenge templates
├── challenge-sources/     # Upstream sources and challenge author notes
├── docs/                  # Project notes and plans
└── Dockerfile.code-server # Base for the local workspace image
```

## Local setup

The commands below are for Windows PowerShell. You need Docker Desktop, Python 3.11 or newer, Node.js and npm, and an API key for a supported model provider. Start Docker Desktop before building images or starting the database.

### 1. Install dependencies

From the project root:

```powershell
cd coding-agent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"

cd ..\cloud-ide-reference
npm install --workspace client
```

### 2. Configure the agent

Create `coding-agent/.env` locally. For example, to use NVIDIA:

```dotenv
MODEL_PROVIDER=nvidia
NVIDIA_API_KEY=your-nvidia-api-key
NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b

AGENT_API_TOKEN=choose-a-long-random-local-token
POSTGRES_PASSWORD=choose-a-local-database-password
CHECKPOINT_DATABASE_URL=postgresql://agent:choose-a-local-database-password@127.0.0.1:15432/agent_checkpoints

LANGSMITH_TRACING=false
```

Replace the placeholders. The two PostgreSQL password values must match; URL-encode special characters in the database URL if necessary. Environment variables take priority over `.env` values. `AGENT_API_TOKEN` is the local token you enter in the IDE. Optional `TYPESAFE_API_KEY` enables Jev checks; LangSmith also needs `LANGSMITH_API_KEY` and `LANGSMITH_PROJECT` when tracing is enabled.

For Groq, use `MODEL_PROVIDER=groq` and `GROQ_API_KEY`. For OpenRouter, use `MODEL_PROVIDER=openrouter` and `OPENROUTER_API_KEY`. See [coding-agent/README.md](coding-agent/README.md) for model settings. Provider availability, limits, and charges depend on the account and model.

### 3. Build the workspace image

From the project root:

```powershell
docker build -f Dockerfile.code-server -t agentic_ide_evaluator-code-server:latest .
cd coding-agent
docker build -f docker/Dockerfile.workspace -t coding-agent-workspace:latest .
```

The first image provides the workspace runtime; the second adds the agent's workspace runner and dependencies. Existing containers must be reopened to use a rebuilt image.

### 4. Start the database and agent API

In `coding-agent`:

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m uvicorn coding_agent.api:app --host 127.0.0.1 --port 8000
```

### 5. Start the IDE

In a second PowerShell terminal:

```powershell
cd "<project-root>\cloud-ide-reference\client"
..\node_modules\.bin\vite.cmd --port 5174 --strictPort
```

Open [http://localhost:5174](http://localhost:5174) and enter the `AGENT_API_TOKEN` from `coding-agent/.env`. The IDE will create or reopen the attempt associated with that browser tab. Save editor changes and disconnect the terminal before asking the agent to work.

The Cloud IDE repository also contains a legacy Node server. It is not required for the challenge workspace flow above; its terminal endpoint can start a host shell, so do not expose it to an untrusted network.

## Tests

From `coding-agent`, run the regular tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The Docker and PostgreSQL integration tests are opt-in. See [coding-agent/README.md](coding-agent/README.md) for their environment flags and package installation tests. The frontend's focused tests can be run from `cloud-ide-reference/client`:

```powershell
node --test src/agentStream.test.js src/workspaceApi.test.js
```

## Evaluation roadmap

The intended evaluator will collect attempt evidence, run tests on a submitted snapshot in a separate environment, and produce an explainable report. Planned dimensions include solution correctness, how a user frames and steers the task, and how they review and verify agent output. The judge and rubric need validation against human-reviewed examples before their scores can be considered reliable.

## Current limitations

- This is a local prototype, not a production multi-user assessment system. The API uses a shared local token rather than individual user authentication.
- Workspace containers use Docker's shared network bridge and can reach the network; separate volumes do not provide network isolation. Additional isolation is needed before running untrusted users' code publicly.
- Commands have a 120-second timeout, and workspace volume disk usage is not currently capped. Python target-folder installs do not support every editable-install or `.pth`-based package workflow.
- `run_tests` currently runs `python -m pytest -q`; it does not automatically select test commands for other project types.
- The agent limits each prompt to 25 model calls; there is no separate tool-call limit. Model availability, tool-call behavior, and progress messages are not guaranteed.
- The repository contains nested Git repositories. Before publishing, decide whether to keep them as separate repositories or include their source in one repository. `.gitignore` does not untrack files that are already tracked.

Never commit API keys, database passwords, local tokens, or private workspace data. Review tracked files and repository history before pushing.

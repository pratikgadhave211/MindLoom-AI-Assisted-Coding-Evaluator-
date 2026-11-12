# Local challenge workspace

This prototype connects the CloudIDE file explorer and editor to one coding-agent attempt. Docker Desktop and the coding-agent PostgreSQL service must be running.

From `coding-agent`:

```powershell
docker compose up -d --wait
.\.venv\Scripts\python.exe -m uvicorn coding_agent.api:app --host 127.0.0.1 --port 8000
```

In another PowerShell window, from `cloud-ide-reference`:

```powershell
npm run dev --workspace client
```

Open the local URL printed by Vite. Enter the `AGENT_API_TOKEN` value from `coding-agent/.env`; the token remains in the page's memory. The attempt ID is saved in the browser tab's session storage so the same attempt can reopen after a reload. Its files live in a Docker volume, not browser storage.

Select a file to open it. Use Ctrl+S or Save to write it. If the workspace file has changed since it was opened, saving fails and the editor keeps the draft open. Copy the draft elsewhere before reopening the file to compare it with the new version.

The coding agent panel uses the same attempt. Save all open changes before sending a prompt. The editor remains read-only until the agent finishes and the workspace is refreshed. If progress disconnects, reconnect to the existing turn; closing the page does not stop the agent. Conversation history is restored from PostgreSQL, while live tool progress is only retained for the current service run.

Select **Connect** in the terminal panel to open a real shell in the attempt workspace. Disconnect the terminal before saving editor changes or asking the agent to work. Disconnecting restarts the workspace container and stops terminal processes, including background servers; saved project files remain in the Docker volume. The terminal can run Python, Node and npm, but cannot download packages because the workspace has no network access. Use **Refresh files** to see terminal changes in the editor; unsaved drafts are kept.

The workspace is a local prototype and does not implement public multi-user authentication. Avoid sharing the local token.

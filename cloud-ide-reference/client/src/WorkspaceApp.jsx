import React, { useEffect, useRef, useState } from 'react';
import Sidebar from './components/Sidebar';
import CodeEditor from './components/CodeEditor';
import EditorTabs from './components/EditorTabs';
import AIPanel from './components/AIPanel';
import Terminal from './components/Terminal';
import { createWorkspaceApi, listWorkspace } from './workspaceApi';

export default function WorkspaceApp() {
  const [token, setToken] = useState('');
  const [attempt, setAttempt] = useState('');
  const [files, setFiles] = useState({});
  const [versions, setVersions] = useState({});
  const [openFiles, setOpenFiles] = useState([]);
  const [activeFile, setActiveFile] = useState(null);
  const [modified, setModified] = useState(new Set());
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [agentRunning, setAgentRunning] = useState(true);
  const [terminalOpen, setTerminalOpen] = useState(false);
  const filesRef = useRef(files);
  const openFilesRef = useRef(openFiles);
  const modifiedRef = useRef(modified);
  const savedContents = useRef({});
  const openingFiles = useRef(new Set());
  filesRef.current = files;
  openFilesRef.current = openFiles;
  modifiedRef.current = modified;

  useEffect(() => {
    const warn = event => {
      if (modified.size) event.preventDefault();
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [modified]);

  async function connect(event) {
    event.preventDefault();
    if (!token.trim() || busy) return;
    setBusy(true);
    setMessage('Opening the workspace...');
    const api = createWorkspaceApi(token.trim());
    try {
      let id = sessionStorage.getItem('workspace_attempt');
      if (id) {
        try {
          await api.list(id);
        } catch (error) {
          if (error.status !== 404) throw error;
          await api.resume(id);
        }
      } else {
        id = (await api.create()).attempt_id;
        sessionStorage.setItem('workspace_attempt', id);
      }
      const listing = await listWorkspace(api, id);
      setFiles(listing);
      setAttempt(id);
      setMessage('Choose a file to edit. Save with Ctrl+S.');
    } catch (error) {
      setMessage(error.message || 'Could not connect to the workspace.');
    } finally {
      setBusy(false);
    }
  }

  async function openFile(path) {
    if (agentRunning) return;
    if (openFiles.includes(path)) {
      setActiveFile(path);
      return;
    }
    if (openingFiles.current.has(path)) return;
    openingFiles.current.add(path);
    try {
      const result = await createWorkspaceApi(token.trim()).read(attempt, path);
      savedContents.current[path] = result.content;
      setFiles(previous => ({ ...previous, [path]: result.content }));
      setVersions(previous => ({ ...previous, [path]: result.version }));
      setOpenFiles(previous => previous.includes(path) ? previous : [...previous, path]);
      setActiveFile(path);
      setMessage('');
    } catch (error) {
      setMessage(error.message);
    } finally {
      openingFiles.current.delete(path);
    }
  }

  function editFile(path, content) {
    setFiles(previous => ({ ...previous, [path]: content }));
    setModified(previous => {
      const next = new Set(previous);
      if (content === savedContents.current[path]) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  async function saveFile(path) {
    if (!path || busy || agentRunning || terminalOpen) return;
    const content = filesRef.current[path];
    setBusy(true);
    try {
      const result = await createWorkspaceApi(token.trim()).save(attempt, path, content, versions[path]);
      savedContents.current[path] = content;
      setVersions(previous => ({ ...previous, [path]: result.version }));
      setModified(previous => {
        const next = new Set(previous);
        if (filesRef.current[path] === content) next.delete(path);
        else next.add(path);
        return next;
      });
      setMessage(`Saved ${path}`);
    } catch (error) {
      setMessage(`Could not save ${path}: ${error.message} Your edits are still open.`);
    } finally {
      setBusy(false);
    }
  }

  function closeFile(path) {
    if (modified.has(path) && !window.confirm('Discard unsaved changes to this file?')) return;
    setOpenFiles(previous => previous.filter(item => item !== path));
    setModified(previous => { const next = new Set(previous); next.delete(path); return next; });
    setFiles(previous => ({ ...previous, [path]: null }));
    if (activeFile === path) setActiveFile(null);
  }

  function canStartAgent() {
    if (busy || openingFiles.current.size) return 'Wait for the current file operation to finish.';
    if (terminalOpen) return 'Disconnect the terminal before asking the agent.';
    if (modifiedRef.current.size) return 'Save your open changes before asking the agent.';
    return '';
  }

  async function refreshWorkspace() {
    const api = createWorkspaceApi(token.trim());
    const listing = await listWorkspace(api, attempt);
    const contents = {};
    const freshVersions = {};
    for (const path of openFilesRef.current) {
      if (modifiedRef.current.has(path) || !(path in listing)) continue;
      const result = await api.read(attempt, path);
      if (modifiedRef.current.has(path)) continue;
      contents[path] = result.content;
      freshVersions[path] = result.version;
    }
    setFiles(previous => {
      const next = { ...listing };
      for (const path of openFilesRef.current) {
        if (modifiedRef.current.has(path)) next[path] = previous[path];
        else if (path in contents) next[path] = contents[path];
        else next[path] = previous[path];
      }
      return next;
    });
    Object.assign(savedContents.current, contents);
    setVersions(previous => ({ ...previous, ...freshVersions }));
    setMessage(modifiedRef.current.size ? 'Workspace refreshed. Unsaved drafts were kept.' : 'Workspace files refreshed.');
  }

  async function refreshFiles() {
    if (busy || agentRunning) return;
    setBusy(true);
    try { await refreshWorkspace(); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }

  if (!attempt) return (
    <main className="h-screen bg-ide-bg text-ide-text flex items-center justify-center p-6">
      <form onSubmit={connect} className="w-full max-w-md bg-ide-sidebar p-6 rounded-lg space-y-4">
        <h1 className="text-xl font-semibold">Open challenge workspace</h1>
        <p className="text-sm text-ide-textMuted">Enter AGENT_API_TOKEN from coding-agent/.env. It stays in this page's memory.</p>
        <input aria-label="Agent API token" type="password" value={token} onChange={event => setToken(event.target.value)}
          className="w-full p-2 bg-ide-bg border border-ide-border rounded" autoComplete="off" />
        <button disabled={busy} className="px-4 py-2 bg-ide-accent text-white rounded disabled:opacity-50">{busy ? 'Opening...' : 'Open workspace'}</button>
        {message && <p role="status" className="text-sm text-ide-textMuted">{message}</p>}
      </form>
    </main>
  );

  return (
    <main className="h-screen flex flex-col bg-ide-bg text-ide-text">
      <header className="h-12 px-4 flex items-center justify-between bg-ide-sidebar border-b border-ide-border">
        <span className="font-semibold">Cloud IDE · Challenge workspace</span>
        <div className="flex gap-3">
          <button onClick={refreshFiles} disabled={busy || agentRunning} className="px-3 py-1 rounded border border-ide-border disabled:opacity-50">Refresh files</button>
          <button onClick={() => saveFile(activeFile)} disabled={!activeFile || busy || agentRunning || terminalOpen} className="px-3 py-1 rounded bg-ide-accent text-white disabled:opacity-50">Save</button>
        </div>
      </header>
      <div className="flex flex-1 min-h-0">
        <aside className="w-64 shrink-0 border-r border-ide-border overflow-auto">
          <Sidebar files={files} activeFile={activeFile} onFileSelect={openFile} section="files" readOnly />
        </aside>
        <section className="flex flex-col flex-1 min-w-0">
          <EditorTabs openFiles={openFiles} activeFile={activeFile} onTabSelect={setActiveFile} onTabClose={closeFile} modifiedFiles={modified} />
          <div className="flex-1 min-h-0 flex flex-col">
            {activeFile ? <CodeEditor file={activeFile} content={files[activeFile] ?? ''}
              readOnly={agentRunning || busy} onChange={content => editFile(activeFile, content)} onSave={() => saveFile(activeFile)} />
              : <p className="p-6 text-ide-textMuted">Select a file from the explorer.</p>}
          </div>
          <Terminal token={token.trim()} attempt={attempt} agentRunning={agentRunning} onStateChange={setTerminalOpen} />
        </section>
        <AIPanel token={token.trim()} attempt={attempt} canStart={canStartAgent} onRunningChange={setAgentRunning} onFinish={refreshWorkspace} />
      </div>
      <footer role="status" className="min-h-8 px-4 py-1 text-xs bg-ide-sidebar border-t border-ide-border">{message || 'Workspace connected.'}</footer>
    </main>
  );
}

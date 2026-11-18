import React, { useEffect, useRef, useState } from 'react';
import Sidebar from './components/Sidebar';
import CodeEditor from './components/CodeEditor';
import EditorTabs from './components/EditorTabs';
import AIPanel from './components/AIPanel';
import Terminal from './components/Terminal';
import SubmissionReport from './components/SubmissionReport';
import { createWorkspaceApi, listWorkspace } from './workspaceApi';

export default function WorkspaceApp() {
  const [token, setToken] = useState('');
  const [challenges, setChallenges] = useState(null);
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
  const [question, setQuestion] = useState(null);
  const [submissionId, setSubmissionId] = useState('');
  const [submissionRunning, setSubmissionRunning] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [previousAttempt, setPreviousAttempt] = useState(() => sessionStorage.getItem('workspace_previous_attempt') || '');
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

  useEffect(() => {
    if (!attempt) return;
    let cancelled = false;
    setQuestion(null);
    setSubmissionId(sessionStorage.getItem(`submission-${attempt}`) || '');
    setReportOpen(false);
    createWorkspaceApi(token.trim()).question(attempt).then(result => {
      if (!cancelled) setQuestion(result);
    }).catch(() => { if (!cancelled) setMessage('Could not load the challenge question.'); });
    return () => { cancelled = true; };
  }, [attempt, token]);

  useEffect(() => {
    if (!attempt || !submissionId) { setSubmissionRunning(false); return; }
    let cancelled = false;
    let timer;
    async function checkSubmission() {
      try {
        const result = await createWorkspaceApi(token.trim()).submission(attempt, submissionId);
        if (cancelled) return;
        const running = ['preparing', 'running', 'testing', 'reviewing'].includes(result.status);
        setSubmissionRunning(running);
        if (running) timer = setTimeout(checkSubmission, 2500);
      } catch {
        if (!cancelled) { setSubmissionRunning(true); timer = setTimeout(checkSubmission, 5000); }
      }
    }
    setSubmissionRunning(true);
    checkSubmission();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [attempt, submissionId, token]);

  async function connect(event) {
    event.preventDefault();
    if (!token.trim() || busy) return;
    setBusy(true);
    setMessage('Loading challenges...');
    const api = createWorkspaceApi(token.trim());
    try {
      const result = await api.challenges();
      setChallenges(result.challenges);
      setMessage('Select a challenge to open its workspace.');
    } catch (error) {
      setMessage(error.message || 'Could not load challenges.');
    } finally {
      setBusy(false);
    }
  }

  async function openChallenge(challengeId, resume = false) {
    if (busy) return;
    setBusy(true);
    setMessage('Opening the workspace...');
    const api = createWorkspaceApi(token.trim());
    try {
      const oldId = sessionStorage.getItem('workspace_attempt');
      const id = resume ? oldId : (await api.create(challengeId)).attempt_id;
      if (!id) throw new Error('No previous workspace is available.');
      if (resume) {
        try { await api.list(id); }
        catch (error) { if (error.status !== 404) throw error; await api.resume(id); }
      } else if (oldId && oldId !== id) {
        sessionStorage.setItem('workspace_previous_attempt', oldId);
        setPreviousAttempt(oldId);
      }
      sessionStorage.setItem('workspace_attempt', id);
      const listing = await listWorkspace(api, id);
      savedContents.current = {};
      openingFiles.current.clear();
      setFiles(listing);
      setVersions({});
      setOpenFiles([]);
      setActiveFile(null);
      setModified(new Set());
      setAgentRunning(true);
      setAttempt(id);
      setMessage('Choose a file to edit. Save with Ctrl+S.');
    } catch (error) {
      setMessage(error.message || 'Could not connect to the workspace.');
    } finally {
      setBusy(false);
    }
  }

  async function openPreviousWorkspace() {
    if (busy || agentRunning || terminalOpen || modified.size) return;
    setBusy(true);
    try {
      const api = createWorkspaceApi(token.trim());
      const id = previousAttempt;
      try { await api.list(id); }
      catch (error) { if (error.status !== 404) throw error; await api.resume(id); }
      const listing = await listWorkspace(api, id);
      sessionStorage.setItem('workspace_previous_attempt', attempt);
      sessionStorage.setItem('workspace_attempt', id);
      setPreviousAttempt(attempt);
      savedContents.current = {};
      openingFiles.current.clear();
      setFiles(listing);
      setVersions({});
      setOpenFiles([]);
      setActiveFile(null);
      setModified(new Set());
      setAgentRunning(true);
      setAttempt(id);
      setMessage('Challenge workspace opened.');
    } catch (error) {
      setMessage(error.message || 'Could not open the challenge.');
    } finally {
      setBusy(false);
    }
  }

  async function submitChallenge() {
    if (busy || submissionRunning || agentRunning || terminalOpen || modified.size || question?.challenge_id !== 'flaskr-secure-search') return;
    setBusy(true);
    const key = `submission-request-${attempt}`;
    const requestId = sessionStorage.getItem(key) || crypto.randomUUID();
    sessionStorage.setItem(key, requestId);
    try {
      const result = await createWorkspaceApi(token.trim()).submit(attempt, requestId);
      sessionStorage.removeItem(key);
      sessionStorage.setItem(`submission-${attempt}`, result.submission_id);
      setSubmissionId(result.submission_id);
      setSubmissionRunning(['preparing', 'running', 'testing', 'reviewing'].includes(result.status));
      setReportOpen(true);
      setMessage('Submission started.');
    } catch (error) {
      if (error.status && error.status < 500) sessionStorage.removeItem(key);
      setMessage(error.message || 'Could not submit. Retry to check the same request.');
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

  if (!attempt && !challenges) return (
    <main className="h-screen bg-ide-bg text-ide-text flex items-center justify-center p-6">
      <form onSubmit={connect} className="w-full max-w-md bg-ide-sidebar p-6 rounded-lg space-y-4">
        <h1 className="text-xl font-semibold">Choose a challenge</h1>
        <p className="text-sm text-ide-textMuted">Enter AGENT_API_TOKEN from coding-agent/.env. It stays in this page's memory.</p>
        <input aria-label="Agent API token" type="password" value={token} onChange={event => setToken(event.target.value)}
          className="w-full p-2 bg-ide-bg border border-ide-border rounded" autoComplete="off" />
        <button disabled={busy} className="px-4 py-2 bg-ide-accent text-white rounded disabled:opacity-50">{busy ? 'Loading...' : 'View challenges'}</button>
        {message && <p role="status" className="text-sm text-ide-textMuted">{message}</p>}
      </form>
    </main>
  );

  if (!attempt) return (
    <main className="min-h-screen bg-ide-bg text-ide-text p-6">
      <div className="max-w-3xl mx-auto space-y-5">
        <h1 className="text-2xl font-semibold">Coding challenges</h1>
        <p className="text-sm text-ide-textMuted">Choose a question to open its isolated workspace and coding agent.</p>
        {challenges.length === 0 && <p>No challenges are available yet.</p>}
        {challenges.map(challenge => <button key={challenge.id} type="button" disabled={busy}
          onClick={() => openChallenge(challenge.id)} className="w-full text-left p-5 bg-ide-sidebar border border-ide-border rounded-lg disabled:opacity-50">
          <span className="block font-semibold text-lg">{challenge.title}</span>
          <span className="block mt-2 text-sm text-ide-textMuted">{challenge.summary}</span>
          <span className="block mt-3 text-sm text-ide-accent">Open challenge →</span>
        </button>)}
        {sessionStorage.getItem('workspace_attempt') && <button type="button" disabled={busy} onClick={() => openChallenge(null, true)}
          className="px-4 py-2 border border-ide-border rounded disabled:opacity-50">Continue previous workspace</button>}
        <button type="button" disabled={busy} onClick={() => { setChallenges(null); setMessage(''); }}
          className="ml-3 px-4 py-2 border border-ide-border rounded disabled:opacity-50">Change API token</button>
        {message && <p role="status" className="text-sm text-ide-textMuted">{message}</p>}
      </div>
    </main>
  );

  return (
    <main className="h-screen flex flex-col bg-ide-bg text-ide-text">
      <header className="h-12 px-4 flex items-center justify-between bg-ide-sidebar border-b border-ide-border">
        <span className="font-semibold">Cloud IDE · Challenge workspace</span>
        <div className="flex gap-3">
          <button onClick={() => setAttempt('')} disabled={busy || agentRunning || terminalOpen || modified.size > 0} className="px-3 py-1 rounded border border-ide-border disabled:opacity-50">Challenges</button>
          {previousAttempt && <button onClick={openPreviousWorkspace} disabled={busy || agentRunning || terminalOpen || modified.size > 0} className="px-3 py-1 rounded border border-ide-border disabled:opacity-50">Previous workspace</button>}
          <button onClick={refreshFiles} disabled={busy || agentRunning} className="px-3 py-1 rounded border border-ide-border disabled:opacity-50">Refresh files</button>
          <button onClick={() => saveFile(activeFile)} disabled={!activeFile || busy || agentRunning || terminalOpen} className="px-3 py-1 rounded bg-ide-accent text-white disabled:opacity-50">Save</button>
          {submissionId && <button onClick={() => setReportOpen(true)} className="px-3 py-1 rounded border border-ide-border">Report</button>}
          <button onClick={submitChallenge} disabled={busy || submissionRunning || agentRunning || terminalOpen || modified.size > 0 || question?.challenge_id !== 'flaskr-secure-search'}
            title={question?.challenge_id !== 'flaskr-secure-search' ? 'Start the new challenge before submitting.' : modified.size ? 'Save your changes before submitting.' : terminalOpen ? 'Disconnect the terminal before submitting.' : submissionRunning ? 'Wait for the current submission.' : ''}
            className="px-3 py-1 rounded bg-ide-accent text-white disabled:opacity-50">Submit</button>
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
        <AIPanel key={attempt} token={token.trim()} attempt={attempt} canStart={canStartAgent} onRunningChange={setAgentRunning} onFinish={refreshWorkspace} unsavedChanges={modified.size > 0} question={question} />
      </div>
      <footer role="status" className="min-h-8 px-4 py-1 text-xs bg-ide-sidebar border-t border-ide-border">{message || 'Workspace connected.'}</footer>
      {reportOpen && submissionId && <SubmissionReport token={token.trim()} attempt={attempt} submissionId={submissionId} onClose={() => setReportOpen(false)} />}
    </main>
  );
}

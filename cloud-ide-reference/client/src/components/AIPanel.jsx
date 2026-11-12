import React, { useEffect, useRef, useState } from 'react';
import { createWorkspaceApi } from '../workspaceApi';
import { appendTimelineEvent, streamTurn } from '../agentStream';

export default function AIPanel({ token, attempt, canStart, onRunningChange, onFinish }) {
  const [chats, setChats] = useState([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(true);
  const [listError, setListError] = useState('');
  const storageKey = `agent-chat-${attempt}`;

  async function refreshChats() {
    const items = await createWorkspaceApi(token).chats(attempt);
    setChats(items);
    return items;
  }

  useEffect(() => {
    let cancelled = false;
    refreshChats().then(items => {
      if (cancelled) return;
      const saved = sessionStorage.getItem(storageKey);
      setSelected(items.some(item => item.id === saved) ? saved : items[0]?.id || '');
    }).catch(problem => { if (!cancelled) setListError(problem.message); });
    return () => { cancelled = true; };
  }, [token, attempt]);

  function selectChat(id) {
    setBusy(true);
    sessionStorage.setItem(storageKey, id);
    setSelected(id);
  }

  async function newChat() {
    setBusy(true);
    setListError('');
    try {
      const chat = await createWorkspaceApi(token).createChat(attempt);
      setChats(items => [...items, chat]);
      selectChat(chat.id);
    } catch (problem) {
      setListError(problem.message);
      setBusy(false);
    }
  }

  return <aside className="w-80 shrink-0 flex flex-col bg-ide-sidebar border-l border-ide-border">
    <div className="p-3 border-b border-ide-border space-y-2">
      <div className="flex justify-between items-center"><h2 className="font-semibold">Coding agent</h2>
        <button type="button" disabled={busy} onClick={newChat} className="text-sm text-ide-accent disabled:opacity-50">+ New chat</button>
      </div>
      <select aria-label="Select chat" value={selected} disabled={busy} onChange={event => selectChat(event.target.value)}
        className="w-full p-1 bg-ide-bg border border-ide-border rounded text-sm disabled:opacity-50">
        {chats.map(chat => <option key={chat.id} value={chat.id}>{chat.title}</option>)}
      </select>
      {listError && <p role="alert" className="text-sm text-red-400">Could not load chats: {listError}. Reload to retry.</p>}
    </div>
    {selected && <ChatConversation key={selected} token={token} attempt={attempt} chat={selected}
      canStart={canStart} onRunningChange={onRunningChange} onBusyChange={setBusy}
      onOtherRunning={selectChat}
      onFinish={async () => { await onFinish(); await refreshChats(); }} />}
  </aside>;
}

function ChatConversation({ token, attempt, chat, canStart, onRunningChange, onBusyChange, onOtherRunning, onFinish }) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [turn, setTurn] = useState('');
  const cursor = useRef(0);
  const completed = useRef(false);
  const starting = useRef(false);
  const watching = useRef(false);
  const historyLost = useRef(false);
  const [pending, setPending] = useState(null);
  const pendingKey = `agent-request-${attempt}-${chat}`;

  async function watch(turnId) {
    if (watching.current) return;
    watching.current = true;
    setError('');
    try {
      if (!completed.current) {
        await streamTurn(token, attempt, turnId, cursor.current, event => {
          if (event.id) cursor.current = event.id;
          if (event.type === 'error' && event.message === 'Chat history could not be saved.') historyLost.current = true;
          setMessages(items => appendTimelineEvent(items, turnId, event));
          if (event.type === 'turn_finished') completed.current = true;
        }, chat);
      }
      await onFinish();
      const history = await createWorkspaceApi(token).chatHistory(attempt, chat);
      if (historyLost.current) setError('Some activity could not be saved. Copy anything you need before switching chats or reloading.');
      else setMessages(history.messages);
      setRunning(false);
      setTurn('');
      onRunningChange(false);
      onBusyChange(false);
    } catch (problem) {
      setError(problem.message || 'Connection lost. Reconnect to check the running turn.');
    } finally {
      watching.current = false;
    }
  }

  useEffect(() => {
    let cancelled = false;
    const saved = sessionStorage.getItem(pendingKey);
    if (saved) {
      try {
        const request = JSON.parse(saved);
        setPending(request);
        setLoading(false);
        submitRequest(request);
        return () => { cancelled = true; };
      } catch {
        sessionStorage.removeItem(pendingKey);
      }
    }
    createWorkspaceApi(token).chatHistory(attempt, chat).then(history => {
      if (cancelled) return;
      setLoading(false);
      setMessages(history.messages);
      if (history.workspace_busy && history.active_chat && history.active_chat !== chat) {
        onRunningChange(true);
        onOtherRunning(history.active_chat);
        return;
      }
      if (history.running_turn) {
        setRunning(true);
        onRunningChange(true);
        setTurn(history.running_turn);
        watch(history.running_turn);
      } else if (history.workspace_busy) {
        onRunningChange(true);
        setError('Another session is using this workspace. Reload after it finishes.');
      } else { onRunningChange(false); onBusyChange(false); }
    }).catch(problem => { if (!cancelled) setError(`Could not check the agent state: ${problem.message}. Reload to retry.`); });
    return () => { cancelled = true; };
  }, [attempt, token, chat]);

  async function submitRequest(request) {
    if (starting.current) return;
    starting.current = true;
    setRunning(true);
    onRunningChange(true);
    onBusyChange(true);
    setError('');
    cursor.current = 0;
    completed.current = false;
    let accepted = false;
    try {
      const api = createWorkspaceApi(token);
      const result = await api.startChatTurn(attempt, chat, request.prompt, request.id);
      accepted = true;
      setPrompt('');
      const history = await api.chatHistory(attempt, chat);
      sessionStorage.removeItem(pendingKey);
      setPending(null);
      if (historyLost.current) setMessages(items => [...items, { role: 'user', content: request.prompt }]);
      else setMessages(history.messages);
      if (history.workspace_busy && history.active_chat && history.active_chat !== chat) {
        onOtherRunning(history.active_chat);
      } else if (history.running_turn || result.status === 'running') {
        const activeTurn = history.running_turn || result.turn_id;
        setTurn(activeTurn);
        await watch(activeTurn);
      } else if (history.workspace_busy) {
        setError('Another session is using this workspace. Reload after it finishes.');
      } else {
        await onFinish();
        setRunning(false);
        onRunningChange(false);
        onBusyChange(false);
        if (result.status === 'interrupted') setError('The earlier request was interrupted. Check the workspace before sending again.');
      }
    } catch (problem) {
      if (!accepted && problem.status && problem.status < 500) {
        sessionStorage.removeItem(pendingKey);
        setPending(null);
        setPrompt(request.prompt);
        try {
          const history = await createWorkspaceApi(token).chatHistory(attempt, chat);
          if (history.active_chat && history.active_chat !== chat) {
            onOtherRunning(history.active_chat);
          } else if (history.running_turn) {
            setTurn(history.running_turn);
            setError(problem.message);
          } else if (history.workspace_busy) {
            setError('Another session is using this workspace. Reload after it finishes.');
          } else {
            setRunning(false);
            onRunningChange(false);
            onBusyChange(false);
            setError(problem.message);
          }
        } catch {
          setError('Could not confirm the workspace status. Reload after the API is available.');
        }
      } else {
        sessionStorage.setItem(pendingKey, JSON.stringify(request));
        setPending(request);
        setError('Could not confirm the request. Retry with the same request ID.');
      }
    } finally {
      starting.current = false;
    }
  }

  function send(event) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || starting.current || running || loading) return;
    const reason = canStart();
    if (reason) { setError(reason); return; }
    const request = { id: crypto.randomUUID(), prompt: text };
    sessionStorage.setItem(pendingKey, JSON.stringify(request));
    setPending(request);
    submitRequest(request);
  }

  return (
    <>
      <div className="flex-1 overflow-auto p-3 space-y-3" aria-live="polite">
        {messages.map((message, index) => <div key={index} className="text-sm whitespace-pre-wrap break-words">
          <strong>{message.role === 'user' ? 'You' : message.role === 'tool' ? 'Tool' : message.role === 'error' ? 'Error' : 'Agent'}: </strong>{message.content}
        </div>)}
        {running && <p className="text-xs text-ide-textMuted">Agent turn in progress. Closing this page does not stop it.</p>}
        {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        {pending && error && <button className="underline text-sm" onClick={() => submitRequest(pending)}>Retry request</button>}
        {running && turn && error && <button className="underline text-sm" onClick={() => watch(turn)}>Reconnect to progress</button>}
      </div>
      <form onSubmit={send} className="p-3 border-t border-ide-border space-y-2">
        <textarea aria-label="Agent prompt" value={prompt} onChange={event => setPrompt(event.target.value)}
          className="w-full p-2 bg-ide-bg border border-ide-border rounded text-sm" placeholder="Ask the agent about this project..." />
        <button disabled={loading || running || !prompt.trim()} className="px-3 py-1 rounded bg-ide-accent text-white disabled:opacity-50">Send</button>
      </form>
    </>
  );
}

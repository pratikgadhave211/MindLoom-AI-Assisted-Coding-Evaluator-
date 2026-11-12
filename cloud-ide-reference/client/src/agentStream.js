// Server events can arrive in pieces, so keep the unfinished part for later.
export function parseEvents(buffer) {
  const parts = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const remaining = parts.pop() || '';
  const events = [];
  for (const part of parts) {
    const data = part.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    if (data) events.push(JSON.parse(data));
  }
  return { events, remaining };
}

// The same event can arrive from saved history and again during reconnect.
export function appendTimelineEvent(items, turn, event) {
  const key = event.id == null ? '' : `${turn}:${event.id}`;
  if (key && items.some(item => item.event_key === key)) return items;
  let item;
  if (event.type === 'progress_update') item = { role: 'progress', content: event.message };
  else if (event.type === 'tool_started') item = { role: 'tool', content: `${event.name} started` };
  else if (event.type === 'tool_finished') item = { role: 'tool', content: `${event.name}: ${event.status}` };
  else if (event.type === 'answer') item = { role: 'assistant', content: event.message };
  else if (event.type === 'error') item = { role: 'error', content: event.message || 'The agent turn failed.' };
  else return items;
  return [...items, key ? { ...item, event_key: key } : item];
}

// The server may have accepted a request even if its response was lost.
export async function recoverTurnStart(api, attempt, refresh, chat) {
  const history = chat ? await api.chatHistory(attempt, chat) : await api.history(attempt);
  if (!history.running_turn && !history.workspace_busy) await refresh();
  return history;
}

export async function streamTurn(token, attempt, turn, after, onEvent, chat) {
  const chatPath = chat ? `/chats/${chat}` : '';
  const response = await fetch(`/agent-api/attempts/${attempt}${chatPath}/turns/${turn}/events`, {
    headers: { Authorization: `Bearer ${token}`, 'Last-Event-ID': String(after) }
  });
  if (!response.ok || !response.body) throw new Error('Could not connect to agent progress.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finished = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const parsed = parseEvents(buffer + decoder.decode(value, { stream: true }));
      buffer = parsed.remaining;
      for (const event of parsed.events) {
        onEvent(event);
        if (event.type === 'turn_finished') finished = true;
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (!finished) throw new Error('Agent progress disconnected. Reconnect to check the turn.');
}

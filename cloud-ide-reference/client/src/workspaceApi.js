// The API runs on the same computer; Vite forwards this path during development.
export function createWorkspaceApi(token, send = fetch) {
  async function request(path, options = {}) {
    const response = await send('/agent-api' + path, {
      ...options,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.detail || 'Workspace request failed.');
      error.status = response.status;
      throw error;
    }
    return data;
  }

  return {
    challenges: () => request('/challenges'),
    create: challengeId => request('/attempts', { method: 'POST', ...(challengeId ? { body: JSON.stringify({ challenge_id: challengeId }) } : {}) }),
    resume: attempt => request(`/attempts/${attempt}/resume`, { method: 'POST' }),
    question: attempt => request(`/attempts/${attempt}/question`),
    submit: (attempt, requestId) => request(`/attempts/${attempt}/submissions`, {
      method: 'POST', body: JSON.stringify({ request_id: requestId })
    }),
    submission: (attempt, submissionId) => request(`/attempts/${attempt}/submissions/${submissionId}`),
    history: attempt => request(`/attempts/${attempt}/history`),
    predictometer: attempt => request(`/attempts/${attempt}/predictometer`),
    chats: attempt => request(`/attempts/${attempt}/chats`),
    createChat: attempt => request(`/attempts/${attempt}/chats`, { method: 'POST' }),
    chatHistory: (attempt, chat) => request(`/attempts/${attempt}/chats/${chat}/history`),
    startChatTurn: (attempt, chat, prompt, requestId) => request(`/attempts/${attempt}/chats/${chat}/turns`, {
      method: 'POST', body: JSON.stringify({ prompt, request_id: requestId })
    }),
    startTurn: (attempt, prompt) => request(`/attempts/${attempt}/turns`, {
      method: 'POST', body: JSON.stringify({ prompt })
    }),
    list: (attempt, path = '.') => request(`/attempts/${attempt}/files?path=${encodeURIComponent(path)}`),
    read: (attempt, path) => request(`/attempts/${attempt}/file?path=${encodeURIComponent(path)}`),
    save: (attempt, path, content, version) => request(`/attempts/${attempt}/file`, {
      method: 'PUT', body: JSON.stringify({ path, content, expected_version: version })
    })
  };
}

export function parseListing(text) {
  if (text === 'Directory is empty.') return [];
  if (text.includes('[Listing truncated]')) throw new Error('Directory listing was truncated.');
  return text.split('\n').filter(Boolean).map(name => ({
    name: name.endsWith('/') ? name.slice(0, -1) : name,
    directory: name.endsWith('/')
  }));
}

export async function listWorkspace(api, attempt, path = '.', depth = 0) {
  if (depth > 20) throw new Error('Directory nesting is too deep.');
  const result = {};
  const listing = await api.list(attempt, path);
  for (const entry of parseListing(listing.entries)) {
    const child = path === '.' ? entry.name : `${path}/${entry.name}`;
    if (entry.directory) Object.assign(result, await listWorkspace(api, attempt, child, depth + 1));
    else result[child] = null;
  }
  return result;
}

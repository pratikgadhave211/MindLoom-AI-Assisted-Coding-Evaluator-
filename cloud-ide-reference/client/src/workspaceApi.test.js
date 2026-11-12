import test from 'node:test';
import assert from 'node:assert/strict';
import { createWorkspaceApi, listWorkspace, parseListing } from './workspaceApi.js';

test('listing keeps file and folder names separate', () => {
  assert.deepEqual(parseListing('flaskr/\nREADME.md\n'), [
    { name: 'flaskr', directory: true }, { name: 'README.md', directory: false }
  ]);
  assert.deepEqual(parseListing('Directory is empty.'), []);
  assert.throws(() => parseListing('a\n[Listing truncated]'), /truncated/i);
});

test('lists nested files using their workspace-relative paths', async () => {
  const api = { list: async (_attempt, path) => ({ entries: path === '.' ? 'app/\nREADME.md' : 'main.py' }) };
  assert.deepEqual(await listWorkspace(api, 'attempt'), { 'app/main.py': null, 'README.md': null });
});

test('save sends the version and reports a conflict', async () => {
  let request;
  const api = createWorkspaceApi('local-token', async (url, options) => {
    request = { url, options };
    return { ok: false, status: 409, json: async () => ({ detail: 'File has changed.' }) };
  });
  await assert.rejects(api.save('attempt', 'app.py', 'my edit', 'v1'), /changed/i);
  assert.equal(JSON.parse(request.options.body).expected_version, 'v1');
  assert.equal(request.options.headers.Authorization, 'Bearer local-token');
});

test('chat request carries the same request ID on retry', async () => {
  const requests = [];
  const api = createWorkspaceApi('token', async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ turn_id: 'turn', status: 'running' }) };
  });
  await api.startChatTurn('attempt', 'chat', 'fix login', 'request-id');
  await api.startChatTurn('attempt', 'chat', 'fix login', 'request-id');
  assert.deepEqual(requests, [
    { prompt: 'fix login', request_id: 'request-id' },
    { prompt: 'fix login', request_id: 'request-id' }
  ]);
});

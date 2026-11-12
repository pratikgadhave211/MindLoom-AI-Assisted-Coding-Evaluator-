import test from 'node:test';
import assert from 'node:assert/strict';
import { parseEvents, recoverTurnStart, appendTimelineEvent } from './agentStream.js';

test('stream parser keeps incomplete events and ignores keepalives', () => {
  const first = parseEvents(': keepalive\n\nid: 1\ndata: {"type":"tool_started","name":"read_file","id":1}\n\ndata: {"type":"ans');
  assert.equal(first.events[0].name, 'read_file');
  const second = parseEvents(first.remaining + 'wer","message":"done","id":2}\n\n');
  assert.equal(second.events[0].message, 'done');
  assert.equal(second.remaining, '');
});

test('an uncertain start refreshes the workspace when the turn already ended', async () => {
  let refreshed = false;
  const api = { history: async () => ({ running_turn: null, messages: [{ role: 'assistant', content: 'done' }] }) };
  const history = await recoverTurnStart(api, 'attempt', async () => { refreshed = true; });
  assert.equal(refreshed, true);
  assert.equal(history.messages[0].content, 'done');
});

test('an uncertain start follows the existing turn without launching another', async () => {
  const api = { history: async () => ({ running_turn: 'existing', messages: [] }) };
  const history = await recoverTurnStart(api, 'attempt', async () => { throw new Error('too early'); });
  assert.equal(history.running_turn, 'existing');
});

test('another chat using the workspace prevents a refresh', async () => {
  const api = { chatHistory: async () => ({ running_turn: null, workspace_busy: true, active_chat: 'other' }) };
  const history = await recoverTurnStart(api, 'attempt', async () => { throw new Error('too early'); }, 'chat');
  assert.equal(history.active_chat, 'other');
});

test('progress and tool events stay in order and do not duplicate on replay', () => {
  let items = [{ role: 'user', content: 'Find it' }];
  const events = [
    { id: 2, type: 'progress_update', message: 'Checking the file.' },
    { id: 3, type: 'tool_started', name: 'read_file' },
    { id: 4, type: 'tool_finished', name: 'read_file', status: 'completed' },
  ];
  for (const event of events) items = appendTimelineEvent(items, 'turn', event);
  items = appendTimelineEvent(items, 'turn', events[0]);
  assert.deepEqual(items.map(item => item.content), ['Find it', 'Checking the file.', 'read_file started', 'read_file: completed']);
  assert.equal(items[1].event_key, 'turn:2');
});

test('replayed events are deduplicated against restored history', () => {
  const history = [{ role: 'progress', content: 'Checking.', event_key: 'turn:5' }];
  assert.deepEqual(appendTimelineEvent(history, 'turn', { id: 5, type: 'progress_update', message: 'Checking.' }), history);
});

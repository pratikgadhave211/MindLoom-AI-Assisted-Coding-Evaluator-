import threading
from collections import deque
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
import psycopg
from psycopg.rows import dict_row
from langchain_core.messages import AIMessage, HumanMessage

from .agent import run_turn
from .config import load_config
from .container_workspace import start_workspace, stop_workspace, resume_workspace, run_workspace_tool, docker
from .memory import open_memory, get_workspace, save_workspace, ensure_original_chat, append_chat_event
from .diagnostics import log_error


class Turn:
    def __init__(self, chat_id=None, save=None):
        self.events = deque(maxlen=200)
        self.condition = threading.Condition()
        self.done = False
        self.next_id = 1
        self.chat_id = chat_id
        self.save = save
        self.status = 'running'

    def publish(self, event):
        with self.condition:
            event = dict(event, id=self.next_id)
            self.next_id += 1
            save_failed = False
            if self.save:
                try:
                    self.save(event)
                except Exception as error:
                    log_error('chat history error', error)
                    self.save = None
                    save_failed = True
            self.events.append(event)
            if save_failed:
                self.events.append({'id': self.next_id, 'type': 'error',
                                    'message': 'Chat history could not be saved.'})
                self.next_id += 1
            self.condition.notify_all()


class AttemptManager:
    def __init__(self):
        self.attempts = {}
        self.lock = threading.Lock()

    def create(self):
        return self._open(str(uuid4()), resume=False)

    def resume(self, attempt_id):
        return self._open(attempt_id, resume=True)

    def _chat_memory(self, attempt):
        if 'chat_memory' not in attempt:
            conn = psycopg.connect(attempt['config'].checkpoint_database_url, autocommit=True, row_factory=dict_row)
            attempt['chat_memory'] = SimpleNamespace(conn=conn)
        return attempt['chat_memory']

    def _open(self, attempt_id, resume):
        with self.lock:
            if attempt_id in self.attempts:
                raise ValueError("Attempt is already open.")
            config = load_config()
            if not config.checkpoint_database_url:
                raise ValueError("Checkpoint database is not configured.")
            memory_context = open_memory(config.checkpoint_database_url, attempt_id)
            memory = memory_context.__enter__()
            workspace = None
            try:
                volume = get_workspace(memory, attempt_id) if resume else None
                if resume and not volume:
                    raise KeyError(attempt_id)
                template = Path(__file__).resolve().parents[3] / "broken-repos" / "broken-flaskr-blog"
                workspace = resume_workspace(volume) if resume else start_workspace(template)
                if not resume:
                    save_workspace(memory, attempt_id, workspace.volume)
                chats_enabled = bool(memory.conn.execute('SELECT id FROM agent_chats WHERE id = %s',
                                                          (attempt_id,)).fetchone()) if resume else False
                if resume:
                    memory.conn.execute("UPDATE agent_requests SET status = 'interrupted' WHERE attempt_id = %s AND status = 'running'", (attempt_id,))
                self.attempts[attempt_id] = {"workspace": workspace, "memory": memory,
                    "memory_context": memory_context, "config": config, "busy": False, "turns": {},
                    "chats_enabled": chats_enabled}
            except BaseException:
                if workspace is not None:
                    stop_workspace(workspace)
                memory_context.__exit__(None, None, None)
                raise
        return attempt_id

    def start_turn(self, attempt_id, prompt, chat_id=None, request_id=None):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if request_id:
                self._check_chat(attempt, attempt_id, chat_id)
                chat_memory = self._chat_memory(attempt)
                existing = chat_memory.conn.execute(
                    'SELECT attempt_id, chat_id, prompt, turn_id, status FROM agent_requests WHERE request_id = %s',
                    (request_id,)).fetchone()
                if existing:
                    if existing['attempt_id'] != attempt_id or existing['chat_id'] != chat_id or existing['prompt'] != prompt:
                        raise ValueError('Request ID was already used for another request.')
                    turn = attempt['turns'].get(existing['turn_id'])
                    status = turn.status if turn and turn.done else existing['status']
                    return existing['turn_id'], status
            if attempt["busy"]:
                raise ValueError("An agent turn is already running.")
            if attempt.get('terminal_open'):
                raise ValueError('Disconnect the terminal before starting the agent.')
            if not attempt["workspace"].active:
                raise ValueError("The workspace is stopped.")
            # Legacy API turns become part of the original chat once chats exist.
            if chat_id is None and attempt.get('chats_enabled'):
                chat_id = attempt_id
            if chat_id:
                self._check_chat(attempt, attempt_id, chat_id)
            attempt["busy"] = True
            turn_id = str(uuid4())
            if chat_id:
                try:
                    chat_memory = self._chat_memory(attempt)
                    with chat_memory.conn.transaction():
                        if request_id:
                            row = chat_memory.conn.execute(
                                "INSERT INTO agent_requests (request_id, attempt_id, chat_id, prompt, turn_id, status) VALUES (%s, %s, %s, %s, %s, 'running') ON CONFLICT DO NOTHING RETURNING request_id",
                                (request_id, attempt_id, chat_id, prompt, turn_id)).fetchone()
                            if not row:
                                raise ValueError('Request ID was already used for another request.')
                        append_chat_event(chat_memory, chat_id, turn_id, {'type': 'prompt', 'message': prompt})
                        chat_memory.conn.execute("UPDATE agent_chats SET title = %s WHERE id = %s AND title = 'New chat'",
                                                       (prompt[:60], chat_id))
                except Exception:
                    attempt['busy'] = False
                    raise
            def save_event(event):
                append_chat_event(chat_memory, chat_id, turn_id, event)
            save = save_event if chat_id else None
            turn = Turn(chat_id, save)
            attempt["turns"][turn_id] = turn

        def worker():
            turn.publish({"type": "turn_started"})
            status = "failed"
            try:
                result = run_turn(prompt, attempt["workspace"], attempt["memory"], chat_id or attempt_id,
                                  attempt["config"], turn.publish)
                if result.get("error"):
                    turn.publish({"type": "error", "message": result["error"]})
                else:
                    turn.publish({"type": "answer", "message": result.get("answer", "")})
                    status = "completed"
            except Exception as error:
                log_error('turn error', error)
                turn.publish({"type": "error", "message": "The agent turn failed. Check the server logs and workspace."})
            finally:
                turn.publish({"type": "turn_finished", "status": status})
                turn.status = status if turn.save or not chat_id else 'interrupted'
                if request_id:
                    try:
                        chat_memory.conn.execute('UPDATE agent_requests SET status = %s WHERE request_id = %s',
                                                 (turn.status, request_id))
                    except Exception as error:
                        log_error('request status error', error)
                        turn.status = 'interrupted'
                        turn.publish({'type': 'error', 'message': 'Could not save the request status. Check the workspace before retrying.'})
                with self.lock:
                    attempt["busy"] = False
                with turn.condition:
                    turn.done = True
                    turn.condition.notify_all()

        thread = threading.Thread(target=worker, daemon=True)
        with self.lock:
            attempt["thread"] = thread
            try:
                thread.start()
            except Exception:
                attempt['busy'] = False
                if request_id:
                    chat_memory.conn.execute("UPDATE agent_requests SET status = 'interrupted' WHERE request_id = %s", (request_id,))
                raise
        return (turn_id, 'running') if request_id else turn_id

    def events(self, attempt_id, turn_id, after, timeout=1, chat_id=None):
        with self.lock:
            turn = self.attempts[attempt_id]["turns"][turn_id]
            if chat_id is not None and turn.chat_id != chat_id:
                raise KeyError(chat_id)
        with turn.condition:
            if not turn.done and not any(event["id"] > after for event in turn.events):
                turn.condition.wait(timeout)
            if turn.events and after < turn.events[0]["id"] - 1:
                raise ValueError("Some earlier events are no longer available.")
            return [event for event in turn.events if event["id"] > after], turn.done

    def _check_chat(self, attempt, attempt_id, chat_id):
        row = self._chat_memory(attempt).conn.execute('SELECT id FROM agent_chats WHERE id = %s AND attempt_id = %s',
                                             (chat_id, attempt_id)).fetchone()
        if not row:
            raise KeyError(chat_id)

    def list_chats(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if attempt['busy'] and not attempt.get('chats_enabled'):
                raise ValueError('Wait for the current turn to finish before opening chats.')
            chat_memory = self._chat_memory(attempt)
            ensure_original_chat(attempt['memory'], attempt_id, chat_memory)
            attempt['chats_enabled'] = True
            return list(chat_memory.conn.execute(
                'SELECT id, title FROM agent_chats WHERE attempt_id = %s ORDER BY created_at, id',
                (attempt_id,)).fetchall())

    def create_chat(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if attempt['busy']:
                raise ValueError('Wait for the agent to finish before starting a new chat.')
            chat_memory = self._chat_memory(attempt)
            ensure_original_chat(attempt['memory'], attempt_id, chat_memory)
            attempt['chats_enabled'] = True
            chat_id = str(uuid4())
            chat_memory.conn.execute('INSERT INTO agent_chats (id, attempt_id) VALUES (%s, %s)',
                                           (chat_id, attempt_id))
            return {'id': chat_id, 'title': 'New chat'}

    def chat_history(self, attempt_id, chat_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            self._check_chat(attempt, attempt_id, chat_id)
            rows = self._chat_memory(attempt).conn.execute(
                'SELECT turn_id, event FROM agent_chat_events WHERE chat_id = %s ORDER BY id', (chat_id,)).fetchall()
            running = None
            active_chat = None
            if attempt['busy']:
                turn_id = next(reversed(attempt['turns']))
                active_chat = attempt['turns'][turn_id].chat_id
                if active_chat == chat_id:
                    running = turn_id
            messages = []
            started = set()
            finished = set()
            for row in rows:
                event = row['event']
                if event['type'] == 'turn_started':
                    started.add(row['turn_id'])
                elif event['type'] == 'turn_finished':
                    finished.add(row['turn_id'])
                message = None
                if event['type'] in ('prompt', 'answer', 'error', 'progress_update'):
                    role = {'prompt': 'user', 'answer': 'assistant', 'error': 'error', 'progress_update': 'progress'}[event['type']]
                    message = {'role': role, 'content': event.get('message', '')}
                elif event['type'] == 'tool_started':
                    message = {'role': 'tool', 'content': f"{event.get('name', 'tool')} started"}
                elif event['type'] == 'tool_finished':
                    message = {'role': 'tool', 'content': f"{event.get('name', 'tool')}: {event.get('status', 'recorded')}"}
                if message:
                    if event.get('id') is not None:
                        message['event_key'] = f"{row['turn_id']}:{event['id']}"
                    messages.append(message)
            if started - finished - {running}:
                messages.append({'role': 'error', 'content': 'An earlier turn was interrupted before it finished.'})
            return {'messages': messages, 'running_turn': running, 'active_chat': active_chat,
                    'workspace_busy': attempt['busy']}

    def history(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if attempt["busy"]:
                return {"messages": [], "running_turn": next(reversed(attempt["turns"]))}
            checkpoint = attempt["memory"].get_tuple({"configurable": {"thread_id": attempt_id}})
            messages = []
            if checkpoint:
                for item in checkpoint.checkpoint.get("channel_values", {}).get("messages", []):
                    if isinstance(item, HumanMessage) and isinstance(item.content, str):
                        messages.append({"role": "user", "content": item.content})
                    elif isinstance(item, AIMessage) and not item.tool_calls and not item.invalid_tool_calls and item.text:
                        messages.append({"role": "assistant", "content": item.text})
            return {"messages": messages, "running_turn": None}

    def file(self, attempt_id, name, args):
        # One local lock keeps API saves from overlapping an agent turn.
        with self.lock:
            attempt = self.attempts[attempt_id]
            if name == "write_editor_file" and attempt["busy"]:
                raise ValueError("Cannot save while the agent is working.")
            if name == 'write_editor_file' and attempt.get('terminal_open'):
                raise ValueError('Disconnect the terminal before saving a file.')
            if not attempt["workspace"].active:
                raise ValueError("The workspace is stopped.")
            return run_workspace_tool(attempt["workspace"], name, args)

    def terminal_workspace(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if not attempt['workspace'].active:
                raise ValueError('The workspace is stopped.')
            if attempt['busy']:
                raise ValueError('Wait for the agent to finish before opening the terminal.')
            if attempt.get('terminal_open'):
                raise ValueError('A terminal is already open for this attempt.')
            attempt['terminal_open'] = True
            return attempt['workspace'].container

    def release_terminal(self, attempt_id):
        with self.lock:
            if attempt_id in self.attempts:
                attempt = self.attempts[attempt_id]
                try:
                    # Restart kills all terminal processes, including detached children.
                    docker('restart', attempt['workspace'].container)
                except Exception:
                    attempt['workspace'].active = False
                    raise
                finally:
                    attempt['terminal_open'] = False

    def start_ide(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if not attempt["workspace"].active:
                raise ValueError("The workspace is stopped.")
            if attempt.get("ide_container"):
                raise ValueError("The IDE is already running for this attempt.")
            name = "coding-agent-theia-" + uuid4().hex
            volume = attempt["workspace"].volume
            try:
                docker("run", "-d", "--name", name, "--read-only", "--user", "1000:1000",
                       "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m,mode=1777", "--cap-drop", "ALL",
                       "--security-opt", "no-new-privileges", "--memory", "2g", "--cpus", "1",
                       "--pids-limit", "256", "-e", "HOME=/tmp/theia", "-p", "127.0.0.1:3000:3000",
                       "--mount", f"type=volume,source={volume},target=/workspace/challenge",
                       "agentic-theia-workspace:local", "/workspace/challenge", "--hostname=0.0.0.0")
            except Exception:
                try:
                    docker("rm", "-f", name)
                except Exception:
                    pass
                raise RuntimeError("Could not start Theia. Check the image and local port 3000.") from None
            attempt["ide_container"] = name
            return f"http://127.0.0.1:3000/?agentic_attempt={attempt_id}"

    def close(self, attempt_id):
        with self.lock:
            attempt = self.attempts[attempt_id]
            if attempt["busy"]:
                raise ValueError("An agent turn is still running.")
            if attempt.get("ide_container"):
                docker("rm", "-f", attempt["ide_container"])
                attempt["ide_container"] = None
            stop_workspace(attempt["workspace"])
            if 'chat_memory' in attempt:
                attempt['chat_memory'].conn.close()
            attempt["memory_context"].__exit__(None, None, None)
            del self.attempts[attempt_id]
            return attempt["workspace"].volume

    def shutdown(self):
        # Stop this service's containers, keeping the workspace volumes.
        with self.lock:
            active = list(self.attempts.items())
        for attempt_id, attempt in active:
            thread = attempt.get("thread")
            if attempt["busy"]:
                try:
                    docker("kill", attempt["workspace"].container)
                    attempt["workspace"].active = False
                except Exception:
                    print("Could not stop an active agent container during shutdown.")
                if thread:
                    thread.join(timeout=35)
            if thread and thread.is_alive():
                print("An agent turn did not stop during shutdown; check Docker.")
                continue
            try:
                self.close(attempt_id)
            except Exception:
                print("Could not clean up an attempt during shutdown; check Docker.")

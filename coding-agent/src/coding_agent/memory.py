from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from psycopg.types.json import Jsonb


@contextmanager
def open_memory(database_url, thread_id):
    # One database connection holds the conversation lock for the whole turn.
    with PostgresSaver.from_conn_string(database_url) as memory:
        memory.serde = JsonPlusSerializer(allowed_msgpack_modules=None)
        memory.setup()
        memory.conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_workspaces (thread_id text PRIMARY KEY, volume text NOT NULL)"
        )
        memory.conn.execute("""CREATE TABLE IF NOT EXISTS agent_chats (
            id text PRIMARY KEY, attempt_id text NOT NULL REFERENCES agent_workspaces(thread_id) ON DELETE CASCADE,
            title text NOT NULL DEFAULT 'New chat', created_at timestamptz NOT NULL DEFAULT now())""")
        memory.conn.execute("""CREATE TABLE IF NOT EXISTS agent_chat_events (
            id bigserial PRIMARY KEY, chat_id text NOT NULL REFERENCES agent_chats(id) ON DELETE CASCADE,
            turn_id text NOT NULL, event jsonb NOT NULL)""")
        memory.conn.execute("""CREATE TABLE IF NOT EXISTS agent_requests (
            request_id text PRIMARY KEY, attempt_id text NOT NULL REFERENCES agent_workspaces(thread_id) ON DELETE CASCADE,
            chat_id text NOT NULL REFERENCES agent_chats(id) ON DELETE CASCADE,
            prompt text NOT NULL, turn_id text NOT NULL, status text NOT NULL)""")
        row = memory.conn.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS locked", (thread_id,)
        ).fetchone()
        if not row["locked"]:
            raise ValueError("This conversation is already running.")
        try:
            yield memory
        finally:
            memory.conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (thread_id,))


def get_workspace(memory, thread_id):
    row = memory.conn.execute("SELECT volume FROM agent_workspaces WHERE thread_id = %s", (thread_id,)).fetchone()
    return row["volume"] if row else None


def save_workspace(memory, thread_id, volume):
    memory.conn.execute("INSERT INTO agent_workspaces (thread_id, volume) VALUES (%s, %s)", (thread_id, volume))


def append_chat_event(memory, chat_id, turn_id, event):
    memory.conn.execute('INSERT INTO agent_chat_events (chat_id, turn_id, event) VALUES (%s, %s, %s)',
                        (chat_id, turn_id, Jsonb(event)))


def ensure_original_chat(memory, attempt_id, chat_memory=None):
    # Migrate the original checkpoint once, without changing its thread ID.
    chat_memory = chat_memory or memory
    with chat_memory.conn.transaction():
        row = chat_memory.conn.execute(
            'INSERT INTO agent_chats (id, attempt_id) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id',
            (attempt_id, attempt_id)).fetchone()
        if not row:
            return
        checkpoint = memory.get_tuple({'configurable': {'thread_id': attempt_id}})
        messages = checkpoint.checkpoint.get('channel_values', {}).get('messages', []) if checkpoint else []
        names = {}
        for item in messages:
            if isinstance(item, HumanMessage) and isinstance(item.content, str):
                append_chat_event(chat_memory, attempt_id, 'original', {'type': 'prompt', 'message': item.content})
                chat_memory.conn.execute("UPDATE agent_chats SET title = %s WHERE id = %s AND title = 'New chat'",
                                    (item.content[:60], attempt_id))
            elif isinstance(item, AIMessage):
                for call in item.tool_calls:
                    names[call['id']] = call['name']
                if not item.tool_calls and not item.invalid_tool_calls and item.text:
                    append_chat_event(chat_memory, attempt_id, 'original', {'type': 'answer', 'message': item.text})
            elif isinstance(item, ToolMessage):
                append_chat_event(chat_memory, attempt_id, 'original', {'type': 'tool_finished',
                                  'name': names.get(item.tool_call_id, 'tool'), 'status': 'recorded'})

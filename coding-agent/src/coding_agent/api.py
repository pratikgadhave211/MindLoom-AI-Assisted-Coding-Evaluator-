import json
import os
import secrets
import asyncio
import codecs
from uuid import UUID
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import dotenv_values
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .attempts import AttemptManager
from .sanity import check_prompt
from .terminal import Terminal


class Prompt(BaseModel):
    prompt: str
    request_id: str | None = None


class FileSave(BaseModel):
    path: str
    content: str
    expected_version: str


class SubmissionRequest(BaseModel):
    request_id: str


class AttemptRequest(BaseModel):
    challenge_id: str | None = None


def create_app(manager=None, token=None):
    @asynccontextmanager
    async def lifespan(app):
        yield
        if hasattr(app.state.manager, "shutdown"):
            await asyncio.to_thread(app.state.manager.shutdown)

    app = FastAPI(title="Coding Agent API", lifespan=lifespan)
    app.state.manager = manager or AttemptManager()
    if token is None:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        values = dotenv_values(env_file, interpolate=False)
        token = os.environ.get("AGENT_API_TOKEN", values.get("AGENT_API_TOKEN", ""))
    app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type", "Last-Event-ID"])

    def authorize(authorization: str = Header(default="")):
        if not token or not secrets.compare_digest(authorization, "Bearer " + token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get('/challenges', dependencies=[Depends(authorize)])
    def challenges():
        path = Path(__file__).resolve().parents[2] / 'challenges/flaskr-secure-search/challenge.json'
        challenge = json.loads(path.read_text(encoding='utf-8'))
        return {'challenges': [{key: challenge[key] for key in ('id', 'title', 'summary')}]}

    @app.websocket('/attempts/{attempt_id}/terminal')
    async def terminal_connection(websocket: WebSocket, attempt_id: str):
        allowed = {'http://localhost:5173', 'http://127.0.0.1:5173',
                   'http://localhost:5174', 'http://127.0.0.1:5174'}
        if websocket.headers.get('origin') not in allowed:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        terminal = None
        reserved = False
        output_task = None
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            supplied = auth.get('token', '') if isinstance(auth, dict) else ''
            if not isinstance(supplied, str) or not token or not secrets.compare_digest(supplied, token):
                await websocket.close(code=1008)
                return
            try:
                container = app.state.manager.terminal_workspace(attempt_id)
                reserved = True
                terminal = await asyncio.to_thread(Terminal, container)
            except (KeyError, ValueError):
                await websocket.send_json({'type': 'error', 'message': 'Workspace unavailable or terminal already open.'})
                return
            except Exception:
                await websocket.send_json({'type': 'error', 'message': 'Could not start the workspace terminal.'})
                return

            await websocket.send_json({'type': 'ready'})
            async def send_output():
                decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
                try:
                    while True:
                        data = await asyncio.to_thread(terminal.read)
                        if not data:
                            break
                        await websocket.send_json({'type': 'output', 'data': decoder.decode(data)})
                except Exception:
                    pass
                try:
                    await websocket.close()
                except Exception:
                    pass

            output_task = asyncio.create_task(send_output())
            while True:
                message = await websocket.receive_json()
                if message.get('type') == 'input' and isinstance(message.get('data'), str) and len(message['data']) <= 16384:
                    await asyncio.to_thread(terminal.write, message['data'])
                elif message.get('type') == 'resize':
                    cols, rows = message.get('cols'), message.get('rows')
                    if type(cols) is int and type(rows) is int and 1 <= cols <= 500 and 1 <= rows <= 200:
                        await asyncio.to_thread(terminal.resize, cols, rows)
                elif message.get('type') == 'close':
                    break
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, OSError):
            pass
        finally:
            if reserved:
                try:
                    await asyncio.to_thread(app.state.manager.release_terminal, attempt_id)
                except Exception:
                    print('Could not restart the workspace after closing its terminal.')
            if terminal:
                try:
                    await asyncio.to_thread(terminal.close)
                except Exception:
                    print('Could not cleanly close the workspace terminal.')
            if output_task:
                output_task.cancel()
                await asyncio.gather(output_task, return_exceptions=True)
            try:
                await websocket.close()
            except Exception:
                pass

    @app.post("/attempts", status_code=201, dependencies=[Depends(authorize)])
    def create_attempt(request: AttemptRequest | None = None):
        try:
            attempt_id = app.state.manager.create(request.challenge_id) if request and request.challenge_id else app.state.manager.create()
            return {"attempt_id": attempt_id, "status": "ready"}
        except ValueError:
            raise HTTPException(status_code=400, detail="Challenge unavailable.") from None
        except Exception:
            raise HTTPException(status_code=503, detail="Could not start an isolated workspace. Check Docker and PostgreSQL.") from None

    @app.get('/attempts/{attempt_id}/question', dependencies=[Depends(authorize)])
    def question(attempt_id: str):
        try:
            return app.state.manager.question(attempt_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Attempt not found.') from None

    @app.post('/attempts/{attempt_id}/submissions', status_code=202, dependencies=[Depends(authorize)])
    def submit(attempt_id: str, request: SubmissionRequest):
        try:
            request_id = str(UUID(request.request_id))
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail='Invalid request ID.') from None
        try:
            return app.state.manager.submit(attempt_id, request_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Attempt not found.') from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except Exception:
            raise HTTPException(status_code=503, detail='Could not prepare submission.') from None

    @app.get('/attempts/{attempt_id}/submissions/{submission_id}', dependencies=[Depends(authorize)])
    def submission(attempt_id: str, submission_id: str):
        try:
            return app.state.manager.submission(attempt_id, submission_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Submission not found.') from None

    @app.post("/attempts/{attempt_id}/resume", dependencies=[Depends(authorize)])
    def resume_attempt(attempt_id: str):
        try:
            return {"attempt_id": app.state.manager.resume(attempt_id), "status": "ready"}
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None
        except ValueError:
            raise HTTPException(status_code=409, detail="Attempt is already open or unavailable.") from None
        except Exception:
            raise HTTPException(status_code=503, detail="Could not reopen the workspace.") from None

    @app.get("/attempts/{attempt_id}/history", dependencies=[Depends(authorize)])
    def history(attempt_id: str):
        try:
            return app.state.manager.history(attempt_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None

    @app.get('/attempts/{attempt_id}/predictometer', dependencies=[Depends(authorize)])
    def predictometer(attempt_id: str):
        try:
            return app.state.manager.predictometer(attempt_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Attempt not found.') from None
        except Exception:
            raise HTTPException(status_code=503, detail='Evaluation is temporarily unavailable.') from None

    @app.get('/attempts/{attempt_id}/chats', dependencies=[Depends(authorize)])
    def list_chats(attempt_id: str):
        try:
            return app.state.manager.list_chats(attempt_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Attempt not found.') from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post('/attempts/{attempt_id}/chats', status_code=201, dependencies=[Depends(authorize)])
    def create_chat(attempt_id: str):
        try:
            return app.state.manager.create_chat(attempt_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Attempt not found.') from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.get('/attempts/{attempt_id}/chats/{chat_id}/history', dependencies=[Depends(authorize)])
    def chat_history(attempt_id: str, chat_id: str):
        try:
            return app.state.manager.chat_history(attempt_id, chat_id)
        except KeyError:
            raise HTTPException(status_code=404, detail='Chat not found.') from None

    @app.post('/attempts/{attempt_id}/chats/{chat_id}/turns', status_code=202, dependencies=[Depends(authorize)])
    def start_chat_turn(attempt_id: str, chat_id: str, request: Prompt):
        try:
            prompt = check_prompt(request.prompt)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        request_id = None
        if request.request_id is not None:
            try:
                request_id = str(UUID(request.request_id))
            except (ValueError, AttributeError):
                raise HTTPException(status_code=400, detail='Invalid request ID.') from None
        try:
            if request_id:
                turn_id, status = app.state.manager.start_turn(attempt_id, prompt, chat_id=chat_id, request_id=request_id)
            else:
                turn_id = app.state.manager.start_turn(attempt_id, prompt, chat_id=chat_id)
                status = 'running'
            return {'turn_id': turn_id, 'status': status}
        except KeyError:
            raise HTTPException(status_code=404, detail='Chat not found.') from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/attempts/{attempt_id}/turns", status_code=202, dependencies=[Depends(authorize)])
    def start_turn(attempt_id: str, request: Prompt):
        try:
            prompt = check_prompt(request.prompt)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        try:
            turn_id = app.state.manager.start_turn(attempt_id, prompt)
            return {"turn_id": turn_id, "status": "running"}
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None

    @app.post("/attempts/{attempt_id}/ide", status_code=202, dependencies=[Depends(authorize)])
    def start_ide(attempt_id: str):
        try:
            return {"status": "starting", "url": app.state.manager.start_ide(attempt_id)}
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Could not start Theia. Check its image and port 3000.") from None

    @app.get("/attempts/{attempt_id}/turns/{turn_id}/events", dependencies=[Depends(authorize)])
    def turn_events(attempt_id: str, turn_id: str, request: Request):
        return stream_events(attempt_id, turn_id, request)

    @app.get('/attempts/{attempt_id}/chats/{chat_id}/turns/{turn_id}/events', dependencies=[Depends(authorize)])
    def chat_turn_events(attempt_id: str, chat_id: str, turn_id: str, request: Request):
        return stream_events(attempt_id, turn_id, request, chat_id)

    def stream_events(attempt_id, turn_id, request, chat_id=None):
        def read_events(after, timeout):
            if chat_id is None:
                return app.state.manager.events(attempt_id, turn_id, after, timeout=timeout)
            return app.state.manager.events(attempt_id, turn_id, after, timeout=timeout, chat_id=chat_id)
        try:
            after = int(request.headers.get("last-event-id", "0"))
            if after < 0:
                raise ValueError()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid event ID.") from None
        try:
            read_events(after, timeout=0)
        except KeyError:
            raise HTTPException(status_code=404, detail="Turn not found.") from None
        except ValueError:
            raise HTTPException(status_code=410, detail="Earlier events are no longer available.") from None

        def stream():
            cursor = after
            while True:
                try:
                    events, done = read_events(cursor, timeout=1)
                except (KeyError, ValueError):
                    yield 'event: error\ndata: {"type":"error","message":"Event history is unavailable."}\n\n'
                    return
                for event in events:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                if done:
                    return
                if not events:
                    yield ": keepalive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.delete("/attempts/{attempt_id}", dependencies=[Depends(authorize)])
    def close_attempt(attempt_id: str):
        try:
            volume = app.state.manager.close(attempt_id)
            return {"status": "closed", "workspace_volume": volume}
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Could not stop the workspace.") from None

    def file_operation(attempt_id, name, args):
        try:
            response = app.state.manager.file(attempt_id, name, args)
        except KeyError:
            raise HTTPException(status_code=404, detail="Attempt not found.") from None
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
        if response["status"] == "conflict":
            raise HTTPException(status_code=409, detail=response["result"])
        if response["status"] != "completed":
            raise HTTPException(status_code=400, detail=response["result"])
        return response["result"]

    @app.get("/attempts/{attempt_id}/files", dependencies=[Depends(authorize)])
    def list_files(attempt_id: str, path: str = "."):
        return {"entries": file_operation(attempt_id, "list_files", {"path": path})}

    @app.get("/attempts/{attempt_id}/file", dependencies=[Depends(authorize)])
    def read_file(attempt_id: str, path: str):
        return file_operation(attempt_id, "read_editor_file", {"path": path})

    @app.put("/attempts/{attempt_id}/file", dependencies=[Depends(authorize)])
    def save_file(attempt_id: str, request: FileSave):
        if len(request.content.encode("utf-8")) > 1024 * 1024:
            raise HTTPException(status_code=413, detail="File is too large.")
        return file_operation(attempt_id, "write_editor_file", request.model_dump())

    return app


app = create_app()

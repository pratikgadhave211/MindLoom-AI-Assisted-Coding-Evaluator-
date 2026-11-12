import React, { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';

export default function Terminal({ token, attempt, agentRunning, onStateChange }) {
  const element = useRef(null);
  const runningRef = useRef(agentRunning);
  const [connection, setConnection] = useState(0);
  const [enabled, setEnabled] = useState(false);
  runningRef.current = agentRunning;

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    const terminal = new XTerm({ cursorBlink: true, fontSize: 13, theme: { background: '#11111b' } });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(element.current);
    fit.fit();

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/agent-api/attempts/${attempt}/terminal`);
    socket.onopen = () => {
      if (disposed) { socket.close(); return; }
      socket.send(JSON.stringify({ token }));
    };
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === 'ready') {
        terminal.writeln('Connected to the challenge workspace.');
        socket.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }));
      } else if (message.type === 'output') terminal.write(message.data);
      else if (message.type === 'error') terminal.writeln(`\r\n${message.message}`);
    };
    socket.onerror = () => terminal.writeln('\r\nTerminal connection failed.');
    socket.onclose = () => {
      if (!disposed) {
        onStateChange(false);
        terminal.writeln('\r\nTerminal disconnected. Use Reconnect to try again.');
      }
    };
    terminal.onData(data => {
      if (socket.readyState === WebSocket.OPEN && (!runningRef.current || data === '\x03')) {
        socket.send(JSON.stringify({ type: 'input', data }));
      } else if (runningRef.current && data !== '\x03') {
        terminal.writeln('\r\nWait for the agent to finish before entering commands.');
      }
    });
    terminal.onResize(({ cols, rows }) => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'resize', cols, rows }));
    });
    const observer = new ResizeObserver(() => { if (!disposed) fit.fit(); });
    observer.observe(element.current);
    return () => {
      disposed = true;
      observer.disconnect();
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'close' }));
      socket.close();
      terminal.dispose();
    };
  }, [token, attempt, connection, enabled]);

  return <div className="h-48 flex flex-col bg-ide-sidebar border-t border-ide-border">
    <div className="px-3 py-1 flex justify-between text-xs text-ide-textMuted">
      <span>Workspace terminal · Disconnect before saving or using the agent. Disconnect stops running processes.</span>
      {enabled
        ? <span className="flex gap-3"><button onClick={() => { onStateChange(true); setConnection(value => value + 1); }} className="underline">Reconnect</button>
            <button onClick={() => { setEnabled(false); onStateChange(false); }} className="underline">Disconnect</button></span>
        : <button disabled={agentRunning} onClick={() => { onStateChange(true); setEnabled(true); }} className="underline disabled:opacity-50">Connect</button>}
    </div>
    <div ref={element} className="flex-1 min-h-0 px-2" />
  </div>;
}

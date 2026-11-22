import React from 'react';
import ReactDOM from 'react-dom/client';
import WorkspaceApp from './WorkspaceApp';
import LandingPage from './LandingPage';
import './index.css';

const App = window.location.pathname.startsWith('/app') ? WorkspaceApp : LandingPage;

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

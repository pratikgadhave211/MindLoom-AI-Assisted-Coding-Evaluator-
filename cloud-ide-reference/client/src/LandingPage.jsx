import React from 'react';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import desktopHero from './assets/mindloom-studio.webp';
import mobileHero from './assets/mindloom-portrait.webp';
import Sidebar from './components/Sidebar';
import EditorTabs from './components/EditorTabs';
import './landing.css';

function Wordmark() {
  return <a className="ml-wordmark" href="/" aria-label="MindLoom home"><span className="ml-weave" aria-hidden="true" />MindLoom</a>;
}

export default function LandingPage() {
  return (
    <div className="ml-page">
      <a className="ml-skip" href="#ml-main">Skip to content</a>
      <header className="ml-header">
        <Wordmark />
        <nav aria-label="Main navigation">
          <a href="#ml-round">Inside a round</a>
          <a className="ml-open" href="/app">Open workspace <ArrowUpRight size={15} /></a>
        </nav>
      </header>

      <main id="ml-main" tabIndex={-1}>
        <section className="ml-hero" aria-labelledby="ml-title">
          <picture className="ml-hero-image">
            <source media="(max-width: 680px)" srcSet={mobileHero} />
            <img src={desktopHero} alt="A developer studying a monitor lit by a brain woven from silver and lime threads." fetchPriority="high" />
          </picture>
          <div className="ml-hero-copy">
            <h1 id="ml-title">How do you<br />code <em>with AI?</em></h1>
            <p>Work through a broken repository with an AI partner. When you submit, get feedback on your fix and the decisions behind it.</p>
            <a className="ml-action" href="/app">Explore challenges <ArrowUpRight size={19} /></a>
          </div>
        </section>

        <section className="ml-round" id="ml-round" aria-labelledby="ml-round-title">
          <h2 id="ml-round-title">Inside <em>a round.</em></h2>
          <div className="ml-round-body">
            <ol className="ml-round-steps">
              <li><h3>Get your bearings.</h3><p>Pick a challenge and open the repo in your browser. Poke around the files, run the project, and see what you’re working with.</p></li>
              <li><h3>Pair up with your agent.</h3><p>Ask it to trace something, talk through a hunch, or make an edit. You decide what’s worth keeping and what needs another look.</p></li>
              <li><h3>See how you did.</h3><p>Submit when you’d ship it. See what passed, where your prompts helped, and one thing to try differently next round.</p></li>
            </ol>
            <figure className="ml-round-preview" aria-label="Workspace preview: a repository, an open project file, and an empty agent prompt.">
              <div className="ml-round-window" inert="">
                <div className="ml-round-tree">
                  <Sidebar files={{ 'flaskr/blog.py': '', 'tests/test_blog.py': '', 'pyproject.toml': '', 'README.rst': '' }}
                    activeFile="pyproject.toml" section="files" readOnly />
                </div>
                <div className="ml-round-editor">
                  <EditorTabs openFiles={['pyproject.toml']} activeFile="pyproject.toml" />
                  <pre>{'[project]\nname = "flaskr"\nversion = "1.0.0"\n\ndependencies = [\n    "flask",\n]'}</pre>
                </div>
                <div className="ml-round-chat">
                  <strong>Coding agent</strong>
                  <span>Ask the agent about this project…</span>
                </div>
              </div>
            </figure>
          </div>
          <div className="ml-round-close">
            <p>The agent says it’s done.<br /><em>What would you check before you ship?</em></p>
            <a href="/app">Explore challenges <ArrowRight size={18} /></a>
          </div>
        </section>
        <footer className="ml-footer">
          <Wordmark />
          <a href="#ml-main">Back to top ↑</a>
        </footer>
      </main>
    </div>
  );
}


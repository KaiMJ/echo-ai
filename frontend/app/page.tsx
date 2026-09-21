import { AgentDemo, OrbSignature } from "../components/agent-demo";
import { CopyCommand } from "../components/copy-command";
import { OrbStudio } from "../components/orb-studio";

const repo = "https://github.com/KaiMJ/echo-ai";
const guides = `${repo}/blob/main/docs/guides`;

function EchoMark() {
  return (
    <span className="echo-mark" aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

export default function Home() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header wrap">
        <a href="#" className="wordmark" aria-label="Echo home">
          <EchoMark />
          echo<span className="wordmark-period">.</span>
        </a>
        <nav
          aria-label="Main navigation"
          className="flex items-center gap-6 sm:gap-9"
        >
          <a href="#how-it-works" className="nav-detail">
            How it works
          </a>
          <a href={`${guides}/README.md`}>Docs</a>
          <a className="nav-github" href={repo}>
            GitHub <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </header>
      <main id="main">
        <section className="hero wrap">
          <div className="hero-copy">
            <div className="intro-line">
              <span className="status-dot" /> A local coding agent for Linux
            </div>
            <h1>
              Your code.
              <br />
              Your machine.
              <br />
              Your Echo.
            </h1>
            <p className="hero-description">
              A local coding agent for your terminal. Explore a repository, make
              a change, and review the result—with models you run yourself.
            </p>
            <div className="hero-actions">
              <a className="button button-dark" href="#get-started">
                Get started <span aria-hidden="true">↗</span>
              </a>
              <a className="text-link" href={repo}>
                Explore the source <span aria-hidden="true">↗</span>
              </a>
            </div>
            <p className="hero-footnote">Python 3.12+ · Linux · Local models</p>
          </div>
          <div className="hero-visual">
            <OrbStudio />
          </div>
        </section>
        <section className="foundation wrap" aria-label="Built with">
          <span>Familiar tools, working together.</span>
          <div>
            <span>Python</span>
            <span>vLLM</span>
            <span>LiteLLM</span>
            <span>Docker</span>
          </div>
        </section>
        <section className="workflow wrap" id="how-it-works">
          <div className="walkthrough">
            <div className="walkthrough-copy">
              <h2>
                From a question
                <br />
                to a working change.
              </h2>
              <p>
                Ask Echo to find its way through a repository, work on a
                feature, or show what changed. Keep the conversation next to the
                code.
              </p>
              <a className="text-link" href="#get-started">
                Start your first session <span aria-hidden="true">↗</span>
              </a>
              <div className="walkthrough-note">
                <span aria-hidden="true">›_</span>
                <p>
                  Read. Search. Edit. Run.
                  <br />
                  The tools you use, in one conversation.
                </p>
              </div>
            </div>
            <AgentDemo />
          </div>
          <div className="feature-grid">
            <article>
              <div className="feature-symbol" aria-hidden="true">
                [ ~/ ]
              </div>
              <h3>At home in your terminal.</h3>
              <p>
                Read, search, edit, and run commands in your checkout. Turn a
                conversation into changes you can inspect.
              </p>
            </article>
            <article>
              <div className="feature-symbol model-symbol" aria-hidden="true">
                <span /> <span /> <span />
              </div>
              <h3>Bring your own models.</h3>
              <p>
                Run Qwen or Gemma locally with vLLM. Echo connects through
                LiteLLM, with model settings you control.
              </p>
            </article>
            <article>
              <div className="feature-symbol" aria-hidden="true">
                ↶
              </div>
              <h3>Keep the thread.</h3>
              <p>
                Resume saved sessions and revisit recorded edits. Try a
                disposable Docker workspace with sandbox mode.
              </p>
            </article>
          </div>
        </section>
        <section className="sandbox-section">
          <div className="wrap sandbox-inner">
            <div>
              <span className="small-note">Room to experiment</span>
              <h2>
                Try it in a<br />
                fresh workspace.
              </h2>
              <p>
                Use sandbox mode to work in a disposable Docker copy. Inspect
                recorded agent edits, then apply them back to your checkout when
                you’re ready.
              </p>
              <a className="text-link" href={`${guides}/everyday-use.md#sandbox-mode`}>
                Read about sandbox mode <span aria-hidden="true">↗</span>
              </a>
            </div>
            <div className="sandbox-code">
              <div>
                <span className="text-neutral-500">
                  # Start in a disposable workspace
                </span>
                <br />
                <span className="text-neutral-500">$ </span>uv run echo-ai chat
                --sandbox
              </div>
              <div>
                <span className="text-neutral-500">
                  # Review recorded agent edits
                </span>
                <br />
                /diff
              </div>
              <div>
                <span className="text-neutral-500">
                  # Bring them into your checkout
                </span>
                <br />
                /apply
              </div>
              <p>Shell changes are outside /diff and /apply tracking.</p>
            </div>
          </div>
        </section>
        <section className="get-started wrap" id="get-started">
          <div>
            <OrbSignature />
            <h2>
              Make something
              <br />
              with Echo.
            </h2>
            <p>Clone the source, connect a model, and start a session.</p>
            <a href={`${guides}/getting-started.md`} className="text-link">
              Full setup guide <span aria-hidden="true">↗</span>
            </a>
          </div>
          <div className="setup-steps">
            <div>
              <span className="step-number">1</span>
              <h3>Clone the repository</h3>
              <CopyCommand command="git clone https://github.com/KaiMJ/echo-ai.git" />
            </div>
            <div>
              <span className="step-number">2</span>
              <h3>Install the dependencies</h3>
              <CopyCommand command="cd echo-ai && uv sync --locked" />
            </div>
            <div>
              <span className="step-number">3</span>
              <h3>Configure your model and launch</h3>
              <p>
                Follow the{" "}
                <a href={`${repo}/blob/main/docs/guides/local-models.md`}>
                  model setup guide
                </a>
                , then start a session.
              </p>
              <CopyCommand command="uv run echo-ai" />
            </div>
            <p className="setup-requirements">
              Linux · Python 3.12+ · uv · Git · Bash · ripgrep
              <br />
              Local inference requires Docker with NVIDIA GPU support.
            </p>
          </div>
        </section>
      </main>
      <footer className="wrap site-footer">
        <a className="wordmark" href="#" aria-label="Echo home">
          <EchoMark />
          echo.
        </a>
        <p>Small by design. Yours to build with.</p>
        <div className="flex gap-6">
          <a href={repo}>GitHub</a>
          <a href={`${guides}/README.md`}>Documentation</a>
        </div>
      </footer>
    </>
  );
}

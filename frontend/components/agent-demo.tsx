"use client";

import { useState } from "react";
import { ThinkingOrb } from "thinking-orbs";

const scenes = [
  {
    state: "searching",
    title: "Explore",
    prompt: "How does session persistence work?",
    action: "Searching the repository",
    lines: [
      "search  src/echo_ai/",
      "read    session storage and runtime",
      "trace   how conversations are saved",
    ],
    result: "Find the context before making a change.",
  },
  {
    state: "working",
    title: "Build",
    prompt: "Add a command to export a session.",
    action: "Working through the change",
    lines: [
      "read    the existing CLI commands",
      "edit    the session export handler",
      "bash    run the relevant tests",
    ],
    result: "From a terminal prompt to a working patch.",
  },
  {
    state: "solving",
    title: "Review",
    prompt: "Show me what changed this session.",
    action: "Inspecting recorded edits",
    lines: [
      "/diff   inspect agent edit and write changes",
      "/undo   restore the previous turn",
      "/redo   bring the change back",
    ],
    result: "Keep a clear view of the edits along the way.",
  },
] as const;

export function AgentDemo() {
  const [active, setActive] = useState(0);
  const scene = scenes[active];
  return (
    <div className="demo-shell">
      <div className="demo-top">
        <span className="flex items-center gap-2">
          <span className="terminal-dot" /> echo / terminal
        </span>
        <span>Illustrative session</span>
      </div>
      <div
        className="demo-body"
        role="tabpanel"
        id="demo-panel"
        aria-labelledby={`demo-tab-${active}`}
      >
        <div className="terminal-command">
          <span aria-hidden="true">❯</span> uv run echo-ai
        </div>
        <div className="demo-prompt">{scene.prompt}</div>
        <div className="flex items-center gap-4 my-7">
          <ThinkingOrb state={scene.state} size={64} theme="dark" />
          <div>
            <span className="block text-white font-semibold">Echo</span>
            <span className="text-sm text-neutral-400">{scene.action}</span>
          </div>
        </div>
        <div className="terminal-lines">
          {scene.lines.map((line) => (
            <div key={line}>
              <span aria-hidden="true">↳</span>
              {line}
            </div>
          ))}
        </div>
        <p className="demo-result">
          {scene.result}
          <span className="cursor" aria-hidden="true" />
        </p>
      </div>
      <div className="demo-tabs" role="tablist" aria-label="Example workflows">
        {scenes.map((item, index) => (
          <button
            key={item.state}
            id={`demo-tab-${index}`}
            role="tab"
            aria-selected={active === index}
            aria-controls="demo-panel"
            tabIndex={active === index ? 0 : -1}
            onClick={() => setActive(index)}
            onKeyDown={(event) => {
              const next =
                event.key === "ArrowRight"
                  ? (index + 1) % 3
                  : event.key === "ArrowLeft"
                    ? (index + 2) % 3
                    : event.key === "Home"
                      ? 0
                      : event.key === "End"
                        ? 2
                        : null;
              if (next !== null) {
                event.preventDefault();
                setActive(next);
                document.getElementById(`demo-tab-${next}`)?.focus();
              }
            }}
          >
            {item.title}
          </button>
        ))}
      </div>
    </div>
  );
}

export function OrbSignature() {
  return (
    <div className="orb-signature" aria-hidden="true">
      <ThinkingOrb state="breathing" size={64} theme="light" />
    </div>
  );
}

"use client";
import { useState } from "react";

export function CopyCommand({ command }: { command: string }) {
  const [status, setStatus] = useState("Copy");
  async function copy() {
    try {
      await navigator.clipboard.writeText(command);
      setStatus("Copied");
    } catch {
      setStatus("Select to copy");
    }
  }
  return (
    <div className="copy-command">
      <code>{command}</code>
      <button onClick={copy} aria-label={`Copy command: ${command}`}>
        <span aria-live="polite">{status}</span>
      </button>
    </div>
  );
}

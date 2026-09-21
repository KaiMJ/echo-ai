"use client";

import { useEffect, useRef, useState } from "react";
import { MODE_DRAWS, resolvePreset, type OrbState } from "thinking-orbs/engine";

const states: { state: OrbState; title: string; detail: string }[] = [
  {
    state: "searching",
    title: "Explore",
    detail: "A question is a good place to start.",
  },
  {
    state: "working",
    title: "Build",
    detail: "One small change. Then the next.",
  },
  {
    state: "connecting",
    title: "Connect",
    detail: "Find the thread through your code.",
  },
  {
    state: "breathing",
    title: "Think",
    detail: "A little space to work things out.",
  },
];

export function OrbStudio() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const selected = states[active];

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const preset = resolvePreset(selected.state, 64);
    let frame = 0;
    let visible = false;
    let running = false;
    let dimension = 0;
    const draw = (time: number) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextDimension = Math.round(canvas.clientWidth * dpr);
      if (nextDimension !== dimension) {
        dimension = nextDimension;
        canvas.width = dimension;
        canvas.height = dimension;
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, dimension, dimension);
      ctx.setTransform(dimension / 64, 0, 0, dimension / 64, 0, 0);
      MODE_DRAWS[preset.mode](ctx, 64, time * preset.speed, false, preset.opts);
    };
    const tick = (now: number) => {
      draw(now / 1000);
      if (running) frame = requestAnimationFrame(tick);
    };
    const sync = () => {
      cancelAnimationFrame(frame);
      running = visible && !document.hidden && !motion.matches && !paused;
      draw(motion.matches || paused ? 0.6 : performance.now() / 1000);
      if (running) frame = requestAnimationFrame(tick);
    };
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting;
      sync();
    });
    observer.observe(canvas);
    const resize = new ResizeObserver(sync);
    resize.observe(canvas);
    document.addEventListener("visibilitychange", sync);
    motion.addEventListener("change", sync);
    sync();
    return () => {
      running = false;
      cancelAnimationFrame(frame);
      observer.disconnect();
      resize.disconnect();
      document.removeEventListener("visibilitychange", sync);
      motion.removeEventListener("change", sync);
    };
  }, [selected.state, paused]);

  return (
    <div className="orb-studio">
      <div className="orb-stage">
        <span className="orb-coordinate" aria-hidden="true">
          echo / in motion
        </span>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`${selected.title}: animated dotted orb`}
          className="hero-orb"
        />
        <button
          className="motion-toggle"
          aria-pressed={paused}
          onClick={() => setPaused(!paused)}
        >
          {paused ? "Resume motion" : "Pause motion"}
        </button>
      </div>
      <div
        className="orb-controls"
        role="group"
        aria-label="Choose an orb animation"
      >
        {states.map((item, index) => (
          <button
            key={item.state}
            aria-pressed={index === active}
            onClick={() => setActive(index)}
          >
            {item.title}
          </button>
        ))}
      </div>
      <p className="orb-description" aria-live="polite">
        {selected.detail}
      </p>
    </div>
  );
}

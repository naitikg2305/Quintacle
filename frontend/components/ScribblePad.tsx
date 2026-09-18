"use client";

import { useRef, useState } from "react";

type Props = {
  onUse: (file: File) => void;
};

// A simple in-app sketch surface — draw with mouse/finger, turn it into a
// PNG, and it feeds through the exact same drop pipeline as any other photo
// (vision description -> classification -> review). For scribbles made
// elsewhere (paper, a real whiteboard), just photograph and drop those —
// this only covers the "draw directly in the app" case.
export default function ScribblePad({ onUse }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const last = useRef<{ x: number; y: number } | null>(null);
  const [hasDrawn, setHasDrawn] = useState(false);

  function pos(e: React.PointerEvent<HTMLCanvasElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function start(e: React.PointerEvent<HTMLCanvasElement>) {
    drawing.current = true;
    last.current = pos(e);
  }

  function move(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!drawing.current) return;
    const ctx = canvasRef.current?.getContext("2d");
    const p = pos(e);
    if (ctx && last.current) {
      ctx.strokeStyle = "#000";
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(last.current.x, last.current.y);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();
    }
    last.current = p;
    setHasDrawn(true);
  }

  function stop() {
    drawing.current = false;
    last.current = null;
  }

  function clear() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    setHasDrawn(false);
  }

  function use() {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (blob) onUse(new File([blob], "scribble.png", { type: "image/png" }));
    }, "image/png");
  }

  return (
    <div className="space-y-2">
      <canvas
        ref={canvasRef}
        width={600}
        height={300}
        className="border rounded bg-white w-full touch-none"
        style={{ maxWidth: "100%", height: "auto", aspectRatio: "2 / 1" }}
        onPointerDown={start}
        onPointerMove={move}
        onPointerUp={stop}
        onPointerLeave={stop}
      />
      <div className="flex gap-2">
        <button onClick={clear} className="border rounded px-3 py-1 text-sm">
          Clear
        </button>
        <button
          onClick={use}
          disabled={!hasDrawn}
          className="border rounded px-3 py-1 text-sm disabled:opacity-40 ml-auto"
        >
          Use this drawing
        </button>
      </div>
    </div>
  );
}

import type { NextConfig } from "next";

// CAPACITOR_BUILD=true switches this to a static export (plain HTML/CSS/JS,
// no Node server) for bundling into the Android app via Capacitor. Regular
// `next dev` / `next build` / `next start` are unaffected.
const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

const nextConfig: NextConfig = {
  ...(isCapacitorBuild
    ? {
        output: "export",
        // 2026-11-05: the phone's Ollama (scripts/termux) pulls qwen3:4b, not
        // the desktop's qwen3:8b — bake it as the chat picker's default
        // (lib/api.ts DEFAULT_LOCAL_MODEL). An explicit env value still wins.
        env: {
          NEXT_PUBLIC_DEFAULT_LOCAL_MODEL:
            process.env.NEXT_PUBLIC_DEFAULT_LOCAL_MODEL || "local:qwen3:4b",
        },
      }
    : {}),
};

export default nextConfig;

import type { NextConfig } from "next";

// CAPACITOR_BUILD=true switches this to a static export (plain HTML/CSS/JS,
// no Node server) for bundling into the Android app via Capacitor. Regular
// `next dev` / `next build` / `next start` are unaffected.
const isCapacitorBuild = process.env.CAPACITOR_BUILD === "true";

const nextConfig: NextConfig = {
  ...(isCapacitorBuild ? { output: "export" } : {}),
};

export default nextConfig;

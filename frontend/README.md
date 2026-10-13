This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Android (Capacitor)

This frontend can also be packaged as an installed Android app (no Node
server on-device, no Play Store) via Capacitor, wrapping a static export of
the same UI. See `docs/android-apk-migration.md` for the full plan. The app
expects a FastAPI backend reachable at `http://localhost:8000` (e.g. the
Termux-hosted backend on the same phone).

```bash
npm run android:build   # static export (out/) + npx cap sync android
npm run android:open    # opens frontend/android/ in Android Studio
```

`android:build` does, in order:
1. `rm -rf out`
2. `CAPACITOR_BUILD=true next build` — builds a static export (`output:
   'export'` in `next.config.ts`, gated behind `CAPACITOR_BUILD` so plain
   `next dev`/`next build`/`next start` are unaffected) into `out/`.
3. `npx cap sync android` — copies `out/` into
   `android/app/src/main/assets/public` and syncs native Capacitor plugin
   config.

From there, building the actual `.apk` is a native Android step run outside
Node: `cd android && ./gradlew assembleDebug` (needs a JDK + Android SDK
installed; not part of this repo's tooling). The resulting debug APK is
fine for personal sideloading.

`android/app/src/main/res/xml/network_security_config.xml` allows cleartext
HTTP to `localhost`/`127.0.0.1` only — Android blocks plaintext HTTP by
default on modern API levels, but loopback-only traffic to the on-device
backend doesn't need TLS.

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.

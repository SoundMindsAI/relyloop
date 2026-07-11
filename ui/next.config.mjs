// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Required for the multi-stage Docker build (ui/Dockerfile) — the runner
  // stage starts the app via `node server.js`, which Next.js only emits when
  // standalone output is enabled. Has no effect on `pnpm dev` / `pnpm build`
  // outside Docker.
  output: "standalone",
  // Baseline security headers. RelyLoop's UI is a no-auth control plane on
  // localhost whose buttons trigger real side effects (Open PR, launch study,
  // demo reset), so clickjacking protection is the load-bearing one: without
  // `frame-ancestors 'none'` a malicious page could iframe the UI and trick
  // the operator into clicking a live action. The CSP here is intentionally
  // frame-only — a full script/style CSP is deferred to GA hardening so it can
  // be authored against the real asset inventory without breaking Turbopack's
  // inline styles/scripts.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
        ],
      },
    ];
  },
};

export default nextConfig;

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
  // the operator into clicking a live action.
  //
  // Security audit 2026-07-11 finding #5: the CSP now enforces the directives
  // that are guaranteed safe for this app — `object-src 'none'` (no plugin
  // XSS), `base-uri 'self'` (no <base> hijack), `form-action 'self'` (no form
  // exfiltration), plus the existing `frame-ancestors 'none'`. A full
  // `script-src`/`style-src` policy is shipped as **report-only** rather than
  // enforcing: an enforcing `script-src 'self'` breaks Turbopack's dev-mode
  // `eval` and Next's inline hydration bootstrap unless per-request nonces are
  // wired (a larger GA-hardening change). Report-only makes violations
  // observable in the console without breaking the app, so the policy can be
  // tightened to enforcing once nonces + the real connect-src origin are wired.
  async headers() {
    const enforcedCsp = [
      "frame-ancestors 'none'",
      "object-src 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ");
    const reportOnlyCsp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: blob:",
      "font-src 'self' data:",
      "connect-src 'self'",
      "object-src 'none'",
      "base-uri 'self'",
      "frame-ancestors 'none'",
    ].join("; ");
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Content-Security-Policy", value: enforcedCsp },
          { key: "Content-Security-Policy-Report-Only", value: reportOnlyCsp },
        ],
      },
    ];
  },
};

export default nextConfig;

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Required for the multi-stage Docker build (ui/Dockerfile) — the runner
  // stage starts the app via `node server.js`, which Next.js only emits when
  // standalone output is enabled. Has no effect on `pnpm dev` / `pnpm build`
  // outside Docker.
  output: "standalone",
};

export default nextConfig;

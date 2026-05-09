/**
 * Placeholder home page (infra_foundation Story 1.3).
 *
 * Replaced by feat_studies_ui's real shell (sidebar nav + dashboards) when that
 * feature lands. For MVP1 bootstrap, this proves the Next.js + Tailwind + TypeScript
 * toolchain is wired and `pnpm dev` serves a renderable page.
 */
export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">RelyLoop is running</h1>
      <p className="max-w-prose text-sm text-gray-600 sm:text-base">
        Open-source automated relevance tuning for enterprise search platforms.
      </p>
      <a
        className="text-blue-600 underline-offset-4 hover:underline"
        href="https://github.com/SoundMindsAI/relyloop/tree/main/docs"
        rel="noopener noreferrer"
        target="_blank"
      >
        See docs/ for getting started →
      </a>
    </main>
  );
}

// Ambient module declaration for plain CSS side-effect imports.
//
// TypeScript 6.0 introduced a stricter check on side-effect imports
// (``import "./globals.css";``) — without a type declaration TS emits
// ``error TS2882: Cannot find module or type declarations for side-effect
// import of './globals.css'``. Next.js handles the actual loading via its
// webpack pipeline; this file only satisfies the type checker.
//
// Scoped to plain ``.css`` side-effect imports; CSS-modules (``*.module.css``)
// already have type declarations shipped via ``next-env.d.ts``.

declare module "*.css";

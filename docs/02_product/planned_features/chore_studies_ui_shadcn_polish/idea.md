# Idea — chore_studies_ui_shadcn_polish

**Date:** 2026-05-12
**Origin:** Surfaced during `feat_studies_ui` Epic 1 phase-gate review (GPT-5.5 findings F1 + F2). Two shadcn primitives were listed in the implementation plan but implemented with simpler alternatives that pass tests but diverge from the plan's "uniform shadcn primitives" intent.

## What's deferred

1. **`ui/src/components/ui/navigation-menu.tsx`** — Plan called for the shadcn `<NavigationMenu>` primitive in TopNav. Story 1.2 shipped a plain `<nav><ul><li><Link>` structure. The simpler version works, has full keyboard nav, and a11y labels; but visual consistency with later modals/popovers (which DO use radix primitives) may be off.

2. **`ui/src/components/ui/select.tsx`** — Plan called for the shadcn `<Select>` primitive in CursorPaginator (page-size dropdown). Story 1.3 shipped a native `<select>`. This works but doesn't match the shadcn visual style. When Story 3.3 (create-study modal) is implemented, it WILL need the shadcn Select — at that point the page-size selector should be migrated for consistency.

## Why deferred

- Both findings are Medium severity; tests pass; visual styling matches enough for MVP1.
- Adding the primitives requires `@radix-ui/react-navigation-menu` and `@radix-ui/react-select` deps, plus a small amount of styling glue.
- Out of scope to keep Epic 1 focused; Story 3.3 will reintroduce shadcn Select naturally.

## Proposed scope (when this idea graduates)

1. `npx shadcn@latest add navigation-menu select` to fetch the canonical primitives.
2. Refactor `ui/src/components/layout/top-nav.tsx` to use `NavigationMenu` / `NavigationMenuList` / `NavigationMenuItem` / `NavigationMenuLink`, preserving the `data-active` / `aria-current` test contract.
3. Refactor `ui/src/components/common/cursor-paginator.tsx` page-size to use `Select`.
4. Re-run tests; visual smoke at `pnpm dev`.

## References

- Implementation plan §UI Guidance "Modal pattern" + Story 1.2 New files table
- Story 1.3's commit message already noted the Select deferral
- shadcn upstream: https://ui.shadcn.com/docs/components/navigation-menu

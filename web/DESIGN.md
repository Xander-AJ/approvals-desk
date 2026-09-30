# Console design notes

Direction: dense ops console, "ledger" palette (cool paper, ink, one deep-green accent).

- Tokens live in `app/globals.css`. Colour is reserved for meaning: `--s-*` pairs (fg/bg) per approval state
  (pending amber, ok green, info blue, bad red, comp violet, idle grey). Accent green = the primary action.
- Type: Geist for UI, Geist Mono (`.num`) for every amount, id and timestamp so columns align.
- Primitives are in `components/ui.tsx` (`StateBadge`, `Money`, `RiskMeter`, `Card`, `PageHeader`, `Skeleton`,
  `EmptyState`, button/input classes). Add to it rather than inlining colours.
- Dark mode follows the OS, with a manual override stored in `localStorage` (`data-theme`).
- e2e depends on: `data-testid="state-badge"`, button names (Approve, Edit amount, Reject, ...), and `ol` for the
  audit timeline. Change them together with `e2e/approvals.spec.ts`.


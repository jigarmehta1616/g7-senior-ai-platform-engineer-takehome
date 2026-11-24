---
name: frontend-console
description: Build or change the Support Console UI in frontend/ (React 18 + TypeScript + Tailwind CSS 4, built with Vite and served by the API at /console/). Use for new screens, components, API calls from the browser, error display, theming, accessibility or responsive layout.
---

# Frontend console playbook

## Stack and layout
React 18, TypeScript (strict), Tailwind CSS 4 via `@tailwindcss/vite`, Vite 5, ESLint 10 with
typescript-eslint strict type-checked rules and React hooks v7. Exact versions are pinned.
```
frontend/src/
  types/              ALL types and interfaces live here, one file per concern:
                      api (wire types mirroring openapi.yaml), client, session, toast, ui (component
                      props), hooks, cases, customers, resilience, app
  api/client.ts       PlatformClient: the ONLY place that calls fetch; ApiError wraps problem+json
  app/                SessionContext/SessionProvider/useSession, ToastContext/ToastProvider/useToast
  components/         reusable, single-purpose: Button, Badge, Card, Kpi, Field, Locked, PriorityLabel,
                      Alert, DataTable<T>, Drawer, Tabs<Id>  (import from "components" barrel)
  hooks/              useLoader (fetch with stale-response protection), useEscapeKey
  lib/format.ts       humanize, formatNumber, formatCurrency, formatDateTime, formatTime, formatHours
  layout/             Header, StatusBar
  features/<area>/    one folder per screen: cases, customers, audit, resilience
```

## Rules
- **Types go in `src/types/`.** No `interface`/`type` declarations inside component files.
- **Reuse components.** Tables use `DataTable<T>` with typed `Column<T>[]`; side panels use `Drawer`;
  status text uses `Badge`/`Alert`. Add a new shared component before copying markup twice.
- **No inline CSS.** No `style=` props and no CSS-in-JS. Use Tailwind utilities and the tokens in
  `src/index.css` (`bg-surface`, `text-muted`, `border-line`, `text-bad`…). Charts use SVG attributes.
- **No `dangerouslySetInnerHTML`.** Case subjects and comments are untrusted and render as text.
- **Data fetching:** use `useLoader(memoisedLoader, toast.fail)`. Never set state synchronously inside
  an effect (the React hooks lint rule enforces this). Pages are keyed by persona, so switching user
  remounts them.
- All requests go through `api` in `api/client.ts`; errors go to `toast.fail(error)`.
- Writes: comments send one `crypto.randomUUID()` Idempotency-Key per intent; escalation sends
  `If-Match` with the ETag from the last GET, reloads on 412, and uses a two-step confirm button.
- Field-level authorization: fields in `redactedFields` render `<Locked scope="…"/>`, never an empty value.

## Build and security
- `vite.config.ts` sets `base: "/console/"` and injects a strict CSP at **build** time only.
- Dev: `npm run dev` on :5173 proxies `/v1`, `/dev`, `/readyz` to the API on :8080.

## Verify
```
cd frontend
rtk npm run check                     # eslint --max-warnings 0 + tsc --noEmit + vite build
grep -rn "style=" src index.html      # must print nothing
```
Then open http://localhost:8080/console/ and check: no browser console messages, the Sample question
returns 4 customers, and Customer 360 shows the degraded banner after `usage -> error` in the Resilience lab.

# Aspect Drilldown — Page Deep-Dive

Dynamic route `/aspects/:aspect` — when the analyst clicks an aspect on Brand Health, they land here to see the last 14 days of volume + a paginated post list for that single aspect.

- **URL** — `http://localhost:3001/aspects/delivery_pickup` (example)
- **Frontend page** — [`frontend/src/pages/AspectDrilldown.tsx`](../../../frontend/src/pages/AspectDrilldown.tsx)
- **Backend route** — [`src/dashboard/api.py`](../../../src/dashboard/api.py) → `GET /api/aspects/{aspect}/detail`

---

## Section 1 — Cheat sheet

- Single API call: `getAspectDetail(aspect, days=14, limit, range)`.
- Range is kept in the URL (`?range=week`) so links stay shareable.
- Two visuals: 14-day LineChart of `total_posts` + a table of matching posts (up to `limit`).
- `limit` dropdown lets the analyst load 10 / 25 / 50 / 100 / 200 posts.

---

## Section 2 — File map

```
AspectDrilldown.tsx
+-- AspectDrilldown()   -- exported page component
+-- inline JSX          -- header + range dropdown + trend chart + posts card
```

Recharts primitives used: `LineChart` + `Line` with a yellow active-dot for hover.

---

## Section 3 — What happens on route entry

```mermaid
flowchart TD
    A["User clicks aspect link on Brand Health or types URL"] --> B["React Router mounts AspectDrilldown"]
    B --> C["useParams reads aspect name from path"]
    C --> D["useSearchParams reads range query"]
    D --> E["useState sets range and limit"]
    E --> F["First render happens"]
    F --> G["useEffect one -- getAspectDetail"]
    F --> H["useEffect two -- syncs range back to URL"]
    G --> I["setData with trend and posts arrays"]
    I --> J["Second render -- chart and table appear"]
```

---

## Section 4 — What React renders

```mermaid
flowchart TD
    A["Guard: if no aspect param return empty message"] --> B["Header: aspect name capitalised + range dropdown"]
    B --> C["Card: 14-Day Trend LineChart of total_posts"]
    C --> D["Card: Posts table with limit dropdown"]
    D --> E["Each row shows title + subreddit + timestamp + sentiment badge"]
```

---

## Section 5 — Data flow

```mermaid
flowchart LR
    A["getAspectDetail response"] --> B["trend array of day + total_posts"]
    A --> C["posts array with title subreddit sentiment timestamp"]
    A --> D["returned + limit"]
    B --> E["LineChart on 14-Day Trend card"]
    C --> F["Posts table"]
    D --> G["Result count label"]
```

Backend origin: [api.py](../../../src/dashboard/api.py) → `GET /api/aspects/{aspect}/detail` runs an inline SQL over `analyses` joined with `raw_posts` filtered by `aspects` JSON-path contains `aspect`.

---

## Section 6 — User actions

- **Range dropdown** — 1h through 90d. On change, the range is written to the URL (`?range=...`) AND the data is reloaded.
- **Limit dropdown** — controls how many posts come back. Reloads immediately.
- **Back button** — browser back returns to Brand Health with all filters intact.

Follow the code:

- Data fetch effect — [AspectDrilldown.tsx#L48-L55](../../../frontend/src/pages/AspectDrilldown.tsx#L48-L55)
- URL sync effect — [AspectDrilldown.tsx#L57-L62](../../../frontend/src/pages/AspectDrilldown.tsx#L57-L62)

---

## Section 7 — Full call chain (Router -> React -> API -> SQL -> back)

```mermaid
flowchart TD
    A["USER clicks aspect on Brand Health"] --> B["React Router navigate<br/>/aspects/:aspect?range=..."]
    B --> C["FRONTEND: AspectDrilldown.tsx<br/>useParams + useSearchParams<br/>useEffect -> getAspectDetail"]
    C --> D["FRONTEND API client:<br/>getAspectDetail(aspect, 14, limit, range)"]
    D --> E["BACKEND FastAPI:<br/>GET /api/aspects/{aspect}/detail"]
    E --> F["Inline SQL over analyses + raw_posts<br/>filter by aspect JSON path"]
    F --> G["SQLite: data/local.db"]
```

---

## Section 8 — File map table

| Layer | File | Symbol |
|---|---|---|
| **UI page** | [AspectDrilldown.tsx](../../../frontend/src/pages/AspectDrilldown.tsx) | `AspectDrilldown()` |
| **API client** | [frontend/src/api.ts](../../../frontend/src/api.ts) | `getAspectDetail` |
| **API route** | [api.py](../../../src/dashboard/api.py) | `GET /api/aspects/{aspect}/detail` |

---

## Section 9 — UI stack

- **Recharts** — `LineChart` + `Line` for 14-day trend
- **react-router-dom** — `useParams`, `useSearchParams` for aspect + range
- **Tailwind** — Card, header, badges
- No icons on this page

---

## Section 10 — Common questions

**Q. Why is the trend always 14 days regardless of the range dropdown?**
Range controls the *post list* filter only. The trend chart is hard-coded to 14 days so the analyst always sees the same time depth for shape comparison across aspects.

**Q. What happens if the aspect param is unknown?**
Backend returns an empty `trend` and empty `posts`. Chart is flat, table shows "0 results". No error.

**Q. Why keep range in the URL?**
Shareable links. Product manager can send a Slack link like `/aspects/delivery_pickup?range=month` and the recipient lands on the exact same view.

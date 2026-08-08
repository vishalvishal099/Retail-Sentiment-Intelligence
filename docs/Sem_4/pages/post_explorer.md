# Post Explorer — Page Deep-Dive

Free-form search UI at `/posts`. Filter the analysed-post archive by subreddit, sentiment, aspect, trust score, or range. Used as the drill-through target from Brand Health and Aspect Drilldown.

- **URL** — `http://localhost:3001/posts`
- **Frontend page** — [`frontend/src/pages/PostExplorer.tsx`](../../../frontend/src/pages/PostExplorer.tsx)
- **Backend route** — [`src/dashboard/api.py`](../../../src/dashboard/api.py) → `GET /api/posts`

---

## Section 1 — Cheat sheet

- Single API call: `getPosts({ limit, subreddit, sentiment, aspect, trust_min, range })`.
- All filter state lives in the URL query — shareable / bookmarkable.
- Auto-search fires on first mount (using URL params). After that, search is manual (Search button).
- Result row limit: 10 / 25 / 50 / 100 / 200 / 500 (dropdown).

---

## Section 2 — File map

```
PostExplorer.tsx
+-- PostExplorer()   -- exported page
+-- inline JSX       -- active-filter pills + filters card + results card
```

Uses the `Card` and `Button` components from `frontend/src/components/`.

---

## Section 3 — Page-load flow

```mermaid
flowchart TD
    A["User opens /posts or drills in from another page"] --> B["Router mounts PostExplorer"]
    B --> C["useSearchParams reads subreddit sentiment aspect trust_min range limit"]
    C --> D["useState initialises filters from URL"]
    D --> E["First render happens"]
    E --> F["useEffect on mount -- runSearch filters"]
    F --> G["api.getPosts params"]
    G --> H["setPosts + setTotal"]
    H --> I["Render active-filter pills + results table"]
```

---

## Section 4 — What React renders

```mermaid
flowchart TD
    A["Header: title + active-filter pills"] --> B["Filters card: subreddit + sentiment + aspect + trust_min + range + limit + Search button"]
    B --> C["Results card"]
    C --> D{"posts empty?"}
    D -->|yes| E["Empty state"]
    D -->|no| F["Rows: title + subreddit link + sentiment badge + aspect tags + trust score"]
```

---

## Section 5 — Data flow

```mermaid
flowchart LR
    A["URL query params"] --> B["useState filters"]
    B --> C["runSearch"]
    C --> D["api.getPosts params"]
    D --> E["ExplorerPost array"]
    D --> F["total count optional"]
    E --> G["Results rows"]
    F --> H["Result count label"]
    B --> I["Active-filter pills in header"]
```

---

## Section 6 — User actions

- **Search button** — writes current `filters` to the URL and re-runs `getPosts`.
- **Change any input** — updates local state only; user must click Search to apply.
- **Click sentiment badge / aspect tag** — could navigate to related view (not currently wired).

Follow the code:

- Auto-search on mount — [PostExplorer.tsx#L57-L60](../../../frontend/src/pages/PostExplorer.tsx#L57-L60)
- `runSearch` — [PostExplorer.tsx#L38-L55](../../../frontend/src/pages/PostExplorer.tsx#L38-L55)
- `handleSearch` — [PostExplorer.tsx#L62-L67](../../../frontend/src/pages/PostExplorer.tsx#L62-L67)

---

## Section 7 — Full call chain (URL params -> React -> API -> SQL -> back)

```mermaid
flowchart TD
    A["USER clicks Search or drills in from Brand Health"] --> B["FRONTEND: PostExplorer.tsx<br/>handleSearch or auto-search on mount"]
    B --> C["FRONTEND API client:<br/>api.getPosts(params)"]
    C --> D["BACKEND FastAPI:<br/>GET /api/posts<br/>builds SQL WHERE clause"]
    D --> E["STORAGE: store.py<br/>SELECT from analyses joined raw_posts<br/>filters: subreddit range sentiment aspect trust_min"]
    E --> F["SQLite: data/local.db"]
```

---

## Section 8 — File map table

| Layer | File | Symbol |
|---|---|---|
| **UI page** | [PostExplorer.tsx](../../../frontend/src/pages/PostExplorer.tsx) | `PostExplorer()` |
| **API client** | [frontend/src/api.ts](../../../frontend/src/api.ts) | `getPosts` |
| **API route** | [api.py](../../../src/dashboard/api.py) | `GET /api/posts` |
| **DB tables** | `data/local.db` | `raw_posts`, `analyses` |

---

## Section 9 — UI stack

- No charts.
- Native `<input>` / `<select>` for filters.
- Card + Button primitives.

---

## Section 10 — Common questions

**Q. Why manual Search instead of live-filter?**
Live-filter would hit the API on every keystroke. Analyst is usually building a specific query (e.g. "walmart + negative + delivery_pickup + last 7d") and wants to fire it once.

**Q. Why do URL query params drive state?**
Shareable links — the drill-through from Brand Health sends `/posts?sentiment=negative&range=today` and this page picks that up on first mount.

**Q. Is there full-text search on the post body?**
Not on this page. This is faceted search only. Full-text search over post bodies would require an FTS index on `raw_posts.data` — not built yet.

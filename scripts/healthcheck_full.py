"""Quick health check on data, API, and frontend."""
import json
import sqlite3
import sys
import urllib.error
import urllib.request


def get(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, str(e)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# 1. Database
section("DATABASE")
db = sqlite3.connect("data/local.db")
for t in ("raw_posts", "analyses", "aggregates", "alerts", "cursors"):
    total = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    extra = ""
    if t == "raw_posts":
        real = db.execute(
            "SELECT COUNT(*) FROM raw_posts WHERE id LIKE 'reddit_%' AND id NOT LIKE 'reddit_c_%'"
        ).fetchone()[0]
        extra = f"  (real posts: {real})"
    elif t == "analyses":
        real = db.execute(
            "SELECT COUNT(*) FROM analyses WHERE id LIKE 'analysis_reddit_%'"
        ).fetchone()[0]
        extra = f"  (real analyses: {real})"
    print(f"  {t:12s} {total}{extra}")

section("REAL ANALYSES BY SUBREDDIT")
rows = db.execute(
    "SELECT json_extract(data,'$.subreddit') AS sub, COUNT(*) "
    "FROM analyses WHERE id LIKE 'analysis_reddit_%' "
    "GROUP BY sub ORDER BY 2 DESC"
).fetchall()
for sub, n in rows:
    print(f"  {sub:25s} {n}")

section("REAL SENTIMENT DISTRIBUTION")
rows = db.execute(
    "SELECT json_extract(data,'$.sentiment') AS s, COUNT(*) "
    "FROM analyses WHERE id LIKE 'analysis_reddit_%' "
    "GROUP BY s ORDER BY 2 DESC"
).fetchall()
for s, n in rows:
    print(f"  {s:10s} {n}")

# 2. API
section("API (http://localhost:8000)")
checks = [
    ("/health", None),
    ("/api/brand-health", "total_posts"),
    ("/api/alerts", None),
    ("/api/posts?limit=3", None),
    ("/api/aspects", None),
    ("/api/trust-stats", None),
]
for path, key in checks:
    code, body = get(f"http://localhost:8000{path}")
    if code == 200:
        try:
            data = json.loads(body)
            if isinstance(data, list):
                summary = f"list[{len(data)}]"
            elif isinstance(data, dict):
                if "alerts" in data and isinstance(data["alerts"], list):
                    summary = f"alerts={len(data['alerts'])}"
                elif "posts" in data and isinstance(data["posts"], list):
                    summary = f"posts={len(data['posts'])}"
                elif "aspects" in data and isinstance(data["aspects"], list):
                    summary = f"aspects={len(data['aspects'])}"
                elif key and key in data:
                    summary = f"{key}={data[key]}"
                else:
                    summary = "keys=" + ",".join(list(data.keys())[:5])
            else:
                summary = type(data).__name__
            print(f"  {code} {path:30s} {summary}")
        except Exception as e:
            print(f"  {code} {path:30s} (parse error {e})")
    else:
        print(f"  {code} {path:30s} {body[:80]}")

# 3. Sample alert + brand-health
section("BRAND HEALTH (today)")
code, body = get("http://localhost:8000/api/brand-health")
if code == 200:
    d = json.loads(body)
    sd = d.get("sentiment_distribution", {})
    print(f"  date: {d.get('date')}")
    print(f"  total_posts: {d.get('total_posts')}  trusted: {d.get('trusted_posts')}")
    print(
        f"  sentiment: pos={sd.get('positive', 0):.1%}  "
        f"neg={sd.get('negative', 0):.1%}  neu={sd.get('neutral', 0):.1%}"
    )
    aspects = list(d.get("aspect_breakdown", {}).keys())
    print(f"  aspects: {aspects}")

section("ALERTS")
code, body = get("http://localhost:8000/api/alerts")
if code == 200:
    data = json.loads(body)
    alerts = data.get("alerts", data) if isinstance(data, dict) else data
    print(f"  count: {len(alerts)}")
    for a in alerts[:5]:
        sev = a.get("severity", "?")
        title = a.get("title", "(no title)")
        print(f"  - [{sev}] {title}")

# 4. Frontend
section("FRONTEND (http://localhost:3000)")
code, body = get("http://localhost:3000/")
if code == 200:
    has_root = '<div id="root"' in body
    has_vite = "/@vite/client" in body
    print(f"  HTTP 200, has #root={has_root}, vite-client={has_vite}")
else:
    print(f"  HTTP {code}")

print()

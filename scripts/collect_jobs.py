#!/usr/bin/env python3
"""Refresh only publicly advertised jobs from configured Greenhouse boards."""
import concurrent.futures
import datetime as dt
import html
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = json.loads((ROOT / "companies.json").read_text())
SEEN_FILE = ROOT / "seen_jobs.json"
OUTPUT = ROOT / "site/jobs.json"
seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
include = re.compile(r"sales|account|business development|provider|physician|pharma|health|clinical|scientific|client success|customer success|consult|medical|pharmacy|operations|partner|commercial|territory|education|analyst|implementation|market", re.I)
exclude = re.compile(r"engineer|software developer|registered nurse|nurse practitioner|physician assistant|physician$|surgeon|chief |vice president|lawyer|attorney|warehouse|security officer", re.I)
outside = re.compile(r"\b(canada|london|united kingdom|germany|france|india|australia|toronto|vancouver|mexico|singapore|poland|europe|berlin)\b", re.I)
def collect(source):
    name, token = source["name"], source["token"]
    try:
        url = "https://boards-api.greenhouse.io/v1/boards/" + token + "/jobs?content=true"
        req = urllib.request.Request(url, headers={"User-Agent": "MedPath public job research", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=16) as response:
            rows = json.load(response).get("jobs", [])
        results = []
        for row in rows:
            title = str(row.get("title", ""))
            if not include.search(title) or exclude.search(title):
                continue
            place = row.get("location") or {}
            place = place.get("name", "") if isinstance(place, dict) else str(place)
            if outside.search(place) and not re.search(r"united states|\bUSA\b|\bU\.S\.", place, re.I):
                continue
            link = row.get("absolute_url") or ""
            if not isinstance(link, str) or not link.startswith("https://"):
                continue
            identity = token + ":" + str(row.get("id"))
            if identity.endswith(":None"):
                continue
            desc = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(row.get("content") or ""))).strip()[:1700]
            results.append({"id": identity, "company": name, "title": title, "location": place or "Not specified", "url": link, "description": desc, "updated": str(row.get("updated_at") or "")[:10], "first_seen_at": seen.setdefault(identity, now), "source": "Greenhouse public job board"})
        return results, {"company": name, "ok": True, "total": len(rows), "matched": len(results)}
    except Exception as exc:
        return [], {"company": name, "ok": False, "error": str(exc)[:160]}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(collect, SOURCES))
jobs = [job for batch, _ in results for job in batch]
jobs.sort(key=lambda job: (job["first_seen_at"], job["updated"]), reverse=True)
status = [info for _, info in results]
ok = sum(1 for info in status if info["ok"])
payload = {"generated_at": now, "jobs": jobs, "stats": {"configured": len(SOURCES), "successful": ok, "failed": len(SOURCES) - ok, "matches": len(jobs)}, "feed_status": status}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
# Preserve the previous published jobs if all sources fail; publish the error state.
if ok == 0 and OUTPUT.exists():
    previous = json.loads(OUTPUT.read_text())
    payload["jobs"] = previous.get("jobs", [])
    payload["stats"]["matches"] = len(payload["jobs"])
    payload["warning"] = "All feed requests failed; displaying prior results which may be stale."
OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
SEEN_FILE.write_text(json.dumps(seen, indent=2))
print(f"Scanned {len(SOURCES)} boards: {ok} succeeded, {len(jobs)} matching jobs")

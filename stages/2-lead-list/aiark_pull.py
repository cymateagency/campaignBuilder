"""AI Ark: count a search, then export it with emails.

  python stages/2-lead-list/aiark_pull.py count  <run_dir>                     # People Search, size 1 -> total (shows cost before export)
  python stages/2-lead-list/aiark_pull.py export <run_dir> [--max N] [--force] # Export People with Email (~1 credit per contact), poll, download
  python stages/2-lead-list/aiark_pull.py resume <run_dir>                     # keep polling/downloading a started export

Reads <run_dir>/api_body.json. Writes <run_dir>/aiark_raw.jsonl (slim rows) and updates state.json.
If list_spec.json has "segment", every row is tagged with it (octave_copy.py passes it as "Segment: <value>").
`export` never starts a second paid export for the same run: if one is already recorded it resumes it
(use --force only when the CSM approved paying again, e.g. after changing the search).
One export holds at most 10,000 contacts. Larger searches stop with a message: narrow the search or pass --max.
Emails AI Ark returns are verified in real time by BounceBan (per AI Ark docs).
"""
import json, sys, time
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import http, tool_key, optional_tool_key, load_state, save_state, add_spend

BASE = "https://api.ai-ark.com/api/developer-portal/v1"
EXPORT_LIMIT = 10000
MAX_POLL_ERRORS = 10


def H():
    return {"X-TOKEN": tool_key("aiark")}


def slim(p, segment=None):
    pr, co = p.get("profile") or {}, p.get("company") or {}
    cs = co.get("summary") or {}
    e = ((p.get("email") or {}).get("output") or [{}])[0]
    rev = (((co.get("financial") or {}).get("revenue") or {}).get("annual") or {}).get("amount")
    return {"aiark_id": p.get("id"), "first": pr.get("first_name"), "last": pr.get("last_name"), "full": pr.get("full_name"),
            "title": pr.get("title"), "linkedin": (p.get("link") or {}).get("linkedin"),
            "person_location": (p.get("location") or {}).get("default"),
            "company": cs.get("name"), "domain": (co.get("link") or {}).get("domain"),
            "website": (co.get("link") or {}).get("website"), "company_linkedin": (co.get("link") or {}).get("linkedin"),
            "industry": cs.get("industry"), "staff": (cs.get("staff") or {}).get("total"), "revenue": rev,
            "hq": ((co.get("location") or {}).get("headquarter") or {}).get("raw_address"),
            "techs": [t.get("name", "").lower() for t in co.get("technologies") or []],
            "mail": co.get("mail") or [],
            "email": e.get("address"), "email_status": e.get("status"), "email_sub": e.get("subStatus"),
            "mx": (e.get("mx") or {}).get("record"), "mx_provider": (e.get("mx") or {}).get("provider"),
            "email_source": "aiark" if e.get("address") else None,
            "segment": segment}


def _body(d):
    return json.loads((Path(d) / "api_body.json").read_text(encoding="utf-8"))


def _segment(d):
    sp = Path(d) / "list_spec.json"
    return json.loads(sp.read_text(encoding="utf-8")).get("segment") if sp.exists() else None


def count(d):
    body = _body(d)
    body.update({"page": 0, "size": 1})
    st, js = http("POST", f"{BASE}/people", body, H())
    if st != 200:
        sys.exit(f"AI Ark search error {st}: {js}")
    n = js.get("totalElements", 0)
    s = load_state(d); s["stages"]["count"] = {"total": n}; save_state(d, s)
    print(f"{n} contacts match. Export costs about {min(n, EXPORT_LIMIT)} AI Ark credits (1 per matched contact).")
    if n > EXPORT_LIMIT:
        print(f"WARNING: one export holds at most {EXPORT_LIMIT}. Narrow the search, or export only the first "
              f"{EXPORT_LIMIT} with --max {EXPORT_LIMIT} ({n - EXPORT_LIMIT} contacts would not be pulled).")


def export(d, max_n=None, force=False):
    s = load_state(d)
    prev = s.get("stages", {}).get("export") or {}
    if prev.get("trackId") and not force:
        print(f"an export was already started for this run (trackId {prev['trackId']}, state {prev.get('state')}). "
              "Resuming it instead of paying again. Use --force to start a new one.")
        return resume(d)
    total = s.get("stages", {}).get("count", {}).get("total")
    if total is None and not max_n:
        sys.exit("run `count` first so the size and cost are known, or pass --max N")
    if max_n is None and total > EXPORT_LIMIT:
        sys.exit(f"{total} contacts match but one export holds at most {EXPORT_LIMIT}. "
                 f"Narrow the search, or pass --max {EXPORT_LIMIT} to pull only the first {EXPORT_LIMIT}.")
    n = min(int(max_n or total), EXPORT_LIMIT)
    if n <= 0:
        sys.exit("nothing to export (count is 0)")
    body = _body(d)
    body.update({"page": 0, "size": n})
    hook = optional_tool_key("aiark_webhook")  # AI Ark requires it (400 "webhook is required"); we still poll ourselves
    if not hook:
        sys.exit("AI Ark requires a webhook URL for exports. Set airtable.shared_fields.aiark_webhook in config.json "
                 "to the Airtable column that holds it, and fill it in.")
    body["webhook"] = hook
    st, js = http("POST", f"{BASE}/people/export", body, H())
    if st != 200 or not isinstance(js, dict) or not js.get("trackId"):
        sys.exit(f"AI Ark export error {st}: {js}")
    s = load_state(d)
    s["stages"]["export"] = {"trackId": js["trackId"], "requested": n, "state": js.get("state")}
    save_state(d, s)
    print(f"export started for {n} contacts, trackId {js['trackId']}")
    resume(d)


def resume(d):
    s = load_state(d)
    exp = s.get("stages", {}).get("export") or {}
    tid = exp.get("trackId")
    if not tid:
        sys.exit("no export recorded for this run. Run `export` first.")
    if exp.get("state") == "DONE" and (Path(d) / "aiark_raw.jsonl").exists():
        print(f"export already downloaded ({exp.get('rows')} rows) -> aiark_raw.jsonl")
        return
    errors = 0
    while True:
        st, js = http("GET", f"{BASE}/people/export/{tid}/statistics", None, H())
        state = js.get("state") if isinstance(js, dict) else None
        if st == 200 and state == "DONE":
            break
        if st in (403, 404) or state in ("STUCK_HARD_REFUND", "STUCK_SOFT_REFUND", "SEARCH_NO_RESULTS", "NO_EMAILS_FOUND"):
            sys.exit(f"export ended without results: {st} {js} (refunded per AI Ark; resubmit if needed)")
        errors = errors + 1 if st != 200 else 0
        if errors >= MAX_POLL_ERRORS:
            sys.exit(f"AI Ark status check failed {errors} times in a row ({st} {js}). Run `resume` later; the export keeps running.")
        print(f"  {state or st} ... waiting 60s")
        time.sleep(60)
    stats = js.get("statistics", {})
    seg = _segment(d)
    out = Path(d) / "aiark_raw.jsonl"
    rows, page = 0, 0
    with out.open("w", encoding="utf-8") as f:
        while True:
            st, js = http("GET", f"{BASE}/people/export/{tid}/inquiries?page={page}&size=100", None, H())
            if st != 200:
                sys.exit(f"download error page {page}: {st} {js}. Run `resume` to download again (no new credits).")
            for p in js.get("content", []):
                f.write(json.dumps(slim(p, seg)) + "\n"); rows += 1
            if js.get("last", True):
                break
            page += 1
    s = load_state(d)
    first_download = s["stages"]["export"].get("state") != "DONE"
    s["stages"]["export"].update({"state": "DONE", "rows": rows, "statistics": stats})
    save_state(d, s)
    if first_download:  # a re-download of the same export costs nothing
        add_spend(d, "aiark_credits", stats.get("total") or rows)
    print(f"downloaded {rows} contacts ({stats}) -> {out}")


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 3 or a[1] not in ("count", "export", "resume"):
        sys.exit("usage: count|export|resume <run_dir> [--max N] [--force]")
    cmd, d = a[1], a[2]
    mx = int(a[a.index("--max") + 1]) if "--max" in a else None
    {"count": lambda: count(d), "export": lambda: export(d, mx, "--force" in a), "resume": lambda: resume(d)}[cmd]()

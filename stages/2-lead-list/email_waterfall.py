"""Find missing emails and verify, cheapest first. Replaces the Clay waterfall.

  python stages/2-lead-list/email_waterfall.py <run_dir> [--mv-all] [--keep-risky] [--dry-run] [--workers 8]

Find (only contacts with no email):  LeadMagic -> Icypeas
  A found email that is already in the client's campaigns (already_contacted.txt) or already on this list is dropped
  before any verification is paid for.
Verify (every email not already verified by AI Ark; --mv-all includes those): MillionVerifier
  ok -> keep | catch_all / unknown -> BounceBan (deliverable keeps; risky only with --keep-risky) | invalid / disposable -> drop
  A MillionVerifier error (no result) is not sent to BounceBan; the contact is logged as "verify error" and can be retried.
Results are cached in .cache/ (90 days) so nobody pays twice for the same person or email.
The cache and the spend in state.json are saved every 25 contacts and on any exit (crash, Ctrl+C), so a re-run never pays again.
Reads cleaned.jsonl, writes verified.jsonl (deliverable only) and waterfall_log.jsonl.
"""
import json, sys, time, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import http, tool_key, add_spend, set_stage, read_jsonl, write_jsonl, ROOT

CACHE = ROOT / ".cache"; CACHE.mkdir(exist_ok=True)
TTL = 90 * 86400
CHECKPOINT_EVERY = 25
_lock = threading.Lock()


def _cache(name):
    p = CACHE / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


FIND, VERIFY = _cache("find"), _cache("verify")


def _fresh(entry):
    return bool(entry) and time.time() - entry.get("at", 0) < TTL


def leadmagic(r):
    st, js = http("POST", "https://api.leadmagic.io/v1/people/email-finder",
                  {"first_name": r.get("first"), "last_name": r.get("last"), "domain": r.get("domain"),
                   "company_name": r.get("company")}, {"X-API-Key": tool_key("leadmagic")})
    if st == 200 and isinstance(js, dict) and js.get("status") == "valid" and js.get("email"):
        return js["email"].lower(), js.get("credits_consumed", 1)
    return None, (js.get("credits_consumed", 0) if isinstance(js, dict) else 0)


def icypeas(r):
    h = {"Authorization": tool_key("icypeas")}
    st, js = http("POST", "https://app.icypeas.com/api/email-search",
                  {"firstname": r.get("first"), "lastname": r.get("last"), "domainOrCompany": r.get("domain") or r.get("company")}, h)
    sid = ((js or {}).get("item") or {}).get("_id") if isinstance(js, dict) else None
    if not sid:
        return None, 0
    for _ in range(12):
        time.sleep(6)
        st, js = http("POST", "https://app.icypeas.com/api/bulk-single-searchs/read", {"id": sid}, h)
        item = ((js or {}).get("items") or [{}])[0] if isinstance(js, dict) else {}
        status = item.get("status")
        if status in ("DEBITED", "FOUND"):
            ems = ((item.get("results") or {}).get("emails") or [])
            return (ems[0]["email"].lower() if ems else None), 1
        if status in ("DEBITED_NOT_FOUND", "NOT_FOUND", "INSUFFICIENT_FUNDS"):
            if status == "INSUFFICIENT_FUNDS":
                print("Icypeas: out of credits")
            return None, 0
    return None, 0


def millionverifier(email):
    """Result string, or None when the call failed (no credit used, nothing to cache)."""
    q = urllib.parse.urlencode({"api": tool_key("millionverifier"), "email": email, "timeout": 20})
    st, js = http("GET", f"https://api.millionverifier.com/api/v3/?{q}")
    if st != 200 or not isinstance(js, dict) or js.get("error") or not js.get("result"):
        return None
    return js["result"]


def bounceban(email):
    h = {"Authorization": tool_key("bounceban")}
    st, js = http("GET", "https://api.bounceban.com/v1/verify/single?" + urllib.parse.urlencode({"email": email}), None, h)
    js = js if isinstance(js, dict) else {}
    tries = 0
    while js.get("status") == "verifying" and js.get("id") and tries < 8:
        time.sleep(30); tries += 1
        st, js = http("GET", "https://api.bounceban.com/v1/verify/single/status?" + urllib.parse.urlencode({"id": js["id"]}), None, h)
        js = js if isinstance(js, dict) else {}
    return js.get("result") or "unknown", js.get("score")


class Run:
    """Shared state for one waterfall run: spend, log, claimed emails, checkpoints."""

    def __init__(self, d, args, contacted, claimed):
        self.d, self.args, self.contacted, self.claimed = d, args, contacted, claimed
        self.spend, self.saved_spend, self.log, self.done = Counter(), Counter(), [], 0

    def charge(self, tool, n):
        with _lock:
            self.spend[tool] += n

    def checkpoint(self):
        """Write the caches and the spend not yet recorded. Safe to call from any thread."""
        with _lock:
            find_txt, verify_txt = json.dumps(FIND), json.dumps(VERIFY)
            delta = {k: v - self.saved_spend[k] for k, v in self.spend.items() if v - self.saved_spend[k]}
            self.saved_spend.update(delta)
            (CACHE / "find.json").write_text(find_txt, encoding="utf-8")
            (CACHE / "verify.json").write_text(verify_txt, encoding="utf-8")
            for k, v in delta.items():
                add_spend(self.d, k, v)

    def finished_one(self):
        with _lock:
            self.done += 1
            due = self.done % CHECKPOINT_EVERY == 0
        if due:
            self.checkpoint()


def process(r, run):
    args = run.args
    key = (r.get("linkedin") or f"{r.get('first')} {r.get('last')} @{r.get('domain')}").lower()
    found_here = False
    # 1) find
    if not r.get("email"):
        hit = FIND.get(key)
        if _fresh(hit):
            r["email"], r["email_source"] = hit.get("email"), hit.get("source")
        elif not args["dry"]:
            for name, fn in (("leadmagic", leadmagic), ("icypeas", icypeas)):
                em, cost = fn(r)
                run.charge(name, cost)
                if em:
                    r["email"], r["email_source"] = em, name
                    break
            with _lock:
                FIND[key] = {"email": r.get("email"), "source": r.get("email_source"), "at": time.time()}
        found_here = bool(r.get("email"))
    if not r.get("email"):
        run.log.append({"key": key, "result": "no email found"}); return None
    e = r["email"] = r["email"].strip().lower()
    # 1b) a found email may belong to someone already contacted, or to another row of this list
    if found_here:
        if e in run.contacted:
            run.log.append({"key": key, "email": e, "result": "already in a client campaign"}); return None
        with _lock:
            dup = e in run.claimed
            run.claimed.add(e)
        if dup:
            run.log.append({"key": key, "email": e, "result": "duplicate email"}); return None
    # 2) verify
    if r.get("email_source") == "aiark" and r.get("email_status") == "VALID" and not args["mv_all"]:
        r["verify"] = "aiark_valid"; return r
    v = VERIFY.get(e)
    if not _fresh(v) and not args["dry"]:
        mv = millionverifier(e)
        if mv is None:
            run.log.append({"key": key, "email": e, "result": "verify error", "detail": "MillionVerifier gave no result"})
            return None
        run.charge("millionverifier", 1)
        v = {"mv": mv, "at": time.time()}
        if mv in ("catch_all", "unknown"):
            bb, score = bounceban(e)
            run.charge("bounceban", 1)
            v.update({"bb": bb, "bb_score": score})
        with _lock:
            VERIFY[e] = v
    if not v:
        return None
    final = "deliverable" if v.get("mv") == "ok" or v.get("bb") == "deliverable" else (
        "risky" if v.get("bb") == "risky" else "undeliverable")
    r["verify"] = f"mv:{v.get('mv')}" + (f" bb:{v.get('bb')}({v.get('bb_score')})" if v.get("bb") else "")
    run.log.append({"key": key, "email": e, "result": final, "detail": r["verify"]})
    return r if final == "deliverable" or (final == "risky" and args["keep_risky"]) else None


def main(d, args):
    d = Path(d)
    rows = read_jsonl(d / "cleaned.jsonl")
    ac = d / "already_contacted.txt"
    contacted = set(ac.read_text(encoding="utf-8").split()) if ac.exists() else set()
    claimed = {(r.get("email") or "").strip().lower() for r in rows if r.get("email")}
    need_find = sum(1 for r in rows if not r.get("email"))
    print(f"{len(rows)} contacts, {need_find} need an email. Max finder cost: ~{need_find} LeadMagic + up to {need_find} Icypeas credits.")
    run = Run(d, args, contacted, claimed)

    def one(r):
        try:
            return process(r, run)
        finally:
            run.finished_one()

    ex = ThreadPoolExecutor(args["workers"])
    try:
        out = list(ex.map(one, rows))
    except BaseException:
        ex.shutdown(wait=True, cancel_futures=True)  # let running lookups finish so their cost is recorded
        run.checkpoint()
        print(f"stopped early. Cache and spend saved ({dict(run.spend)}); re-run to continue without paying twice.")
        raise
    ex.shutdown()
    run.checkpoint()
    keep = [r for r in out if r]
    write_jsonl(d / "verified.jsonl", keep)
    write_jsonl(d / "waterfall_log.jsonl", run.log)
    src = Counter(r.get("email_source") for r in keep)
    results = Counter(l["result"] for l in run.log)
    set_stage(d, "waterfall", done=not args["dry"], deliverable=len(keep), by_source=dict(src), results=dict(results))
    print(f"deliverable: {len(keep)} of {len(rows)} | by source: {dict(src)} | results: {dict(results)} | spend this run: {dict(run.spend)}")


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        sys.exit("usage: email_waterfall.py <run_dir> [--mv-all] [--keep-risky] [--dry-run] [--workers 8]")
    main(a[1], {"mv_all": "--mv-all" in a, "keep_risky": "--keep-risky" in a, "dry": "--dry-run" in a,
                "workers": int(a[a.index("--workers") + 1]) if "--workers" in a else 8})

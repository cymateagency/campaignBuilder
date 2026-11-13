"""Clean the AI Ark pull before spending on email finding.

  python stages/2-lead-list/clean.py <run_dir> [--title-must REGEX] [--title-not REGEX] [--industry-not REGEX]

Drops: duplicates, already contacted (already_contacted.txt), contacts behind held gateways
(config.json -> held_gateways, matched on MX record, mail field or tech stack), off-target titles.
Keeps contacts with no email: those go to the waterfall (which checks found emails against already_contacted.txt again).
Writes cleaned.jsonl, held.jsonl and prints a drop table.
"""
import json, re, sys
from collections import Counter
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import CONFIG, read_jsonl, write_jsonl, set_stage

# What each gateway looks like in MX records and tech stacks.
GATEWAY_PATTERNS = {
    "proofpoint": (["pphosted", "ppe-hosted", "proofpoint"], ["proofpoint"]),
    "mimecast": (["mimecast"], ["mimecast"]),
    "ironport": (["iphmx", "ironport"], ["cisco ironport", "ironport"]),
}


def _gateway_matchers():
    mx, tech = [], set()
    for g in CONFIG.get("held_gateways") or []:
        m, t = GATEWAY_PATTERNS.get(g.lower(), ([g.lower()], [g.lower()]))
        mx += m
        tech |= set(t)
    return (re.compile("|".join(map(re.escape, mx)), re.I) if mx else None), tech


GATEWAY_RE, GATEWAY_TECHS = _gateway_matchers()


def gateway_hit(r):
    blob = " ".join([r.get("mx") or "", r.get("mx_provider") or "", json.dumps(r.get("mail") or [])])
    return bool(GATEWAY_RE and GATEWAY_RE.search(blob)) or bool(GATEWAY_TECHS & set(r.get("techs") or []))


def person_key(r):
    """Stable id for dedupe. None when the row has nothing to identify the person by (never treated as a duplicate)."""
    if r.get("aiark_id"):
        return f"id:{r['aiark_id']}"
    if r.get("linkedin"):
        return f"li:{r['linkedin'].lower().rstrip('/')}"
    name = f"{r.get('first') or ''} {r.get('last') or ''}".strip().lower()
    if name and (r.get("domain") or r.get("company")):
        return f"nm:{name}@{(r.get('domain') or r.get('company')).lower()}"
    return None


def main(d, must=None, never=None, industry_not=None):
    d = Path(d)
    ac = d / "already_contacted.txt"
    seen = set(ac.read_text(encoding="utf-8").split()) if ac.exists() else set()
    if not ac.exists():
        print("NOTE: no already_contacted.txt (run smartlead_export.py first); nobody is removed as already contacted")
    must_re = re.compile(must, re.I) if must else None
    never_re = re.compile(never, re.I) if never else None
    ind_not_re = re.compile(industry_not, re.I) if industry_not else None
    c, keep, held, dup_people, dup_emails = Counter(), [], [], set(), set()
    for r in read_jsonl(d / "aiark_raw.jsonl"):
        pid = person_key(r)
        e = (r.get("email") or "").strip().lower()
        if (pid and pid in dup_people) or (e and e in dup_emails):
            c["duplicate"] += 1; continue
        if pid:
            dup_people.add(pid)
        if e:
            dup_emails.add(e)
        if e and e in seen:
            c["already in a client campaign"] += 1; continue
        t = r.get("title") or ""
        if (must_re and not must_re.search(t)) or (never_re and never_re.search(t)):
            c["off-target title"] += 1; continue
        if ind_not_re and ind_not_re.search(r.get("industry") or ""):
            c["off-target industry"] += 1; continue
        if gateway_hit(r):
            held.append(r); c["held: gateway"] += 1; continue
        r["email"] = e or None
        keep.append(r); c["kept (with email)" if e else "kept (needs email)"] += 1
    write_jsonl(d / "cleaned.jsonl", keep)
    write_jsonl(d / "held.jsonl", held)
    for k, v in c.most_common():
        print(f"{k:32s} {v}")
    set_stage(d, "clean", done=True, kept=len(keep), held=len(held), drops=dict(c))


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        sys.exit("usage: clean.py <run_dir> [--title-must REGEX] [--title-not REGEX] [--industry-not REGEX]")
    main(a[1], a[a.index("--title-must") + 1] if "--title-must" in a else None,
         a[a.index("--title-not") + 1] if "--title-not" in a else None,
         a[a.index("--industry-not") + 1] if "--industry-not" in a else None)

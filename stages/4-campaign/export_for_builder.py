"""Turn the client-approved copy from stage 3 into the inputs of Jairo's campaign-builder skill.

  python stages/4-campaign/export_for_builder.py <run_dir> --mailboxes-from <campaign_id> --subsequence-from <subsequence_id>
        [--mailbox-ids 1,2,3] [--no-subsequence] [--start-date YYYY-MM-DD] [--max-per-day 444] [--source aiark_us_net_new]
        [--skip-client-approval]

Reads <run_dir>/campaign_spec.json ("type", "name", "signature", "followups", the one slot) and copy.jsonl.
Writes <run_dir>/builder/spec.json (campaign-builder "inline" mode) and <run_dir>/builder/leads.csv.
Then the campaign-builder skill validates, dry-runs, builds the DRAFT (with the goal subsequence) and runs the SOP checklist.

Email 1 = {{Email_Copy}} (each lead's approved email, as HTML so the paragraphs survive) + the Cymate signature
(closer spintax, %sender-firstname%, title, website with a one dot leader so it isn't a link), then {{PS}} when the
framework writes one. Subject = {{Email_Subject}}. Follow ups are the spec's follow ups + the same signature.
Refuses to run before the client approved the current copy (stage 3 approvals.py).
"""
import csv, html, json, re, sys
from datetime import date, timedelta
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "3-copy"))
from common import read_jsonl, set_stage, signature_parts, NO_LINK_DOT
from approvals import require_client_approval

TYPES = ["ColdOutreach", "Podcast", "Signups", "Form", "Partnership", "Webinar", "Referral"]  # reply-agent prefixes
MIN_PER_DAY = 444  # SOP minimum, enforced by campaign-builder


def body_html(text):
    """Plain-text email -> clean HTML: one <div> per line, <br> between paragraphs."""
    text = (text or "").replace("\r\n", "\n").strip()
    paras = [p for p in text.split("\n\n") if p.strip()]
    return "<br>".join("".join(f"<div>{html.escape(ln, quote=False)}</div>" for ln in p.split("\n")) for p in paras)


def html_to_lines(h):
    """Follow up HTML from campaign_spec.json -> campaign-builder lines ("" = blank line)."""
    h = re.sub(r"</div>", "\n", h)  # each div is a line ...
    h = re.sub(r"<br\s*/?>", "\n", h)  # ... and a <br> between divs is a blank line (new paragraph)
    text = html.unescape(re.sub(r"<[^>]+>", "", h))
    lines, blank = [], False
    for ln in text.split("\n"):
        ln = ln.strip()
        if ln:
            lines.append(ln); blank = False
        elif lines and not blank:
            lines.append(""); blank = True
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def signature_lines(spec):
    closers, titles, website = signature_parts(spec)
    spin = lambda xs: xs[0] if len(xs) == 1 else "{" + "|".join(xs) + "}"
    return [f"{spin(closers)},", "%sender-firstname%", spin(titles), website.replace(".", NO_LINK_DOT)]


def next_business_day(today=None):
    d = (today or date.today()) + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.isoformat()


def build(d, client, opts):
    d = Path(d)
    spec = json.loads((d / "campaign_spec.json").read_text(encoding="utf-8"))
    problems = []
    ctype, name = spec.get("type"), spec.get("name", "")
    if ctype not in TYPES:
        problems.append(f'campaign_spec.json "type" must be one of {TYPES} (the client\'s reply-agent type), got {ctype!r}')
    elif not name.startswith(f"{ctype}_"):
        problems.append(f'campaign_spec.json "name" must start with "{ctype}_" (the reply agent routes on it), got {name!r}. '
                        "Format: <type>_<segment>_<titles>_<size>_<geo>_<source>_<month>")
    if len(spec["slots"]) != 1:
        problems.append("one framework per campaign: campaign_spec.json must have exactly one slot")
    if not opts.get("mailbox_ids") and not opts.get("mailboxes_from"):
        problems.append("say which mailboxes: --mailboxes-from <live campaign id> or --mailbox-ids 1,2,3")
    if not opts.get("no_subsequence") and not opts.get("subsequence_from"):
        problems.append("the reply agent needs a goal subsequence: --subsequence-from <the client's existing <type>_Subsequence id> "
                        "(or --no-subsequence only if the CSM says so)")
    if problems:
        sys.exit("can't export for campaign-builder:\n  " + "\n  ".join(problems))
    signature_parts(spec)  # stops if the signature (title, website) isn't set

    src = d / "copy.jsonl"
    if not src.exists():
        sys.exit("no copy.jsonl: run stage 3's full copy run first (octave_copy.py without --test)")
    leads = read_jsonl(src)
    s = list(spec["slots"])[0].lower()
    has_ps = any(l.get(f"ps_{s}") for l in leads)

    email1 = ["{{Email_Copy}}", ""] + signature_lines(spec) + (["", "{{PS}}"] if has_ps else [])
    steps = [{"delay_days": 1, "subject": "{{Email_Subject}}", "body": email1}]
    for fu in spec.get("followups", []):
        lines = html_to_lines(fu["body_html"])
        if not any("%sender" in ln for ln in lines):
            lines += [""] + signature_lines(spec)
        steps.append({"delay_days": fu["delay_days"], "body": lines})

    per_day = int(opts.get("max_per_day") or max(MIN_PER_DAY, int(spec.get("max_new_leads_per_day") or 0)))
    if per_day < MIN_PER_DAY:
        sys.exit(f"max new leads per day must be at least {MIN_PER_DAY} (SOP)")
    out = {
        "_comment": f"Written by stages/4-campaign/export_for_builder.py from {d.as_posix()} (client-approved copy). Build with the campaign-builder skill.",
        "client": client,
        "type": ctype,
        "name": name,
        "schedule": {"start_date": opts.get("start_date") or next_business_day(), "end_hour": spec.get("end_hour", "16:00"),
                     "max_new_leads_per_day": per_day},
        "sequence": {"mode": "inline", "steps": steps},
        "mailboxes": ({"mode": "list", "ids": [int(x) for x in opts["mailbox_ids"].split(",") if x.strip()]}
                      if opts.get("mailbox_ids") else {"mode": "clone", "source_campaign_id": int(opts["mailboxes_from"])}),
        "subsequence": ({"mode": "none"} if opts.get("no_subsequence")
                        else {"mode": "clone", "source_campaign_id": int(opts["subsequence_from"])}),
        "leads": {"csv": "leads.csv", "source": opts.get("source") or spec.get("lead_source") or "aiark",
                  "required_fields": ["Email_Copy", "Email_Subject"]},
    }

    bd = d / "builder"
    bd.mkdir(exist_ok=True)
    (bd / "spec.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cols = ["first_name", "last_name", "email", "company_name", "website", "linkedin_profile", "location",
            "Title", "Email_Subject", "Email_Copy", "PS", "Segment", "Framework", "Copy_Source"]
    with (bd / "leads.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in leads:
            w.writerow({"first_name": r.get("first") or "", "last_name": r.get("last") or "", "email": r.get("email") or "",
                        "company_name": r.get("company") or "", "website": r.get("website") or r.get("domain") or "",
                        "linkedin_profile": r.get("linkedin") or "", "location": r.get("hq") or "", "Title": r.get("title") or "",
                        "Email_Subject": r.get(f"subject_{s}") or "", "Email_Copy": body_html(r.get(f"email_{s}")),
                        "PS": r.get(f"ps_{s}") or "", "Segment": r.get("segment") or "",
                        "Framework": spec["slots"][list(spec["slots"])[0]]["framework"], "Copy_Source": r.get(f"copy_{s}_source") or ""})
    set_stage(d, "builder_export", done=True, spec=str(bd / "spec.json"), leads=len(leads), name=name)
    print(f"wrote {bd / 'spec.json'} and {bd / 'leads.csv'} ({len(leads)} leads, {len(steps)} emails, name {name}). "
          "Next: the campaign-builder skill (validate, dry run, build).")
    return out


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        sys.exit(__doc__)
    arg = lambda k: a[a.index(k) + 1] if k in a else None
    d = a[1]
    require_client_approval(d, "Exporting the campaign for the builder")
    state = json.loads((Path(d) / "state.json").read_text(encoding="utf-8")) if (Path(d) / "state.json").exists() else {}
    build(d, state.get("client") or arg("--client") or "", {
        "mailboxes_from": arg("--mailboxes-from"), "mailbox_ids": arg("--mailbox-ids"),
        "subsequence_from": arg("--subsequence-from"), "no_subsequence": "--no-subsequence" in a,
        "start_date": arg("--start-date"), "max_per_day": arg("--max-per-day"), "source": arg("--source")})

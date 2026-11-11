"""Copy approval loop: the CSM approves the test copy, then the client approves it, round by round.

  python stages/3-copy/approvals.py status         <run_dir>
  python stages/3-copy/approvals.py csm-approve    <run_dir> [--note "..."]   # after reviewing copy_test.md (5+ leads)
  python stages/3-copy/approvals.py client-review  <run_dir>                  # writes client_review.md to send the client
  python stages/3-copy/approvals.py client-feedback <run_dir> "what the client said"
  python stages/3-copy/approvals.py client-approve <run_dir> [--note "..."]

Every approval is tied to the campaign_spec.json version it was given for (its hash). Changing the brief, the
framework or the fallback copy after feedback starts a new round: re-test, CSM approves again, client reviews again.
octave_copy.py (full run) and smartlead_build.py refuse to run until the client approved the current version.
Internal tests can pass --skip-client-approval to those two scripts.
"""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import load_state, save_state, read_jsonl, signature_text

MIN_EXAMPLES = 5


def spec_hash(d):
    return hashlib.sha256((Path(d) / "campaign_spec.json").read_text(encoding="utf-8").encode()).hexdigest()[:16]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _approvals(d):
    s = load_state(d)
    a = s.setdefault("copy_approval", {"round": 1, "history": []})
    return s, a


def client_approved(d):
    """True when the client approved the current campaign_spec.json version."""
    a = load_state(d).get("copy_approval") or {}
    return (a.get("client") or {}).get("spec_hash") == spec_hash(d)


def _tested(d):
    p = Path(d) / "copy_test.jsonl"
    if not p.exists():
        sys.exit("no copy_test.jsonl yet: run octave_copy.py --test 8 first")
    rows = read_jsonl(p)
    h = spec_hash(d)
    if not rows or any(r.get("_spec_hash") != h for r in rows):
        sys.exit("copy_test.jsonl was made with an older campaign_spec.json: re-run octave_copy.py --test before approving")
    if len(rows) < MIN_EXAMPLES:
        sys.exit(f"only {len(rows)} test leads: the CSM reviews at least {MIN_EXAMPLES} (octave_copy.py --test {MIN_EXAMPLES} or more)")
    return rows


def status(d):
    a = load_state(d).get("copy_approval") or {}
    h = spec_hash(d)
    mark = lambda k: "yes (current version)" if (a.get(k) or {}).get("spec_hash") == h else (
        "for an OLDER version" if a.get(k) else "no")
    print(f"round {a.get('round', 1)} | CSM approved: {mark('csm')} | sent to client: {mark('sent')} | client approved: {mark('client')}")
    for h_ in a.get("history", [])[-6:]:
        print(f"  {h_['at']}  {h_['event']}" + (f": {h_['note']}" if h_.get("note") else ""))


def csm_approve(d, note=""):
    _tested(d)
    s, a = _approvals(d)
    a["csm"] = {"spec_hash": spec_hash(d), "at": now(), "note": note}
    a["history"].append({"at": now(), "event": f"round {a['round']}: CSM approved", "note": note})
    save_state(d, s)
    print(f"CSM approved round {a['round']}. Next: approvals.py client-review {d}")


def client_review(d):
    rows = _tested(d)
    s, a = _approvals(d)
    if (a.get("csm") or {}).get("spec_hash") != spec_hash(d):
        sys.exit("the CSM hasn't approved this version yet: approvals.py csm-approve first")
    spec = json.loads((Path(d) / "campaign_spec.json").read_text(encoding="utf-8"))
    signoff = signature_text(spec)
    lines = [f"# Email copy for review: {spec.get('name', '')}", "",
             f"Round {a['round']}. Below are {len(rows)} real examples of the first email, each written for a real prospect. "
             "The opening line is personalized for each company; the rest of the message stays the same across the campaign.",
             "Reply with anything you'd like changed (claims, tone, wording, offers to avoid) or simply approve.", ""]
    for i, r in enumerate(rows, 1):
        for slot in spec["slots"]:
            s_ = slot.lower()
            lines += [f"## Example {i}: {r.get('title')} at {r.get('company')}", "",
                      f"**Subject:** {r.get(f'subject_{s_}')}", "", r.get(f"email_{s_}", "").strip(), "", signoff, ""]
            if r.get(f"ps_{s_}"):
                lines += [r[f"ps_{s_}"], ""]
    fus = spec.get("followups") or []
    if fus:
        import re as _re
        lines += ["## Follow ups (same thread, no new subject)", ""]
        for f in fus:
            txt = _re.sub(r"<br\s*/?>", "\n", f["body_html"])
            txt = _re.sub(r"</div>\s*", "\n", txt)
            txt = _re.sub(r"<[^>]+>", "", txt).replace("{{first_name}}", "<first name>")
            lines += [f"**{f['delay_days']} days later:**", "", txt.strip(), ""]
    out = Path(d) / "client_review.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    a["sent"] = {"spec_hash": spec_hash(d), "at": now()}
    a["history"].append({"at": now(), "event": f"round {a['round']}: client_review.md written for the client"})
    save_state(d, s)
    print(f"wrote {out} ({len(rows)} examples). Send it to the client, then record their answer with client-feedback or client-approve.")


def client_feedback(d, text):
    s, a = _approvals(d)
    fb = Path(d) / "client_feedback.md"
    with fb.open("a", encoding="utf-8") as f:
        f.write(f"## Round {a['round']} ({now()})\n\n{text.strip()}\n\n")
    a["history"].append({"at": now(), "event": f"round {a['round']}: client feedback", "note": text.strip()[:200]})
    a["round"] += 1
    a.pop("client", None)
    save_state(d, s)
    print(f"feedback saved to {fb}. Round {a['round']} starts: update the brief/fallbacks (or the agent for framework issues), "
          "re-run octave_copy.py --test, CSM approves, client-review again.")


def client_approve(d, note=""):
    s, a = _approvals(d)
    h = spec_hash(d)
    if (a.get("sent") or {}).get("spec_hash") != h:
        sys.exit("this version of the copy was never sent to the client (approvals.py client-review first)")
    a["client"] = {"spec_hash": h, "at": now(), "note": note}
    a["history"].append({"at": now(), "event": f"round {a['round']}: client approved", "note": note})
    save_state(d, s)
    print("client approved. Next: octave_copy.py (full run), then stage 4.")


def require_client_approval(d, what):
    """Called by octave_copy.py (full run) and smartlead_build.py."""
    if "--skip-client-approval" in sys.argv:
        print("NOTE: --skip-client-approval: running without client approval (internal test only)")
        return
    if not client_approved(d):
        sys.exit(f"{what} needs the client's approval of the current copy first. "
                 f"Run: python stages/3-copy/approvals.py status {d}   (or --skip-client-approval for internal tests)")


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 3:
        sys.exit(__doc__)
    cmd, d = a[1], a[2]
    note = a[a.index("--note") + 1] if "--note" in a else ""
    if cmd == "status":
        status(d)
    elif cmd == "csm-approve":
        csm_approve(d, note)
    elif cmd == "client-review":
        client_review(d)
    elif cmd == "client-feedback":
        if len(a) < 4:
            sys.exit('usage: client-feedback <run_dir> "what the client said"')
        client_feedback(d, a[3])
    elif cmd == "client-approve":
        client_approve(d, note)
    else:
        sys.exit(__doc__)

"""Build the Smartlead campaign as a DRAFT and write the upload file.

  python stages/4-campaign/smartlead_build.py <client> <run_dir> --reference <live_campaign_id> [--dry-run] [--new] [--no-mailboxes]

Reads <run_dir>/campaign_spec.json:
  {"name": "Meeting_<Angle>", "max_new_leads_per_day": 300,
   "signature": {"closers": ["Appreciate it", "Best regards", "Thanks"], "titles": ["Client Partner"], "website": "clear-tech.com"},
   "followups": [{"delay_days": 3, "body_html": "..."}, {"delay_days": 4, "body_html": "..."}],
   "slots": {...}}                     # same slots as octave_copy.py
Email 1 gets one A/B variant per slot; each variant reads that lead's custom fields {{subject_<slot>}} / {{email_<slot>}},
followed by the sign-off, then {{ps_<slot>}} for frameworks that write a P.S. (Standard Go-To). The plain-text copy is converted to HTML paragraphs before upload, so line breaks survive.
Settings, schedule and mailboxes are copied from the reference campaign (a live campaign of this client).
Leads: copy.jsonl (falls back to verified.jsonl). Also writes upload.csv in the Cymate lead template.
Stops at the first failed API call and says which campaign id was left as a partial draft.
Refuses to create a second campaign for the same run unless --new is passed. Never starts the campaign.
"""
import csv, html, json, sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import http, smartlead_key, set_stage, read_jsonl, signature_html, ROOT
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "3-copy"))
from approvals import require_client_approval

B = "https://server.smartlead.ai/api/v1"
NO_MAILBOXES = False  # set by --no-mailboxes


def body_html(text):
    """Plain-text email -> Smartlead HTML: one <div> per line, <br> between paragraphs."""
    text = (text or "").replace("\r\n", "\n").strip()
    paras = [p for p in text.split("\n\n") if p.strip()]
    return "<br>".join("".join(f"<div>{html.escape(ln, quote=False)}</div>" for ln in p.split("\n")) for p in paras)


def write_upload_csv(d, leads, slots):
    with (Path(__file__).resolve().parent / "templates" / "lead_template_header.csv").open(encoding="utf-8-sig") as f:
        hdr = next(csv.reader(f))
    extra = [f"{k}_{s.lower()}" for s in slots for k in ("subject", "email", "ps")]
    with (Path(d) / "upload.csv").open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel shows accents right
        w = csv.DictWriter(f, fieldnames=hdr + extra, extrasaction="ignore"); w.writeheader()
        for r in leads:
            row = {h: "" for h in hdr}
            row.update({"Full Name": r.get("full"), "First Name": r.get("first"), "Last Name": r.get("last"), "Name_Final": r.get("first"),
                        "Title": r.get("title"), "Email Business": r.get("email"), "Final_Email": r.get("email"),
                        "Company Name": r.get("company"), "Normalized Name": r.get("company"), "Company Website": r.get("website"),
                        "Website_Final": r.get("website"), "Domain_Final": r.get("domain"), "LinkedIn": r.get("linkedin"),
                        "Company Linkedin": r.get("company_linkedin"), "Company Industry": r.get("industry"), "Company Size": r.get("staff"),
                        "Company Address": r.get("hq"), "Email Valid (MV & FM)": r.get("verify"), "group": r.get("segment") or ""})
            row.update({k: r.get(k, "") for k in extra})
            w.writerow(row)


def call(method, url, body, step, cid=None):
    """Smartlead call that stops the build on failure and says what was left behind."""
    st, js = http(method, url, body)
    if st != 200 or (isinstance(js, dict) and js.get("ok") is False) or isinstance(js, str):
        left = f" Campaign {cid} was created but is incomplete (still DRAFT): fix it in Smartlead or delete it." if cid else ""
        sys.exit(f"Smartlead {step} failed ({st}): {js}.{left}")
    return js


def category_ids(opts):
    out = []
    for o in opts or []:
        if isinstance(o, dict) and o.get("id") is not None:
            out.append(o["id"])
        elif isinstance(o, (int, str)):
            out.append(o)
    return out


def main(client, d, ref, dry, new):
    d = Path(d)
    spec = json.loads((d / "campaign_spec.json").read_text(encoding="utf-8"))
    src = d / ("copy.jsonl" if (d / "copy.jsonl").exists() else "verified.jsonl")
    leads = read_jsonl(src)
    if src.name == "verified.jsonl":
        print("WARNING: no copy.jsonl, so the leads have no subject_/email_ fields and Email 1 would be empty")
    write_upload_csv(d, leads, spec["slots"])
    print(f"upload.csv written ({len(leads)} leads from {src.name})")
    signature_html(spec)  # stop early if the signature isn't set
    if dry:
        return
    require_client_approval(d, "Building the Smartlead campaign")
    if (d / "campaign_id").exists() and not new:
        sys.exit(f"this run already built campaign {(d / 'campaign_id').read_text(encoding='utf-8').strip()}. "
                 "Check it in Smartlead; pass --new only if a second campaign is really wanted.")
    k = smartlead_key(client)
    refc = call("GET", f"{B}/campaigns/{ref}?api_key={k}", None, "read reference campaign")
    accts = call("GET", f"{B}/campaigns/{ref}/email-accounts?api_key={k}", None, "read reference mailboxes")
    if not accts and not NO_MAILBOXES:
        sys.exit(f"reference campaign {ref} has no mailboxes; pick a live campaign of {client}, "
                 "or pass --no-mailboxes for a test draft that cannot send")

    made = call("POST", f"{B}/campaigns/create?api_key={k}", {"name": spec["name"]}, "create campaign")
    cid = made.get("id") if isinstance(made, dict) else None
    if not cid:
        sys.exit(f"Smartlead create campaign returned no id: {made}")
    (d / "campaign_id").write_text(str(cid), encoding="utf-8")
    set_stage(d, "build", campaign_id=cid, done=False, reference=ref)

    signoff = signature_html(spec)  # closer, sender first name, title, website that is not a link
    ps_slots = {s for s in spec["slots"] if any(r.get(f"ps_{s.lower()}") for r in leads)}  # e.g. Standard Go-To
    variants = [{"subject": f"{{{{subject_{s.lower()}}}}}",
                 "email_body": f"{{{{email_{s.lower()}}}}}" + (f"<br>{signoff}" if signoff else "")
                               + (f"<br><div>{{{{ps_{s.lower()}}}}}</div>" if s in ps_slots else ""),
                 "variant_label": chr(65 + i)} for i, s in enumerate(spec["slots"])]
    seqs = [{"seq_number": 1, "seq_delay_details": {"delay_in_days": 0}, "seq_variants": variants}]
    for i, fu in enumerate(spec.get("followups", []), start=2):
        fu_body = fu["body_html"] if "%sender" in fu["body_html"] else f'{fu["body_html"]}<br>{signoff}'  # same signature on follow ups
        seqs.append({"seq_number": i, "seq_delay_details": {"delay_in_days": fu["delay_days"]}, "subject": "", "email_body": fu_body})
    call("POST", f"{B}/campaigns/{cid}/sequences?api_key={k}", {"sequences": seqs}, "sequences", cid)

    ooo = refc.get("out_of_office_detection_settings") or {}
    settings = {"track_settings": refc.get("track_settings"), "stop_lead_settings": refc.get("stop_lead_settings"),
                "send_as_plain_text": refc.get("send_as_plain_text"), "force_plain_text": refc.get("force_plain_text"),
                "follow_up_percentage": refc.get("follow_up_percentage"), "add_unsubscribe_tag": refc.get("add_unsubscribe_tag"),
                "enable_ai_esp_matching": refc.get("enable_ai_esp_matching"),
                "bounce_autopause_threshold": str(refc.get("bounce_autopause_threshold") or 4),
                "out_of_office_detection_settings": {**ooo, "autoReactivateOOO": False} if ooo.get("autoCategorizeOOO") else ooo,
                "ai_categorisation_options": category_ids(refc.get("ai_categorisation_options"))}
    call("POST", f"{B}/campaigns/{cid}/settings?api_key={k}", settings, "settings", cid)

    cron = refc.get("scheduler_cron_value") or {}
    sched = {"timezone": cron.get("tz"), "days_of_the_week": cron.get("days"), "start_hour": cron.get("startHour"),
             "end_hour": cron.get("endHour"), "min_time_btw_emails": refc.get("min_time_btwn_emails"),
             "max_new_leads_per_day": spec.get("max_new_leads_per_day", 300)}
    call("POST", f"{B}/campaigns/{cid}/schedule?api_key={k}", sched, "schedule", cid)
    if accts:
        call("POST", f"{B}/campaigns/{cid}/email-accounts?api_key={k}", {"email_account_ids": [a["id"] for a in accts]}, "mailboxes", cid)
    else:
        print("no mailboxes attached (--no-mailboxes): this draft cannot send until mailboxes are added in Smartlead")

    tot = {}
    for i in range(0, len(leads), 100):
        batch = [{"first_name": r.get("first"), "last_name": r.get("last"), "email": r.get("email"), "company_name": r.get("company"),
                  "website": r.get("website") or "", "linkedin_profile": r.get("linkedin") or "", "location": r.get("hq") or "",
                  "custom_fields": {"title": (r.get("title") or "")[:200],
                                    **{f"subject_{s.lower()}": r.get(f"subject_{s.lower()}", "") for s in spec["slots"]},
                                    **{f"email_{s.lower()}": body_html(r.get(f"email_{s.lower()}", "")) for s in spec["slots"]},
                                    **{f"ps_{s.lower()}": html.escape(r.get(f"ps_{s.lower()}", ""), quote=False) for s in ps_slots}}}
                 for r in leads[i:i + 100]]
        res = call("POST", f"{B}/campaigns/{cid}/leads?api_key={k}", {"lead_list": batch, "settings": {
            "ignore_global_block_list": False, "ignore_unsubscribe_list": False,
            "ignore_duplicate_leads_in_other_campaign": False, "ignore_community_bounce_list": False}},
            f"lead upload (leads {i + 1}-{i + len(batch)})", cid)
        for kk, v in (res or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                tot[kk] = tot.get(kk, 0) + v
    set_stage(d, "build", done=True, leads=tot, mailboxes=len(accts), variants=len(variants))
    print(f"campaign {cid} '{spec['name']}' created as DRAFT with {len(variants)} Email 1 variants, {len(accts)} mailboxes. leads: {tot}")


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 3 or "--reference" not in a:
        sys.exit("usage: smartlead_build.py <client> <run_dir> --reference <campaign_id> [--dry-run] [--new] [--no-mailboxes]")
    NO_MAILBOXES = "--no-mailboxes" in a
    main(a[1], a[2], a[a.index("--reference") + 1], "--dry-run" in a, "--new" in a)

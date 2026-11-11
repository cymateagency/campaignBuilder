"""Offline simulation of every pipeline stage with every external API faked (no keys, no credits).

  python tests/test_offline.py      # prints ALL PASS
"""
import json, sys, shutil, tempfile
from pathlib import Path
from collections import Counter
ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
for _p in ("lib", "stages/2-lead-list", "stages/3-copy", "stages/4-campaign"):
    sys.path.insert(0, str(ROOT / _p))
import common
tmp = Path(tempfile.mkdtemp()); d = tmp / "run"; d.mkdir()
fails = []
def check(c, msg):
    print(("ok  " if c else "FAIL") + " " + msg)
    if not c: fails.append(msg)

# --- Airtable lookup: shared keys from the Cymate row, Smartlead from the client row, exact Business match
ROWS = {"recC": {"fldZk1XJa6aGNr2KY": "Cymate", "fldoRVFOrzVVyWeXf": "oct-key", "AI Ark API Key": "ark-key"},
        "recA": {"fldZk1XJa6aGNr2KY": "Acme", "fld0DPqzJj7tQcYnC": "sl-acme"},
        "recB": {"fldZk1XJa6aGNr2KY": "Acme Labs", "fld0DPqzJj7tQcYnC": "sl-labs"},
        "recD": {"fldZk1XJa6aGNr2KY": "Dup"}, "recE": {"fldZk1XJa6aGNr2KY": "dup"}}
def fake_at(path, params=None):
    rid = path.rsplit("/", 1)[-1]
    if rid.startswith("rec"):
        return {"fields": ROWS[rid]}
    assert params["fields[]"] == "fldZk1XJa6aGNr2KY"
    return {"records": [{"id": k, "fields": {"fldZk1XJa6aGNr2KY": v["fldZk1XJa6aGNr2KY"]}} for k, v in ROWS.items()]}
real_at = common._airtable
real_at_cfg = json.loads(json.dumps(common.CONFIG["airtable"]))
common.CONFIG["airtable"]["cymate_record"] = "Cymate"
common.CONFIG["airtable"]["shared_fields"].update({"aiark": "AI Ark API Key", "leadmagic": "LeadMagic API Key"})
common._airtable = fake_at
check(common.tool_key("octave") == "oct-key" and common.tool_key("aiark") == "ark-key", "shared keys come from the Cymate row (by id and by name)")
check(common.smartlead_key("acme") == "sl-acme", "client match is exact: 'acme' does not pick 'Acme Labs'")
try:
    common.tool_key("leadmagic"); check(False, "missing shared key should stop")
except SystemExit as e:
    check("LeadMagic API Key" in str(e), "missing shared column gives a clear message")
try:
    common.smartlead_key("Dup"); check(False, "duplicate should stop")
except SystemExit as e:
    check("2 rows" in str(e), "duplicate client names are refused")
try:
    common.smartlead_key("Acm"); check(False, "unknown should stop")
except SystemExit as e:
    check("Close matches" in str(e), "unknown client lists close matches")
CY_URL = "https://mcp.octavehq.com/mcp?ctx=eyJvcmdhbml6YXRpb25fc2x1ZyI6ImN5bWF0ZSIsIndvcmtzcGFjZV9vX2lkIjoid2FfdHl1N0FEVVA0NkxKR3k1ZnUyR2ZBIn0%3D"
import base64
OTHER_URL = "https://mcp.octavehq.com/mcp?ctx=" + base64.urlsafe_b64encode(b'{"workspace_o_id":"wa_other"}').decode()
ROWS["recA"].update({"fldoRVFOrzVVyWeXf": "acme-oct", "fldEjSsHO7q54U0bi": CY_URL})
ROWS["recB"].update({"fldoRVFOrzVVyWeXf": "labs-oct", "fldEjSsHO7q54U0bi": OTHER_URL})
common._KEYS.clear(); common._RECORDS.clear()
check(common.octave_workspace(CY_URL) == "wa_tyu7ADUP46LJGy5fu2GfA", "reads the workspace id from an Octave MCP URL")
check(common.octave_key("Acme") == "acme-oct", "client's own Octave key used when it is in the Cymate workspace")
check(common.octave_key("Dup") if False else common.octave_key(None) == "oct-key", "no client: Cymate row key")
try:
    common.octave_key("Acme Labs"); check(False, "other workspace should stop")
except SystemExit as e:
    check("wa_other" in str(e), "client key from another Octave workspace is refused")
ROWS["recA"].pop("fldoRVFOrzVVyWeXf"); common._KEYS.clear(); common._RECORDS.clear()
check(common.octave_key("Acme") == "oct-key", "client without its own Octave key falls back to the Cymate row")
common.CONFIG["airtable"]["shared_fields"]["aiark_webhook"] = None
check(common.optional_tool_key("aiark_webhook") is None, "optional_tool_key returns None for an unmapped key")
common._airtable = real_at
common.CONFIG["airtable"] = real_at_cfg

# --- aiark_pull
import aiark_pull as P
P.tool_key = lambda n: "x"; P.optional_tool_key = lambda n: "https://hook.test/x"; P.time.sleep = lambda s: None
calls = []
def fake_http(m, url, body=None, h=None, **k):
    calls.append(url)
    if url.endswith("/people/export"): return 200, {"trackId": "T1", "state": "PENDING"}
    if url.endswith("/statistics"): return 200, {"state": "DONE", "statistics": {"total": 2}}
    if "/inquiries" in url: return 200, {"last": True, "content": [
        {"id": "a1", "profile": {"first_name": "Łukasz", "last_name": "Nowak", "title": "CISO"}, "company": {"link": {"domain": "x.pl"}}},
        {"id": None, "profile": {"first_name": "Ana", "title": "CISO"}, "company": {}}]}
P.http = fake_http
(d / "api_body.json").write_text("{}"); (d / "list_spec.json").write_text(json.dumps({"segment": "Seg A"}))
common.save_state(d, {"stages": {"count": {"total": 25000}}, "spend": {}})
try:
    P.export(str(d)); check(False, "export should refuse >10k")
except SystemExit as e:
    check("10000" in str(e), "export refuses >10k without --max")
P.export(str(d), 2)
P.export(str(d), 2)
check(sum(u.endswith("/people/export") for u in calls) == 1, "second export resumes instead of paying again")
rows = common.read_jsonl(d / "aiark_raw.jsonl")
check(rows[0]["first"] == "Łukasz" and rows[0]["segment"] == "Seg A", "UTF-8 name and segment tag survive")
check(common.load_state(d)["spend"]["aiark_credits"] == 2, "AI Ark spend counted once")

# --- clean
import clean as C
raw = [{"aiark_id": None, "linkedin": None, "first": "A", "last": "B", "domain": "a.com", "title": "CISO"},
       {"aiark_id": None, "linkedin": None, "first": "C", "last": "D", "domain": "c.com", "title": "CISO"},
       {"aiark_id": None, "linkedin": None, "title": "CISO"},
       {"aiark_id": None, "linkedin": None, "title": "CISO"},
       {"aiark_id": "z", "title": "CISO", "email": "z@z.com", "mx": "mx1.pphosted.com"},
       {"aiark_id": "y", "title": "CISO", "email": "old@y.com"}]
common.write_jsonl(d / "aiark_raw.jsonl", raw)
(d / "already_contacted.txt").write_text("old@y.com\nfound@old.com")
C.main(str(d))
check(len(common.read_jsonl(d / "cleaned.jsonl")) == 4, "id-less rows kept (4 kept)")
check(len(common.read_jsonl(d / "held.jsonl")) == 1, "Proofpoint MX held via config")

# --- waterfall
import email_waterfall as W
W.CACHE = tmp / "cache"; W.CACHE.mkdir(); W.FIND.clear(); W.VERIFY.clear()
found = iter(["found@old.com", "dup@x.com", "dup@x.com", "err@x.com"])
W.leadmagic = lambda r: (next(found, None), 1); W.icypeas = lambda r: (None, 0)
W.millionverifier = lambda e: None if e.startswith("err") else "ok"
W.bounceban = lambda e: ("deliverable", 99)
common.write_jsonl(d / "cleaned.jsonl", [{"first": f"P{i}", "last": "X", "domain": f"d{i}.com"} for i in range(4)])
W.main(str(d), {"mv_all": False, "keep_risky": False, "dry": False, "workers": 1})
res = Counter(l["result"] for l in common.read_jsonl(d / "waterfall_log.jsonl"))
check(res == Counter({"already in a client campaign": 1, "duplicate email": 1, "verify error": 1, "deliverable": 1}), f"waterfall results {dict(res)}")
st = common.load_state(d)["spend"]
check(st.get("leadmagic") == 4 and st.get("millionverifier") == 1, f"waterfall spend recorded {st}")
common.write_jsonl(d / "cleaned.jsonl", [{"first": f"Q{i}", "last": "X", "domain": f"q{i}.com"} for i in range(3)])
cnt = iter(range(10))
def boom(r):
    if next(cnt) == 2: raise RuntimeError("network died")
    return (f"{r['first'].lower()}@q.com", 1)
W.leadmagic = boom; W.millionverifier = lambda e: "ok"
before = common.load_state(d)["spend"]["leadmagic"]
try:
    W.main(str(d), {"mv_all": False, "keep_risky": False, "dry": False, "workers": 1})
except RuntimeError:
    pass
after = common.load_state(d)["spend"]["leadmagic"]
cache = (W.CACHE / "find.json").read_text(encoding="utf-8")
check(after - before == 2 and "q0@q.com" in cache, f"crash still saves spend and cache (+{after - before})")

# --- octave_copy
import octave_copy as O
leads = [{"aiark_id": f"L{i}", "email": f"l{i}@x.com", "first": "Zoë", "segment": "Seg A"} for i in range(6)]
common.write_jsonl(d / "verified.jsonl", leads)
spec = json.loads((ROOT / "stages/3-copy/templates/campaign_spec.example.json").read_text(encoding="utf-8"))
check(list(spec["slots"]) == ["MEDIUM"], "example spec uses one framework")
spec["slots"] = {k: {"framework": fw, "fallback_subject": "...", "fallback_body": "..."} for k, fw in
                 (("LONG", "STANDARD_GO_TO"), ("MEDIUM", "TFKD"), ("SHORT", "TWO_SENTENCE_PAIN"), ("SHORT_B", "POKE_THE_BEAR"))}
(d / "campaign_spec.json").write_text(json.dumps(spec), encoding="utf-8")
check(O.CONFIG["octave_template_agents"]["TFKD"].startswith("ca_"), "config has the real agent OIDs")
O.CONFIG["octave_template_agents"]["TFKD"] = "TODO_AGENT_OID"
spec["brief"] = "no client line"
(d / "campaign_spec.json").write_text(json.dumps(spec), encoding="utf-8")
try:
    O.main(str(d), 2); check(False, "should refuse")
except SystemExit as e:
    check("no Octave agent OID" in str(e) and "placeholder" in str(e) and "CLIENT:" in str(e), "refuses TODO agent, '...' fallbacks and a brief without CLIENT:")
O.CONFIG["octave_template_agents"]["TFKD"] = "ca_test"
spec["brief"] = "CLIENT: Acme - test\nSEGMENTS:\n- Seg A: x"
for s in spec["slots"].values(): s.update(fallback_subject="quick question", fallback_body="Hi there,\n\nFallback.")
(d / "campaign_spec.json").write_text(json.dumps(spec), encoding="utf-8")
runs = []
def fake_agent(agent, lead, brief, seg):
    runs.append((lead["aiark_id"], seg))
    ps = "P.S. like a map & compass." if agent == O.CONFIG["octave_template_agents"]["STANDARD_GO_TO"] else ""
    return {"subject": "hi", "body": f"Hey {lead['first']},\n\nLine 2 & <ok>.", "ps": ps, "confidence": "high"}, True
O.run_agent = fake_agent
try:
    O.main(str(d), 2); check(False, "test of 2 should be refused")
except SystemExit as e:
    check("at least 5" in str(e), "CSM review needs at least 5 examples")
O.main(str(d), 5)
check(len(runs) == 20 and all(s == "Seg A" for _, s in runs), "test run: 5 leads x 4 slots with segment")
md = (d / "copy_test.md").read_text(encoding="utf-8")
check("Zoë" in md and "P.S. like a map" in md, "copy_test.md written with UTF-8 and shows the P.S.")
import approvals as A
try:
    O.main(str(d)); check(False, "full run without client approval should stop")
except SystemExit as e:
    check("client's approval" in str(e), "full copy run waits for the client's approval")
try:
    A.client_review(str(d)); check(False, "client review before CSM approval should stop")
except SystemExit as e:
    check("CSM hasn't approved" in str(e), "client review needs the CSM's approval first")
A.csm_approve(str(d)); A.client_review(str(d))
cr = (d / "client_review.md").read_text(encoding="utf-8")
check(cr.count("## Example") == 20 and "Appreciate it," in cr and "client-website.com" in cr and "Fact:" not in cr,
      "client_review.md: 5 leads x 4 slots, signature, no internal notes")
A.client_feedback(str(d), "Please don't mention LG.")
check(not A.client_approved(str(d)) and "Please don't mention LG." in (d / "client_feedback.md").read_text(encoding="utf-8"), "client feedback recorded, starts a new round")
A.client_approve(str(d))
check(A.client_approved(str(d)), "client approval recorded for the current version")
O.main(str(d))
check(len(runs) == 24, f"full run only pays for the 1 new lead (runs={len(runs)})")

# --- smartlead_build
import smartlead_build as S
S.smartlead_key = lambda c: "k"; sent = {}; FAIL = [True]
def sl_http(m, url, body=None, h=None, **k):
    key = url.split("/api/v1/")[1].split("?")[0]
    sent.setdefault(key, []).append(body)
    if key == "campaigns/R1": return 200, {"scheduler_cron_value": {"tz": "America/New_York"}, "ai_categorisation_options": [1, {"id": 2}]}
    if key == "campaigns/R1/email-accounts": return 200, [{"id": 5}]
    if key == "campaigns/create": return 200, {"id": 99}
    if key.endswith("/schedule") and FAIL[0]: return 400, {"error": "bad tz"}
    if key.endswith("/leads"): return 200, {"upload_count": len(body["lead_list"])}
    return 200, {"ok": True}
S.http = sl_http
try:
    S.main("Client", str(d), "R1", False, False); check(False, "should stop")
except SystemExit as e:
    check("Campaign 99" in str(e) and "schedule" in str(e), "stops at failed call and names the partial draft")
try:
    S.main("Client", str(d), "R1", False, False); check(False, "should refuse")
except SystemExit as e:
    check("already built campaign 99" in str(e), "refuses a second build for the same run")
FAIL[0] = False; sent.clear()
S.main("Client", str(d), "R1", False, True)
var = sent["campaigns/99/sequences"][0]["sequences"][0]["seq_variants"][0]["email_body"]
check(var.startswith("{{email_long}}<br><div>{Appreciate it|Best regards|Thanks},</div><div>%sender-firstname%</div>")
      and "client-website․com" in var and var.endswith("<br><div>{{ps_long}}</div>"), "LONG variant: body, signature (first name, title, unlinked site), then P.S.")
fu = sent["campaigns/99/sequences"][0]["sequences"][1]["email_body"]
check("%sender-firstname%" in fu, "follow ups get the same signature")
var_b = sent["campaigns/99/sequences"][0]["sequences"][0]["seq_variants"][1]["email_body"]
check("ps_" not in var_b, "slots without a P.S. get no P.S. line")
lf = sent["campaigns/99/leads"][0]["lead_list"][0]["custom_fields"]
check(lf.get("ps_long") == "P.S. like a map &amp; compass." and "ps_medium" not in lf, "P.S. uploaded as a custom field")
cf = sent["campaigns/99/leads"][0]["lead_list"][0]["custom_fields"]["email_long"]
check(cf == "<div>Hey Zoë,</div><br><div>Line 2 &amp; &lt;ok&gt;.</div>", f"email converted to HTML: {cf}")
check(sent["campaigns/99/settings"][0]["ai_categorisation_options"] == [1, 2], "category ids handle ints and dicts")
check(common.load_state(d)["stages"]["build"]["done"] is True, "build recorded in state.json")
check("Zoë" in (d / "upload.csv").read_text(encoding="utf-8-sig"), "upload.csv UTF-8")
shutil.rmtree(tmp)
print("\nALL PASS" if not fails else f"\n{len(fails)} FAILED")

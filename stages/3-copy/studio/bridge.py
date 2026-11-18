"""Cymate Copy bridge: a local MCP server (stdio) behind the Copy Studio artifact.

The artifact's network is blocked and must never hold API keys, so everything that needs a key runs here:
  - Airtable (AIRTABLE_TOKEN): the client list, and each client's Smartlead and Octave keys
  - Smartlead (the client's own key from Airtable): campaigns, analytics and sequence copy, for the learnings
  - Octave: the Cymate template agents (Cymate-workspace key) and the client's own library (its key + Octave MCP URL)
No tool ever returns a key. Registered in the Claude desktop app as "cymate_copy":
  python <repo>/stages/3-copy/studio/bridge.py   (setup: stages/3-copy/studio/README.md)

Agent runs take 30-120 s (web research), longer than one connector call may wait, so they are jobs:
start_agent_runs returns job ids at once and get_agent_runs reports them.
"""
import sys

PROTO_OUT = sys.stdout  # the MCP channel; everything else printed goes to stderr
sys.stdout = sys.stderr

import json, re, threading, time, traceback, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # stages/3-copy/studio/bridge.py -> repo root
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "stages" / "3-copy"))
import common  # noqa: E402
from common import CONFIG, http, smartlead_key  # noqa: E402
import octave_copy  # noqa: E402  (qa + greeting fixes, the same checks as the CLI test run)

SL = "https://server.smartlead.ai/api/v1"
OCTAVE_RUN = octave_copy.URL
VERSION = "1.0.0"


class ToolError(Exception):
    pass


def guard(fn, *a, **k):
    """common.py exits on missing keys or rows: turn that into a readable tool error."""
    try:
        return fn(*a, **k)
    except SystemExit as e:
        raise ToolError(str(e) or "stopped")


# ---------- Airtable ----------

def list_clients(_):
    at = CONFIG["airtable"]
    nf = at["client_name_field"]
    names, offset = [], None
    while True:
        params = {"returnFieldsByFieldId": "true", "pageSize": 100, "fields[]": nf}
        if offset:
            params["offset"] = offset
        js = guard(common._airtable, f"{at['base']}/{at['clients_table']}", params)
        for rec in js.get("records", []):
            v = str((rec.get("fields") or {}).get(nf) or "").strip()
            if v:
                names.append(v)
        offset = js.get("offset")
        if not offset:
            break
    return {"clients": sorted(set(names), key=str.lower), "shared_row": at["cymate_record"]}


# ---------- Smartlead ----------

def sl_get(key, path, params=None):
    q = "&".join(f"{k}={v}" for k, v in (params or {}).items() if v is not None)
    st, js = http("GET", f"{SL}{path}?api_key={key}" + (f"&{q}" if q else ""), timeout=60)
    time.sleep(0.25)  # Smartlead allows ~10 requests per 2 s
    if st != 200:
        msg = js if isinstance(js, str) else json.dumps(js)[:300]
        raise ToolError(f"Smartlead {path.split('?')[0]} returned HTTP {st}: {msg}".replace(key, "***"))
    return js


def check_client(args):
    client = (args.get("client") or "").strip()
    if not client:
        raise ToolError("client is required")
    out = {"client": client}
    try:
        k = guard(smartlead_key, client)
        out["smartlead_key"] = "found in Airtable"
        try:
            camps = sl_get(k, "/campaigns/")
            out["smartlead_api"] = "ok"
            out["smartlead_campaigns"] = len(camps) if isinstance(camps, list) else None
        except ToolError as e:
            out["smartlead_api"] = str(e)
    except ToolError as e:
        out["smartlead_key"] = str(e)
    try:
        _, src = agent_key(client)
        out["octave_agents_key"] = src
        key, url, ws = _client_octave(client)
        own = bool(key and url and ws and ws != CONFIG["octave_workspace"])
        out["octave_library"] = f"client's own Octave workspace ({ws})" if own else "Cymate workspace, entities matching the client name"
    except ToolError as e:
        out["octave_agents_key"] = str(e)
    out["template_agents"] = CONFIG["octave_template_agents"]
    return out


TAG = re.compile(r"<[^>]+>")


def text_of(html):
    s = re.sub(r"<br\s*/?>|</div>|</p>", "\n", html or "", flags=re.I)
    s = TAG.sub("", s).replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def num(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def smartlead_learnings(args):
    """Campaign performance plus the copy of the best and worst campaigns, for Claude to turn into learnings.
    Smartlead's API has campaign-level numbers only, not per-variant performance."""
    client = (args.get("client") or "").strip()
    top = max(1, min(int(args.get("top") or 4), 8))
    scan = max(top, min(int(args.get("scan") or 25), 40))
    k = guard(smartlead_key, client)
    allc = [c for c in (sl_get(k, "/campaigns/") or []) if isinstance(c, dict)]
    camps = [c for c in allc if c.get("status") not in ("DRAFTED",)]
    camps.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    rows = []
    for c in camps[:scan]:
        try:
            a = sl_get(k, f"/campaigns/{c['id']}/analytics")
        except ToolError:
            continue
        sent = num(a.get("sent_count") or a.get("unique_sent_count"))
        uniq = num(a.get("unique_sent_count")) or sent
        rep = num(a.get("reply_count"))
        pos = num((a.get("campaign_lead_stats") or {}).get("interested")) if isinstance(a.get("campaign_lead_stats"), dict) else 0
        rows.append({"id": c["id"], "name": c.get("name"), "status": c.get("status"), "created_at": (c.get("created_at") or "")[:10],
                     "sent": sent, "unique_leads_sent": uniq, "replies": rep, "positive": pos,
                     "bounced": num(a.get("bounce_count")), "opened": num(a.get("open_count")),
                     "reply_rate": round(100 * rep / uniq, 2) if uniq else 0.0,
                     "positive_rate": round(100 * pos / uniq, 2) if uniq else 0.0})
    ranked = sorted([r for r in rows if r["unique_leads_sent"] >= 100], key=lambda r: (r["positive_rate"], r["reply_rate"]), reverse=True)
    pick = ranked[:top] + [r for r in ranked[-2:] if r not in ranked[:top]]
    for r in pick:
        r["label"] = "best" if r in ranked[:top] else "worst"
        try:
            seqs = sl_get(k, f"/campaigns/{r['id']}/sequences")
        except ToolError as e:
            r["sequence_error"] = str(e)
            continue
        steps = []
        for s in sorted(seqs if isinstance(seqs, list) else [], key=lambda s: num(s.get("seq_number"))):
            variants = s.get("sequence_variants") or [{"subject": s.get("subject"), "email_body": s.get("email_body"), "variant_label": "A"}]
            steps.append({"step": num(s.get("seq_number")),
                          "delay_days": num((s.get("seq_delay_details") or {}).get("delay_in_days") or (s.get("seq_delay_details") or {}).get("delayInDays")),
                          "variants": [{"label": v.get("variant_label") or "", "subject": v.get("subject") or "",
                                        "body": text_of(v.get("email_body"))[:1500]} for v in variants[:4]]})
        r["sequence"] = steps
    msg = None
    if not camps:
        msg = f"{len(allc)} campaigns in this Smartlead account, all drafts: nothing has been sent yet, so there are no learnings."
    elif not ranked:
        msg = "No campaign has 100+ leads sent yet, so rates are too early to trust. Copy is still shown for reference."
        pick = sorted(rows, key=lambda r: r["unique_leads_sent"], reverse=True)[:top]
        for r in pick:
            r["label"] = "early"
            try:
                r["sequence"] = [{"step": num(s.get("seq_number")), "variants": [{"label": v.get("variant_label") or "", "subject": v.get("subject") or "",
                                  "body": text_of(v.get("email_body"))[:1500]} for v in (s.get("sequence_variants") or [{"subject": s.get("subject"), "email_body": s.get("email_body")}])[:4]]}
                                 for s in sl_get(k, f"/campaigns/{r['id']}/sequences") or []]
            except ToolError as e:
                r["sequence_error"] = str(e)
    return {"client": client, "message": msg, "campaigns_total": len(allc), "drafts_skipped": len(allc) - len(camps),
            "campaigns_scanned": len(rows), "campaigns_with_100_plus_sent": len(ranked),
            "performance": sorted(rows, key=lambda r: r["unique_leads_sent"], reverse=True),
            "copy_of_best_and_worst": pick,
            "note": "Rates are per unique lead sent. Smartlead's API gives campaign-level numbers only, never per-variant results."}


# ---------- Octave: keys, library ----------

def _client_octave(client):
    """(own_key, own_mcp_url, own_workspace) from the client's Airtable row; any may be empty."""
    f = guard(common._record_fields, guard(common._client_record_id, client))
    cf = CONFIG["airtable"]["client_fields"]
    key = str(f.get(cf["octave"]) or "").strip()
    url = str(f.get(cf["octave_mcp_url"]) or "").strip()
    if isinstance(f.get(cf["octave_mcp_url"]), list):
        url = next((str(x) for x in f[cf["octave_mcp_url"]] if x), "")
    return key, url, (common.octave_workspace(url) if url else None)


def agent_key(client):
    """Key that runs the template agents (Cymate workspace): the client's own key only when it is a
    Cymate-workspace key, otherwise the shared key. Unlike common.octave_key, a client with its own
    workspace is not an error here: its key is used for its library instead."""
    key, _, ws = _client_octave(client)
    if key and (ws in (None, CONFIG["octave_workspace"])):
        return key, "client's own key"
    return guard(common.tool_key, "octave"), f"shared key ({CONFIG['airtable']['cymate_record']} row)"


def cymate_mcp_url():
    import base64
    ctx = base64.urlsafe_b64encode(json.dumps({"organization_slug": "cymate", "workspace_o_id": CONFIG["octave_workspace"]},
                                              separators=(",", ":")).encode()).decode()
    return f"https://mcp.octavehq.com/mcp?ctx={ctx}"


def octave_mcp(url, key, tool, args, timeout=120):
    """One tools/call on an Octave MCP server with an API key (stateless HTTP, SSE or JSON answer)."""
    import urllib.request, urllib.error
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": f"Bearer {key}"}

    def post(payload, sid=None):
        hh = dict(h, **({"mcp-session-id": sid} if sid else {}))
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=hh, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw, sid2 = r.read().decode("utf-8", "replace"), r.headers.get("mcp-session-id")
        except urllib.error.HTTPError as e:
            raise ToolError(f"Octave MCP {tool}: HTTP {e.code} {e.read()[:200]!r}")
        except OSError as e:
            raise ToolError(f"Octave MCP {tool}: {e}")
        msgs = [json.loads(l[5:]) for l in raw.splitlines() if l.startswith("data:") and l[5:].strip()] or ([json.loads(raw)] if raw.strip() else [])
        return msgs, sid2 or sid

    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "cymate_copy", "version": VERSION}}})
    if sid:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    msgs, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}, sid)
    m = next((x for x in msgs if x.get("id") == 2), None)
    if not m or "error" in m:
        raise ToolError(f"Octave MCP {tool}: {(m or {}).get('error') or 'no answer'}")
    res = m["result"]
    if res.get("structuredContent") is not None:
        return res["structuredContent"]
    txt = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
    if res.get("isError"):
        raise ToolError(f"Octave MCP {tool}: {txt[:300]}")
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return txt


LIB_TYPES = ["product", "service", "persona", "segment", "use_case", "proof_point", "reference", "competitor", "objection"]


def _slim(rows, n=25):
    out = []
    for r in (rows or [])[:n]:
        if isinstance(r, dict):
            out.append({"name": r.get("name") or r.get("title") or "", "description": (r.get("description") or r.get("summary") or "")[:600]})
    return out


def octave_context(args):
    """What Octave knows about the client, as reference for the brief. Uses the client's own Octave
    workspace (its key + Octave MCP URL from Airtable) when it has one; otherwise searches the Cymate
    workspace for the client's name (that workspace holds many clients, so only matching entities)."""
    client = (args.get("client") or "").strip()
    query = (args.get("query") or "").strip()
    key, url, ws = _client_octave(client)
    own = bool(key and url and ws and ws != CONFIG["octave_workspace"])
    out = {"client": client, "source": "client's own Octave workspace" if own else "Cymate Octave workspace (entities matching the client name)",
           "workspace": ws if own else CONFIG["octave_workspace"], "library": {}, "errors": []}
    if own:
        def fetch(t):
            if t == "_company":
                return t, octave_mcp(url, key, "get_workspace_company", {})
            if t == "_search":
                return t, octave_mcp(url, key, "search_knowledge_base", {"query": query, "limit": 8})
            return t, octave_mcp(url, key, "list_entities", {"entityType": t, "limit": 25})
        jobs = ["_company"] + LIB_TYPES + (["_search"] if query else [])
        with ThreadPoolExecutor(6) as ex:
            futs = [ex.submit(fetch, t) for t in jobs]
            for f in futs:
                try:
                    t, js = f.result()
                except ToolError as e:
                    out["errors"].append(str(e))
                    continue
                if t == "_company":
                    out["company"] = js[:3000] if isinstance(js, str) else js
                elif t == "_search":
                    out["search"] = js
                else:
                    rows = (js.get("entities") or js.get("results") or js.get("data") or js.get("items")) if isinstance(js, dict) else js
                    if rows:
                        out["library"][t] = _slim(rows)
    else:
        skey, _ = agent_key(client)
        try:
            out["search"] = octave_mcp(cymate_mcp_url(), skey, "search_knowledge_base",
                                       {"query": f"{client} {query}".strip(), "limit": 10, "includeResources": True})
        except ToolError as e:
            out["errors"].append(str(e))
    s = out.get("search")
    if isinstance(s, (dict, list)) and len(json.dumps(s)) > 12000:
        out["search"] = json.dumps(s)[:12000]
    return out


# ---------- Octave template agents (jobs) ----------

JOBS, JOBS_LOCK = {}, threading.Lock()
POOL = ThreadPoolExecutor(8)


def _agent_job(jid, client, framework, lead, brief, segment, extra):
    try:
        agent = CONFIG["octave_template_agents"].get(framework)
        if not agent:
            raise ToolError(f"no template agent for framework '{framework}' in config.json")
        ctx = brief + (f"\n\nSegment: {segment}" if segment else "") + (f"\n\nEXTRA INSTRUCTIONS FOR THIS RUN: {extra}" if extra else "")
        body = {"agentOId": agent, "firstName": lead.get("first"), "lastName": lead.get("last"), "jobTitle": lead.get("title"),
                "linkedInProfile": lead.get("linkedin"), "companyName": lead.get("company"), "companyDomain": lead.get("domain"),
                "email": lead.get("email"), "outputFormat": "JSON", "runtimeContext": ctx}
        st, js = http("POST", OCTAVE_RUN, body, {"api_key": agent_key(client)[0]}, timeout=300)
        if st != 200 or not isinstance(js, dict):
            raise ToolError(f"Octave returned {st}: {str(js)[:300]}")
        data = js.get("data") or {}
        out = data.get("jsonContent")
        if not out and data.get("content"):
            try:
                out = json.loads(data["content"])
            except (TypeError, json.JSONDecodeError):
                out = None
        if not isinstance(out, dict):
            raise ToolError("Octave answered without the JSON email")
        hard, flags = octave_copy.qa(out, lead, {"brief": brief}) if out.get("body") else (["empty body"], [])
        res = {"subject": out.get("subject") or "", "body": octave_copy.fix_greeting(out.get("body") or "", lead),
               "ps": (out.get("ps") or "").strip(), "confidence": str(out.get("confidence") or "").lower(),
               "fact_used": out.get("fact_used") or "", "source_url": out.get("source_url") or "",
               "hard_fails": hard, "flags": flags}
        if "1 to 2 weeks" in brief:
            res["body"] = re.sub(r"(?<!1 to )\b(in|within) 2 weeks\b", r"\1 1 to 2 weeks", res["body"])
        state = {"status": "done", "result": res}
    except Exception as e:  # noqa: BLE001  (report every failure on the job, never kill the server)
        msg = str(e) if isinstance(e, ToolError) else f"{type(e).__name__}: {e}"
        state = {"status": "error", "error": msg}
    with JOBS_LOCK:
        JOBS[jid].update(state, finished=time.time())


def start_agent_runs(args):
    client = (args.get("client") or "").strip()
    framework = args.get("framework") or "TFKD"
    brief = (args.get("brief") or "").strip()
    leads = args.get("leads") or []
    if not client:
        raise ToolError("client is required")
    if not brief.startswith("CLIENT:"):
        raise ToolError("the brief must start with 'CLIENT: <name> - <what the company is>' (the agents refuse to write without it)")
    if not leads or len(leads) > 15:
        raise ToolError("send 1 to 15 leads per call")
    agent_key(client)  # fail now, not inside every job
    ids = []
    for lead in leads:
        jid = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            JOBS[jid] = {"status": "running", "started": time.time(), "lead": lead.get("email") or lead.get("company")}
        POOL.submit(_agent_job, jid, client, framework, lead, brief, lead.get("segment") or args.get("segment"), args.get("extra_instructions"))
        ids.append(jid)
    return {"job_ids": ids, "estimated_octave_credits": 2 * len(ids)}


def get_agent_runs(args):
    with JOBS_LOCK:
        return {"jobs": {j: dict(JOBS.get(j) or {"status": "unknown"}) for j in (args.get("job_ids") or [])}}


# ---------- Onboarding (Airtable): form, call transcripts, notes ----------

ONB_TABLE, TRANSCRIPT_TABLE = "tbl4mZqO7lTnyX1Mf", "tblagqZTMi5KpvEVm"
CLIENT_ONB_LINK, CLIENT_TRANSCRIPTS, CLIENT_NOTES = "fld0WaAz95Jo5zTld", "fld4kg5K4oHJ9QBFD", "fldqkLTaMETttBkck"
ONB_FIELDS = {  # copy-relevant onboarding form answers (secrets such as logins are never read)
    "fldKdbY3ym05kkfkk": "Business name", "fldxtMt0QLOWVOcf3": "What the company does", "fld7wjgYDwjx61MZv": "Business details",
    "fld7XTrNrGtgdRC8Q": "Target locations", "fldBoEQDAF19ZAdUJ": "Top industries sold to", "fldXcxzVQSH8MNFmC": "Employee headcount",
    "fldCwSKajJMIJn6iy": "Revenue", "fldvJS016qHguFyMq": "Job titles sold to", "fldjMWdHKZP55BAaw": "Prospect objectives and success metrics",
    "fldPhu3RRSaylcDrL": "Pain points (how their job is harder without you)", "fld21n8RR1VQxX0qE": "How you help",
    "fld5goBX1HpINHOCv": "Value: makes money", "flddj41OXR2EFDSNR": "Value: saves money", "fldEN6oBYr55fXfyv": "Value: saves time",
    "fldFACxcUN4XNiEpV": "Value: avoids effort", "fldO9e9rHfm2n4Aip": "USP / unique mechanism", "fld32zmdOKaRUVXFM": "Case studies for email",
    "fldAvdxdUtQkQhtbH": "Quantifiable results", "fld4Lxb5OIfY8cayV": "Social proof statement", "fld1C3xqIHFlUDd76": "Common objections",
    "fldsS03MK8GJlb4XE": "How objections are addressed", "fld2cLlcYHauq7zwb": "Lead magnets", "fld0pnEdNglcOduPM": "Insights of value",
    "flddnkH5lzdGf5qnV": "Primary campaign objective", "fldIdeeqn7ykCgE4l": "Booking links", "fldqhPHTza0tkVkjH": "Campaign do's and don'ts",
    "fldrsaihQCwseMvGT": "Form filled by", "fldSbXQ29GCucJXWP": "Email signatures (attachments)", "fldrbZS3qqTNTyGZ7": "Best past outbound emails (attachments)",
}


def _flat(v):
    if isinstance(v, list):
        return ", ".join(_flat(x) for x in v if x not in (None, ""))
    if isinstance(v, dict):
        return v.get("name") or v.get("filename") or v.get("url") or json.dumps(v)
    return str(v)


def onboarding_context(args):
    """The client's onboarding form answers (Airtable 'Onboarding Client' table, linked from the Clients row or
    matched by Business Name), its onboarding/sync call transcripts (Transcript Intake) and the Clients notes."""
    client = (args.get("client") or "").strip()
    at = CONFIG["airtable"]
    rec = guard(common._record_fields, guard(common._client_record_id, client))
    out = {"client": client, "form": None, "form_source": None, "transcripts": [], "notes": _flat(rec.get(CLIENT_NOTES) or "")[:4000] or None}
    ids = rec.get(CLIENT_ONB_LINK) or []
    rows = []
    for rid in ids[:2]:
        js = guard(common._airtable, f"{at['base']}/{ONB_TABLE}/{rid}", {"returnFieldsByFieldId": "true"})
        rows.append(js.get("fields") or {})
    if not rows:
        name = client.replace("'", "\\'")
        js = guard(common._airtable, f"{at['base']}/{ONB_TABLE}", {"returnFieldsByFieldId": "true", "pageSize": 3,
                   "filterByFormula": f"LOWER(TRIM({{Business Name}}))='{name.lower()}'"})
        rows = [r.get("fields") or {} for r in js.get("records", [])]
        if rows:
            out["form_source"] = "Onboarding Client table, matched by business name"
    else:
        out["form_source"] = "Onboarding Client table, linked from the client's row"
    if rows:
        f = rows[0]
        out["form"] = {label: _flat(f[fid])[:3000] for fid, label in ONB_FIELDS.items() if f.get(fid) not in (None, "", [])}
    tids = rec.get(CLIENT_TRANSCRIPTS) or []
    for rid in tids[-int(args.get("transcripts") or 2):]:
        try:
            js = guard(common._airtable, f"{at['base']}/{TRANSCRIPT_TABLE}/{rid}")
        except ToolError:
            continue
        flds = js.get("fields") or {}
        text = next((v for k, v in flds.items() if k.lower() == "transcript"), None) or ""
        title = "Call transcript"
        out["transcripts"].append({"title": title, "created": js.get("createdTime", "")[:10], "transcript": str(text)[:30000]})
    if not out["form"]:
        out["form_message"] = "No onboarding form row in Airtable for this client."
    return out


def sample_leads(args):
    """Real prospects from the client's Smartlead campaigns, to test copy on when the pipeline has no verified list."""
    client = (args.get("client") or "").strip()
    n = max(1, min(int(args.get("n") or 6), 15))
    k = guard(smartlead_key, client)
    camps = [c for c in (sl_get(k, "/campaigns/") or []) if isinstance(c, dict)]
    camps.sort(key=lambda c: ({"ACTIVE": 0, "PAUSED": 1, "COMPLETED": 2}.get(c.get("status"), 3), -(num(c.get("id")))))
    out = []
    for c in camps[:6]:
        try:
            js = sl_get(k, f"/campaigns/{c['id']}/leads", {"limit": 40, "offset": 0})
        except ToolError:
            continue
        for row in (js.get("data") if isinstance(js, dict) else js) or []:
            l = row.get("lead") or row
            cf = l.get("custom_fields") or {}
            title = cf.get("title") or cf.get("Title") or cf.get("job_title") or cf.get("Job Title") or l.get("title") or ""
            site = (l.get("website") or l.get("company_url") or "").lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            dom = site or (l.get("email") or "").split("@")[-1]
            if not (l.get("first_name") and l.get("company_name") and dom):
                continue
            out.append({"first": l.get("first_name"), "last": l.get("last_name") or "", "title": title, "company": l.get("company_name"),
                        "domain": dom, "linkedin": l.get("linkedin_profile") or "", "from_campaign": c.get("name")})
            if len(out) >= n:
                return {"client": client, "leads": out}
    return {"client": client, "leads": out, "message": None if out else "No leads with a name, company and domain in this client's Smartlead campaigns."}


def agent_template(args):
    """The live instructions of one Cymate template agent in Octave (Cymate workspace), so the studio
    builds paste-ready instructions from what the agent really says today."""
    fw = (args.get("framework") or "").strip()
    oid = CONFIG["octave_template_agents"].get(fw)
    if not oid:
        raise ToolError(f"no template agent for framework '{fw}' in config.json")
    key = guard(common.tool_key, "octave")
    js = octave_mcp(cymate_mcp_url(), key, "get_agent", {"oId": oid})
    d = (js.get("data") if isinstance(js, dict) else None) or {}
    cfg = d.get("data") or {}
    return {"framework": fw, "agent_oid": oid, "name": d.get("name"), "instructions": cfg.get("instructions") or "",
            "web_search_instructions": ((cfg.get("tools") or {}).get("parallelWebSearch") or {}).get("customInstructions") or "",
            "json_schema_instructions": cfg.get("jsonSchemaInstructions") or "", "model": cfg.get("model"), "updated": d.get("updatedAt")}


def _run_slug(s):
    return (s or "").strip().lower().replace(" ", "-")


def pipeline_run(args):
    """What the pipeline already decided for this client, from runs/<client>/<campaign>/:
    stage 1 (client_context.md, icp_brief.md, chosen group + offer), stage 2 (verified leads),
    stage 3 (campaign_spec.json). Newest campaign first unless one is named."""
    client = (args.get("client") or "").strip()
    base = ROOT / "runs" / _run_slug(client)
    if not base.is_dir():
        return {"client": client, "campaigns": [], "message": f"No pipeline run for {client} on this laptop (runs/{_run_slug(client)}/)."}
    camps = sorted([d for d in base.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
    want = _run_slug(args.get("campaign") or "")
    d = next((c for c in camps if c.name == want), camps[0] if camps else None)
    if not d:
        return {"client": client, "campaigns": []}
    rd = lambda n, cap=20000: (d / n).read_text(encoding="utf-8")[:cap] if (d / n).exists() else None
    state = json.loads(rd("state.json") or "{}")
    spec = json.loads(rd("campaign_spec.json") or "null")
    leads = []
    if (d / "verified.jsonl").exists():
        for row in common.read_jsonl(d / "verified.jsonl")[: int(args.get("leads") or 8)]:
            leads.append({k: row.get(k) for k in ("first", "last", "title", "company", "domain", "linkedin", "email", "segment") if row.get(k)})
    return {"client": client, "campaigns": [c.name for c in camps], "campaign": d.name,
            "onboarding": (state.get("stages") or {}).get("onboarding"),
            "client_context_md": rd("client_context.md"), "icp_brief_md": rd("icp_brief.md"),
            "campaign_spec": spec, "verified_leads": leads}


def copy_rules(_):
    return {"frameworks_md": (ROOT / "stages" / "3-copy" / "reference" / "frameworks.md").read_text(encoding="utf-8"),
            "template_agents": CONFIG["octave_template_agents"]}


# ---------- MCP plumbing ----------

S = lambda props, req=(): {"type": "object", "properties": props, "required": list(req)}
LEAD = {"type": "object", "properties": {k: {"type": "string"} for k in ("first", "last", "title", "company", "domain", "linkedin", "email", "segment")}}
TOOLS = {
    "list_clients": (list_clients, "Client names from the Airtable Clients table (Business column). No keys.", S({}), True),
    "check_client": (check_client, "For one client: is the Smartlead key in Airtable and does it work, and which Octave key runs the agents. Never returns a key.",
                     S({"client": {"type": "string"}}, ["client"]), True),
    "smartlead_learnings": (smartlead_learnings, "The client's Smartlead campaign performance (per unique lead) and the sequence copy of its best and worst campaigns, using the client's own key from Airtable.",
                            S({"client": {"type": "string"}, "top": {"type": "integer"}, "scan": {"type": "integer"}}, ["client"]), True),
    "octave_context": (octave_context, "What Octave knows about the client (company, offers, personas, segments, proof, brand voice), from the client's own Octave workspace when Airtable has its key and MCP URL, else matching entities in the Cymate workspace. Optional query runs a knowledge-base search (1 Octave credit).",
                       S({"client": {"type": "string"}, "query": {"type": "string"}}, ["client"]), True),
    "onboarding_context": (onboarding_context, "The client's onboarding form answers (Airtable Onboarding Client table), its call transcripts (Transcript Intake) and Clients notes. No secrets.",
                           S({"client": {"type": "string"}, "transcripts": {"type": "integer"}}, ["client"]), True),
    "sample_leads": (sample_leads, "Real prospects (name, title, company, domain) from the client's Smartlead campaigns, for test copy when there is no verified list.",
                     S({"client": {"type": "string"}, "n": {"type": "integer"}}, ["client"]), True),
    "agent_template": (agent_template, "The live instructions, web search instructions and output schema of one Cymate template agent in Octave (TFKD, STANDARD_GO_TO, TALKING_TO_OTHER_FOLKS, TWO_SENTENCE_PAIN, POKE_THE_BEAR).",
                       S({"framework": {"type": "string"}}, ["framework"]), True),
    "pipeline_run": (pipeline_run, "The pipeline's saved work for the client on this laptop: stage 1 client_context.md, icp_brief.md and the chosen group + offer, stage 2 verified leads, stage 3 campaign_spec.json.",
                     S({"client": {"type": "string"}, "campaign": {"type": "string"}, "leads": {"type": "integer"}}, ["client"]), True),
    "copy_rules": (copy_rules, "Cymate frameworks, house style and the template agent ids (stages/3-copy/reference/frameworks.md).", S({}), True),
    "start_agent_runs": (start_agent_runs, "Start Octave template agent runs (about 2 credits each) for up to 15 leads. Returns job ids; poll get_agent_runs.",
                         S({"client": {"type": "string"}, "framework": {"type": "string"}, "brief": {"type": "string"},
                            "leads": {"type": "array", "items": LEAD}, "segment": {"type": "string"}, "extra_instructions": {"type": "string"}},
                           ["client", "framework", "brief", "leads"]), False),
    "get_agent_runs": (get_agent_runs, "Status and results of agent runs started with start_agent_runs.",
                       S({"job_ids": {"type": "array", "items": {"type": "string"}}}, ["job_ids"]), True),
}


def send(msg):
    PROTO_OUT.buffer.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
    PROTO_OUT.buffer.flush()


def handle(req):
    m, rid = req.get("method"), req.get("id")
    if m == "initialize":
        return {"protocolVersion": (req.get("params") or {}).get("protocolVersion") or "2024-11-05",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "cymate_copy", "version": VERSION}}
    if m == "ping":
        return {}
    if m == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s, "annotations": {"readOnlyHint": ro}}
                          for n, (_, d, s, ro) in TOOLS.items()]}
    if m == "tools/call":
        p = req.get("params") or {}
        t = TOOLS.get(p.get("name"))
        if not t:
            raise ValueError(f"unknown tool {p.get('name')}")
        try:
            res = t[0](p.get("arguments") or {})
            return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False)}], "structuredContent": res}
        except ToolError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    if rid is None:
        return None  # notifications
    raise LookupError(m)


def serve():
    lock = threading.Lock()

    def one(req):
        try:
            res = handle(req)
            if req.get("id") is not None:
                with lock:
                    send({"jsonrpc": "2.0", "id": req["id"], "result": res})
        except LookupError as e:
            with lock:
                send({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": f"method not found: {e}"}})
        except Exception as e:  # noqa: BLE001
            with lock:
                send({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32603, "message": str(e)}})

    calls = ThreadPoolExecutor(6)  # a slow Smartlead read never blocks a job poll
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if req.get("method") in ("initialize", "tools/list", "ping") or req.get("id") is None:
            one(req)
        else:
            calls.submit(one, req)


if __name__ == "__main__":
    serve()

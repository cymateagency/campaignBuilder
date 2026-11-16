"""Write the full Email 1 for each lead and slot with the Octave template agents.

  python stages/3-copy/octave_copy.py <run_dir> --client "<client>" --test 8   # first 8 leads, writes copy_test.md for CSM review
  python stages/3-copy/octave_copy.py <run_dir> --client "<client>"            # every lead in verified.jsonl

Octave key: the client's own "Octave API Key" from Airtable when filled (it must belong to the Cymate workspace,
where the agents live), otherwise the Cymate row's key. Without --client the Cymate row's key is used.

Reads <run_dir>/campaign_spec.json:
  {"brief": "<campaign brief text>",
   "slots": {"LONG": {"framework": "STANDARD_GO_TO", "fallback_subject": "...", "fallback_body": "..."}, "MEDIUM": {...}, ...},
   "segment_field": "segment"}            # optional: lead field passed as "Segment: <value>" (aiark_pull.py sets "segment")
Template agents (one per framework, reused across clients) are in config.json -> octave_template_agents.
Stops before spending if a slot's agent OID is missing, or a fallback is still the "..." placeholder.
Each agent returns JSON: {"subject", "body", "ps", "confidence": "high"|"low", "fact_used", "source_url"}.
"ps" is only used by frameworks with a P.S. (Standard Go-To); it is placed after the sign-off.
The brief is the only source of truth: the agents live in the shared Cymate Octave workspace and are told to ignore its library.
Low confidence or a failed run falls back to the slot's fallback copy. ~2 Octave credits per run.
The full run reuses the test leads' copy when campaign_spec.json hasn't changed since the test, so they aren't paid for twice.
Approval loop (stages/3-copy/approvals.py): --test N (5+) -> CSM approves -> client reviews client_review.md -> feedback rounds -> client approves;
the full run (no --test) refuses to start before the client approved the current campaign_spec.json.
Free script checks on every agent email (qa): the greeting is always rewritten to the lead's real first name; a source
that looks like a different company's site (smartbank.co.jp for smartbank.com) sends the fallback; dashes, >110 words,
sentences over 30 words and a misspelled client name are flagged in copy_test.md for the reviewer.
After changing an agent's instructions in Octave, pass --fresh: cached answers came from the old instructions.
"""
import hashlib, json, re, sys, threading, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import http, octave_key, add_spend, set_stage, read_jsonl, write_jsonl, CONFIG

URL = "https://app.octavehq.com/api/v2/agents/generate-content/run"
CLIENT = None  # set from --client
WORKERS = 12  # emails written at the same time; --workers N to change
FRESH = False  # --fresh: ignore cached answers (after an agent was changed)


def lead_id(l):
    return l.get("aiark_id") or l.get("email")


def run_agent(agent, lead, brief, segment):
    """Returns (output dict or None, attempted). attempted is True once the request reached Octave."""
    ctx = brief + (f"\n\nSegment: {segment}" if segment else "")
    body = {"agentOId": agent, "firstName": lead.get("first"), "lastName": lead.get("last"), "jobTitle": lead.get("title"),
            "linkedInProfile": lead.get("linkedin"), "companyName": lead.get("company"), "companyDomain": lead.get("domain"),
            "email": lead.get("email"), "outputFormat": "JSON", "runtimeContext": ctx}
    st, js = http("POST", URL, body, {"api_key": octave_key(CLIENT)}, timeout=300)
    if st != 200 or not isinstance(js, dict):
        if st == 0:
            print(f"  Octave did not answer in time for {lead.get('company')} ({agent}); using fallback copy", flush=True)
        return None, True  # it reached Octave (or timed out there), so it may be charged
    data = js.get("data") or {}
    out = data.get("jsonContent")
    if not out and data.get("content"):
        try:
            out = json.loads(data["content"])
        except (TypeError, json.JSONDecodeError):
            out = None
    return (out if isinstance(out, dict) else None), True


class RunCache:
    """Every agent answer, saved the moment it arrives (copy_cache.jsonl in the run folder), keyed by
    lead + slot + campaign_spec version. A crash or re-run never pays twice for the same email."""

    def __init__(self, d, spec_hash):
        self.path, self.spec_hash, self.lock = Path(d) / "copy_cache.jsonl", spec_hash, threading.Lock()
        self.data = {}
        if self.path.exists():
            for row in read_jsonl(self.path):
                self.data[row["key"]] = row["out"]

    def key(self, lead, slot):
        return f"{lead_id(lead)}|{slot}|{self.spec_hash}"

    def get(self, lead, slot):
        return self.data.get(self.key(lead, slot))

    def put(self, lead, slot, out):
        k = self.key(lead, slot)
        with self.lock:
            self.data[k] = out
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": k, "out": out}) + "\n")


CACHE = None  # set in main


_spend_lock = threading.Lock()

GREETING = re.compile(r"^\s*(hey|hi|hello)\b[^,\n]{0,40},", re.I)
NAME_TOKEN = re.compile(r"\{\{?\s*first[ _]?name\s*\}?\}", re.I)
DASHES = re.compile(r" [-–—] |[–—]")


def first_name(lead):
    return (lead.get("first") or "there").strip().split(" ")[0].title()


def fix_greeting(body, lead):
    """The greeting always uses the lead's real first name, whatever the agent wrote ("{first name}",
    or a name it picked up from the fact)."""
    body = NAME_TOKEN.sub(first_name(lead), body or "")
    if GREETING.match(body):
        return GREETING.sub(f"Hey {first_name(lead)},", body, count=1)
    return f"Hey {first_name(lead)},\n\n{body.lstrip()}"


def _host(url):
    try:
        return urllib.parse.urlparse(url if "//" in url else "//" + url).hostname or ""
    except ValueError:
        return ""


def client_name(spec):
    m = re.match(r"\s*CLIENT:\s*(.+?)\s+-\s", spec.get("brief", ""))
    return m.group(1).strip() if m else None


def qa(out, lead, spec):
    """Free checks on an agent email. Returns (hard, flags): hard ones send the fallback instead."""
    hard, flags = [], []
    body = out.get("body") or ""
    dom = (lead.get("domain") or "").lower().removeprefix("www.")
    host = _host(out.get("source_url") or "").lower().removeprefix("www.")
    label = dom.split(".")[0] if dom else ""
    if host and label and label in host and not (host == dom or host.endswith("." + dom)):
        hard.append(f"source {host} looks like a different company than {dom}")
    about = (out.get("fact_used") or "").split(":", 1)[0].strip().lower()
    company = (lead.get("company") or "").lower()
    norm = lambda x: re.sub(r"[^a-z0-9]", "", x)
    generic = {"the", "and", "inc", "llc", "ltd", "corp", "corporation", "company", "group", "holdings", "nasdaq", "nyse",
               "bank", "banks", "bancorp", "financial", "credit", "capital", "trust", "savings", "federal", "mortgage",
               "first", "national", "american", "united", "security", "community", "citizens", "state", "international"}
    core = [w for w in re.findall(r"[a-z0-9]+", company) if len(w) > 2 and w not in generic]
    about_words = set(re.findall(r"[a-z0-9]+", about))
    if about and not (norm(about) in norm(company) or norm(company) in norm(about) or (label and label in norm(about))
                      or any(w in about_words for w in core)):
        hard.append(f"fact is about '{about}', not {lead.get('company')}")
    brief = spec.get("brief", "")
    if "1 to 2 weeks" in brief:
        loose_weeks = [m.group(0) for m in re.finditer(r"\b\d+\s+weeks?\b", body)
                       if not re.search(r"1 to 2 weeks$", body[:m.end()])]
        if loose_weeks:
            flags.append(f"timeline {loose_weeks} (brief says 1 to 2 weeks)")
    if DASHES.search(body):
        flags.append("dash in body")
    words = len(body.split())
    if words > 110:
        flags.append(f"{words} words (max 110)")
    name = client_name(spec)
    if name:
        loose = re.compile(re.escape(name).replace(r"\-", r"[\s-]?"), re.I)
        variants = {m.group(0) for m in loose.finditer(body)}
        if any(v != name for v in variants):
            flags.append(f"client name written as {sorted(variants)} (should be {name})")
    longest = max((len(x.split()) for x in re.split(r"[.?!]\s", body) if x.strip()), default=0)
    if longest > 30:
        flags.append(f"a {longest} word sentence (keep under 30)")
    return hard, flags


def write_slot(lead, slot, spec, spend):
    """One email: one agent run for one lead and one framework slot (or its cached answer)."""
    cfg = spec["slots"][slot]
    seg = lead.get(spec.get("segment_field", "segment"))
    agent = CONFIG["octave_template_agents"][cfg["framework"]]
    out = CACHE.get(lead, slot) if CACHE else None
    if out is None:
        out, attempted = run_agent(agent, lead, spec["brief"], seg)
        with _spend_lock:
            spend["octave_runs"] += 1 if attempted else 0  # a run that returned bad JSON is still charged
        if out is not None and CACHE:
            CACHE.put(lead, slot, out)
    else:
        with _spend_lock:
            spend["cached"] += 1
    ok = bool(out) and str(out.get("confidence", "")).lower() == "high" and bool(out.get("body"))
    s = slot.lower()
    hard, flags = qa(out, lead, spec) if ok else ([], [])
    flags = [f for f in flags if not f.startswith("timeline")]  # auto-corrected below
    if hard:  # a check the agent should never fail: don't send it, use the fallback
        ok = False
    lead[f"qa_{s}"] = hard + flags
    lead[f"subject_{s}"] = (out.get("subject") or cfg.get("fallback_subject", "")) if ok else cfg.get("fallback_subject", "")
    fb = cfg.get("fallback_body", "").replace("{first_name}", first_name(lead))
    body = fix_greeting(out["body"], lead) if ok else fb
    if ok and "1 to 2 weeks" in spec.get("brief", ""):  # the approved claim; agents shorten it to "2 weeks"
        body = re.sub(r"(?<!1 to )\b(in|within) 2 weeks\b", r"\1 1 to 2 weeks", body)
    lead[f"email_{s}"] = body
    lead[f"ps_{s}"] = (out.get("ps") or "").strip() if ok else cfg.get("fallback_ps", "")
    lead[f"copy_{s}_source"] = "agent" if ok else "fallback"
    lead[f"fact_{s}"] = (out or {}).get("fact_used", "")
    lead[f"source_url_{s}"] = (out or {}).get("source_url", "")
    return lead


def write_lead(lead, spec, spend):
    for slot in spec["slots"]:
        write_slot(lead, slot, spec, spend)
    return lead


def check_spec(spec, leads):
    """Stop before any credit is spent on a setup that can only produce fallback or placeholder copy."""
    problems = []
    if not spec.get("brief", "").lstrip().startswith("CLIENT:"):
        problems.append("brief must start with 'CLIENT: <name> - <what the company is>' (the agents refuse to write without it)")
    for slot, cfg in spec["slots"].items():
        agent = CONFIG["octave_template_agents"].get(cfg.get("framework"), "")
        if not agent or agent.startswith("TODO"):
            problems.append(f"{slot}: no Octave agent OID for framework '{cfg.get('framework')}' in config.json")
        for k in ("fallback_subject", "fallback_body"):
            if not (cfg.get(k) or "").strip() or cfg.get(k, "").strip() == "...":
                problems.append(f"{slot}: {k} is empty or still the '...' placeholder")
    if problems:
        sys.exit("campaign_spec.json / config.json not ready:\n  " + "\n  ".join(problems))
    field = spec.get("segment_field", "segment")
    missing = sum(1 for l in leads if not l.get(field))
    if "SEGMENTS:" in spec.get("brief", "") and missing:
        print(f"WARNING: {missing} of {len(leads)} leads have no '{field}', so the agent gets no 'Segment:' line for them. "
              f"Set \"segment\" in list_spec.json before the pull, or add the field to verified.jsonl.")


def main(d, test_n=None):
    d = Path(d)
    spec_txt = (d / "campaign_spec.json").read_text(encoding="utf-8")
    spec = json.loads(spec_txt)
    spec_hash = hashlib.sha256(spec_txt.encode()).hexdigest()[:16]
    global CACHE
    CACHE = RunCache(d, spec_hash + ("|fresh" + str(int(__import__('time').time())) if FRESH else ""))
    leads = read_jsonl(d / "verified.jsonl")
    if test_n:
        leads = leads[:test_n]
    check_spec(spec, leads)
    if test_n is not None and test_n < 5:
        sys.exit("the CSM reviews at least 5 examples: use --test 5 or more")
    if not test_n:
        from approvals import require_client_approval
        require_client_approval(d, "The full copy run")

    reuse = {}
    test_file = d / "copy_test.jsonl"
    if not test_n and test_file.exists():
        tested = read_jsonl(test_file)
        if tested and all(t.get("_spec_hash") == spec_hash for t in tested):
            reuse = {lead_id(t): t for t in tested if lead_id(t)}
        else:
            print("campaign_spec.json changed since the test run, so the test leads are written again")
    todo = [l for l in leads if lead_id(l) not in reuse]
    runs = len(todo) * len(spec["slots"])
    print(f"{len(todo)} leads x {len(spec['slots'])} slots = {runs} runs (~{2 * runs} Octave credits)"
          + (f"; reusing approved test copy for {len(leads) - len(todo)} leads" if reuse else ""))
    spend = Counter()
    done = Counter()
    jobs = [(l, slot) for l in todo for slot in spec["slots"]]  # every email runs in parallel, not lead by lead

    def one(job):
        l, slot = job
        write_slot(l, slot, spec, spend)
        with _spend_lock:
            done["n"] += 1
            n = done["n"]
        print(f"  {n}/{len(jobs)} emails written ({l.get('company')}, {slot})", flush=True)

    try:
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(one, jobs))
        written = {lead_id(l): l for l in todo}
    finally:
        add_spend(d, "octave_runs", spend["octave_runs"])
    leads = [reuse.get(lead_id(l)) or written.get(lead_id(l)) or l for l in leads]
    for l in leads:
        l["_spec_hash"] = spec_hash
    name = "copy_test" if test_n else "copy"
    write_jsonl(d / f"{name}.jsonl", leads)
    if test_n:
        md = []
        for l in leads:
            md.append(f"## {l.get('full')} - {l.get('title')} @ {l.get('company')} (segment: {l.get(spec.get('segment_field', 'segment')) or 'none'})\n")
            for slot in spec["slots"]:
                s = slot.lower()
                md.append(f"**{CONFIG['slot_names'].get(slot, slot)} ({spec['slots'][slot]['framework']}, {l[f'copy_{s}_source']})**  \n"
                          f"Subject: {l.get(f'subject_{s}')}\n\n{l.get(f'email_{s}')}\n\n"
                          + (f"{l.get(f'ps_{s}')}\n\n" if l.get(f'ps_{s}') else "")
                          + f"Fact: {l.get(f'fact_{s}')} {l.get(f'source_url_{s}')}\n"
                          + (f"\nQA: {'; '.join(l.get(f'qa_{s}'))}\n" if l.get(f'qa_{s}') else "\nQA: passed the script checks\n"))
        (d / "copy_test.md").write_text("\n".join(md), encoding="utf-8")
    src = Counter(l[f"copy_{s.lower()}_source"] for l in leads for s in spec["slots"])
    set_stage(d, "copy_test" if test_n else "copy", done=True, sources=dict(src), spec_hash=spec_hash)
    print(f"done: {dict(src)} | octave runs this call: {spend['octave_runs']} (reused from cache: {spend['cached']}) -> {name}.jsonl" + (" and copy_test.md" if test_n else ""))


if __name__ == "__main__":
    a = sys.argv
    if len(a) < 2:
        sys.exit('usage: octave_copy.py <run_dir> [--client "<client>"] [--test N] [--workers 12] [--fresh]')
    CLIENT = a[a.index("--client") + 1] if "--client" in a else None
    WORKERS = int(a[a.index("--workers") + 1]) if "--workers" in a else WORKERS
    FRESH = "--fresh" in a
    main(a[1], int(a[a.index("--test") + 1]) if "--test" in a else None)

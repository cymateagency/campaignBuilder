"""Shared helpers: config, keys from Airtable, HTTP with retries, run state."""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from pathlib import Path

# Windows consoles default to cp1252: print names like "Łukasz" without crashing.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
_KEYS = {}


def http(method, url, body=None, headers=None, retries=4, timeout=90):
    """JSON request with retry on 429/5xx. Returns (status, parsed_json_or_text).
    A timeout or network error never raises: GETs are retried, other methods return (0, "network error: ...")
    because the server may still have done (and charged for) the work."""
    try:
        return _http(method, url, body, headers, retries, timeout)
    except (TimeoutError, OSError, urllib.error.URLError) as e:  # URLError/HTTPError subclass OSError
        if method == "GET" and retries > 0:
            time.sleep(5)
            return http(method, url, body, headers, retries - 1, timeout)
        return 0, f"network error: {e}"


def _http(method, url, body=None, headers=None, retries=4, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    h.update(headers or {})
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return r.status, json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return r.status, raw.decode(errors="replace")
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After") or 0) or 2 ** (attempt + 1)
                time.sleep(wait)
                continue
            try:
                return e.code, json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return e.code, raw.decode(errors="replace")
    return 0, "no response"


def airtable_token():
    """AIRTABLE_TOKEN from the environment, or on Windows from the value saved with setx
    (a terminal opened before setx doesn't see it yet). None if not set."""
    tok = os.environ.get("AIRTABLE_TOKEN")
    if not tok and sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                tok = winreg.QueryValueEx(k, "AIRTABLE_TOKEN")[0]
        except OSError:
            tok = None
        if tok:
            os.environ["AIRTABLE_TOKEN"] = tok
    return tok or None


def _airtable(path, params=None):
    tok = airtable_token()
    if not tok:
        sys.exit("Set AIRTABLE_TOKEN (Airtable personal access token) in your environment.")
    q = ("?" + urllib.parse.urlencode(params, doseq=True)) if params else ""
    st, js = http("GET", f"https://api.airtable.com/v0/{path}{q}", headers={"Authorization": f"Bearer {tok}"})
    if st != 200:
        sys.exit(f"Airtable error {st}: {js}")
    return js


_RECORD_IDS, _RECORDS = {}, {}


def _client_record_id(name):
    """Record id of the Clients row whose Business field equals name (case-insensitive). Only the name field is read."""
    k = name.strip().lower()
    if k in _RECORD_IDS:
        return _RECORD_IDS[k]
    at = CONFIG["airtable"]
    nf = at["client_name_field"]
    hits, close, offset = [], [], None
    while True:
        params = {"returnFieldsByFieldId": "true", "pageSize": 100, "fields[]": nf}
        if offset:
            params["offset"] = offset
        js = _airtable(f"{at['base']}/{at['clients_table']}", params)
        for rec in js.get("records", []):
            v = str((rec.get("fields") or {}).get(nf) or "").strip()
            if v.lower() == k:
                hits.append(rec["id"])
            elif k in v.lower() or (v and v.lower() in k):
                close.append(v)
        offset = js.get("offset")
        if not offset:
            break
    if not hits:
        sys.exit(f"No row in the Airtable Clients table with Business = '{name}'."
                 + (f" Close matches: {', '.join(sorted(set(close))[:8])}" if close else ""))
    if len(hits) > 1:
        sys.exit(f"{len(hits)} rows in the Clients table have Business = '{name}'. Make the name unique in Airtable.")
    _RECORD_IDS[k] = hits[0]
    return hits[0]


def _record_fields(rec_id):
    """All fields of one Clients row, reachable by field id AND by field name."""
    if rec_id not in _RECORDS:
        at = CONFIG["airtable"]
        path = f"{at['base']}/{at['clients_table']}/{rec_id}"
        by_name = _airtable(path).get("fields") or {}
        by_id = _airtable(path, {"returnFieldsByFieldId": "true"}).get("fields") or {}
        _RECORDS[rec_id] = {**by_name, **by_id}
    return _RECORDS[rec_id]


def _field(record_name, field, label):
    val = _record_fields(_client_record_id(record_name)).get(field)
    if isinstance(val, list):  # lookup fields come back as lists
        val = next((x for x in val if x), None)
    if not val or not str(val).strip():
        sys.exit(f"Airtable Clients row '{record_name}' has no value in '{field}' ({label}). Fill it in Airtable and re-run.")
    return str(val).strip()


def tool_key(name):
    """Shared key (aiark, aiark_webhook, leadmagic, icypeas, millionverifier, bounceban, octave),
    read from the Cymate row of the Clients table."""
    if name not in _KEYS:
        at = CONFIG["airtable"]
        _KEYS[name] = _field(at["cymate_record"], at["shared_fields"][name], name)
    return _KEYS[name]


def optional_tool_key(name):
    """Like tool_key, but None when config.json maps the key to no field (null)."""
    return tool_key(name) if CONFIG["airtable"]["shared_fields"].get(name) else None


def client_value(client, name):
    """Per-client value (smartlead, octave_mcp_url) from that client's row of the Clients table."""
    ck = f"{name}:{client.strip().lower()}"
    if ck not in _KEYS:
        _KEYS[ck] = _field(client, CONFIG["airtable"]["client_fields"][name], name)
    return _KEYS[ck]


def smartlead_key(client):
    return client_value(client, "smartlead")


def octave_workspace(mcp_url):
    """Workspace id inside an Octave MCP URL (the ctx parameter is base64 JSON), or None."""
    import base64
    try:
        ctx = urllib.parse.parse_qs(urllib.parse.urlparse(mcp_url).query).get("ctx", [""])[0]
        ctx += "=" * (-len(ctx) % 4)
        return json.loads(base64.urlsafe_b64decode(ctx)).get("workspace_o_id")
    except Exception:
        return None


def octave_key(client=None):
    """Octave key that runs the template agents. The client's own key when its row has one and its
    Octave MCP URL is the Cymate workspace (where the agents live); otherwise the Cymate row's key."""
    ck = f"octave_for:{(client or '').strip().lower()}"
    if ck in _KEYS:
        return _KEYS[ck]
    want = CONFIG["octave_workspace"]
    key = None
    if client:
        f = _record_fields(_client_record_id(client))
        own = str(f.get(CONFIG["airtable"]["client_fields"]["octave"]) or "").strip()
        url = str(f.get(CONFIG["airtable"]["client_fields"]["octave_mcp_url"]) or "").strip()
        if own:
            ws = octave_workspace(url)
            if ws and ws != want:
                sys.exit(f"{client}'s Octave key is for workspace {ws}, but the template agents live in the Cymate "
                         f"workspace ({want}). Leave the client's Octave key empty to use the Cymate row's key.")
            key = own
            if not ws:
                print(f"NOTE: {client} has no readable Octave MCP URL, so its Octave workspace can't be checked")
    _KEYS[ck] = key or tool_key("octave")
    return _KEYS[ck]


def run_dir(client, campaign):
    d = ROOT / "runs" / client.lower().replace(" ", "-") / campaign.lower().replace(" ", "-")
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(d):
    p = Path(d) / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"stages": {}, "spend": {}}


def save_state(d, state):
    (Path(d) / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def add_spend(d, tool, amount):
    s = load_state(d)
    s["spend"][tool] = s["spend"].get(tool, 0) + amount
    save_state(d, s)


def read_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def set_stage(d, stage, **info):
    s = load_state(d)
    s["stages"].setdefault(stage, {}).update(info)
    save_state(d, s)


# ---- email signature (Cymate format, as in the live client campaigns) ----
NO_LINK_DOT = "․"  # one dot leader: looks like "." but email clients don't turn clear-tech.com into a link


def signature_parts(spec):
    """campaign_spec.json "signature": {"closers": [...], "titles": [...], "website": "clear-tech.com"}."""
    sig = spec.get("signature") or {}
    closers = [c for c in sig.get("closers") or [] if c.strip()]
    titles = [t for t in sig.get("titles") or [] if t.strip()]
    website = (sig.get("website") or "").strip().removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")
    missing = [k for k, v in (("closers", closers), ("titles", titles), ("website", website)) if not v]
    if missing:
        sys.exit(f'campaign_spec.json "signature" is missing {missing}. Example: {{"closers": ["Appreciate it", "Best regards", "Thanks"], '
                 '"titles": ["Client Partner"], "website": "clear-tech.com"}')
    return closers, titles, website


def _spin(items):
    return items[0] if len(items) == 1 else "{" + "|".join(items) + "}"


def signature_html(spec):
    """Closer spintax, sender first name, title spintax, website that is not a link."""
    closers, titles, website = signature_parts(spec)
    return (f"<div>{_spin(closers)},</div><div>%sender-firstname%</div>"
            f"<div>{_spin(titles)}</div><div>{website.replace('.', NO_LINK_DOT)}</div>")


def signature_text(spec, first_name="<sender first name>"):
    closers, titles, website = signature_parts(spec)
    return f"{closers[0]},\n{first_name}\n{titles[0]}\n{website}"

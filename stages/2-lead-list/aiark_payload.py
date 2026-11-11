"""Turn a list spec into (1) the AI Ark in-app payload the CSM pastes into Search Payload and
(2) the API body we pull with. Also normalizes an API payload the CSM copies back from the app.

Usage:
  python stages/2-lead-list/aiark_payload.py build  <spec.json>  <out_dir>   # writes inapp_payload.json + api_body.json
  python stages/2-lead-list/aiark_payload.py approve <api_payload.json> <out_dir>  # CSM's approved API payload -> api_body.json

Key mapping is in reference/aiark_payload_map.md. Keys marked UNVERIFIED there are inferred.
"""
import json, sys
from pathlib import Path

EMPLOYEE_PRESETS = {
    "1-10": (1, 10), "11-20": (11, 20), "21-50": (21, 50), "51-100": (51, 100), "101-200": (101, 200),
    "201-500": (201, 500), "501-1000": (501, 1000), "1001-2000": (1001, 2000), "2001-5000": (2001, 5000),
    "5001-10000": (5001, 10000), "10001+": (10001, None),
}
# Verified labels: $0.1M-$0.5M, $0.5M-$1M, $5M-$10M ... $100M-$500M. Higher labels follow AI Ark's data buckets (UNVERIFIED in app).
REVENUE_PRESETS = {
    "$0.1M-$0.5M": (100_000, 500_000), "$0.5M-$1M": (500_000, 1_000_000), "$1M-$5M": (1_000_000, 5_000_000),
    "$5M-$10M": (5_000_000, 10_000_000), "$10M-$25M": (10_000_000, 25_000_000), "$25M-$50M": (25_000_000, 50_000_000),
    "$50M-$100M": (50_000_000, 100_000_000), "$100M-$500M": (100_000_000, 500_000_000),
    "$500M-$1B": (500_000_000, 1_000_000_000), "$1B-$5B": (1_000_000_000, 5_000_000_000),
    "$5B-$10B": (5_000_000_000, 10_000_000_000), "$10B+": (10_000_000_000, None),
}
REVENUE_SHORTCUTS = {  # team default: $25M+ (app has presets only, so the API uses the same buckets)
    "25M+": ["$25M-$50M", "$50M-$100M", "$100M-$500M", "$500M-$1B", "$1B-$5B", "$5B-$10B", "$10B+"],
    "10M+": ["$10M-$25M", "$25M-$50M", "$50M-$100M", "$100M-$500M", "$500M-$1B", "$1B-$5B", "$5B-$10B", "$10B+"],
}


def _rng(pairs):
    out = []
    for s, e in pairs:
        r = {"start": s}
        if e is not None:
            r["end"] = e
        out.append(r)
    return out


def _loc_str(l):
    return " ".join(x for x in (l.get("continent"), l.get("country"), l.get("state")) if x)


def _inc_exc(d, mode=None):
    """{'include':[..],'exclude':[..]} -> API any-block, optional text mode."""
    blk = {}
    for k in ("include", "exclude"):
        vals = d.get(k) or []
        if vals:
            blk[k] = {"mode": mode, "content": vals} if mode else vals
    return {"any": blk} if blk else None


def _dur(years_min=None, years_max=None):
    d = {}
    if years_min is not None:
        d["min"] = {"year": int(years_min), "month": 0}
    if years_max is not None:
        d["max"] = {"year": int(years_max), "month": 0}  # UNVERIFIED key
    return d


def _dur_app(years_min=None, years_max=None):
    d = {}
    if years_min is not None:
        d["from"] = {"years": int(years_min)}
    if years_max is not None:
        d["to"] = {"years": int(years_max)}  # UNVERIFIED key
    return d


def build(spec):
    app, contact, account, api_only = {}, {}, {}, []

    # --- titles (Word Match is the Cymate rule) ---
    t = spec.get("titles") or {}
    mode = t.get("match", "WORD")
    title_api = {}
    if t.get("include") or t.get("exclude"):
        if t.get("include"):
            app["include_latest_title"] = t["include"]
        if t.get("exclude"):
            app["exclude_latest_title"] = t["exclude"]
        title_api.update(_inc_exc(t, mode))
    if t.get("all"):
        app["all_latest_title"] = t["all"]
        title_api["all"] = {"include": {"mode": mode, "content": t["all"]}}
    if title_api:
        app["exact_match"] = {k: mode for k in ("include_latest_title", "exclude_latest_title", "all_latest_title") if k in app}
        app["latest_active_job_title_only"] = False
        contact.setdefault("experience", {}).setdefault("latest", {})["title"] = title_api

    # --- seniority / department ---
    s = spec.get("seniority") or {}
    if s.get("include"):
        app["include_seniority"] = [x.upper() for x in s["include"]]
    if s.get("exclude"):
        app["exclude_seniority"] = [x.upper() for x in s["exclude"]]  # UNVERIFIED app key
    if s:
        contact["seniority"] = _inc_exc({k: [x.upper() for x in v] for k, v in s.items()})
    dep = spec.get("department") or {}
    if dep.get("include"):
        app["include_department_and_function"] = dep["include"]
        contact["departmentAndFunction"] = _inc_exc(dep)

    # --- time in role / company / experience ---
    for key, app_key, api_key in (("time_in_role", "time_in_current_job_role", "currentJob"),
                                  ("time_in_company", "time_in_current_company", "currentCompany"),
                                  ("total_experience", "time_in_work_experience", "total")):
        v = spec.get(key)
        if v:
            app[app_key] = _dur_app(v.get("min_years"), v.get("max_years"))
            contact.setdefault("experience", {}).setdefault("current", {}).setdefault("duration", {})[api_key] = \
                _dur(v.get("min_years"), v.get("max_years"))

    # --- skills / languages ---
    sk = spec.get("skills") or {}
    if sk:
        if sk.get("include"):
            app["include_skills"] = sk["include"]
            app.setdefault("exact_match", {})["include_skills"] = sk.get("match", "WORD")
        if sk.get("exclude"):
            app["exclude_skills"] = sk["exclude"]
        blk = {}
        if sk.get("include"):
            blk["include"] = {"mode": sk.get("match", "WORD"), "content": sk["include"]}
        if sk.get("exclude"):
            blk["exclude"] = {"mode": "SMART", "content": sk["exclude"]}
        contact["skill"] = {"any": blk}

    # --- locations ---
    for key, app_inc, app_exc, target in (("person_location", "location_include", "location_exclude", contact),
                                          ("hq_location", "location_include_account", "location_exclude_account", account)):
        loc = spec.get(key) or {}
        if loc.get("include"):
            app[app_inc] = loc["include"]
        if loc.get("exclude"):
            app[app_exc] = loc["exclude"]
        if loc:
            target["location"] = _inc_exc({k: [_loc_str(x) for x in v] for k, v in loc.items()})

    # --- company size / revenue ---
    emp = spec.get("employees") or {}
    if emp.get("presets"):
        app["employee_size_predefined"] = emp["presets"]
        account["employeeSize"] = {"type": "RANGE", "range": _rng(EMPLOYEE_PRESETS[p] for p in emp["presets"])}
    elif emp.get("min") is not None or emp.get("max") is not None:
        app["employee_size_custom"] = {k: emp[k] for k in ("min", "max") if emp.get(k) is not None}
        lo = emp.get("min") if emp.get("min") is not None else 1  # a max-only range still needs a start
        account["employeeSize"] = {"type": "RANGE", "range": _rng([(lo, emp.get("max"))])}
    rev = spec.get("revenue")
    if rev:
        presets = REVENUE_SHORTCUTS[rev] if isinstance(rev, str) else rev["presets"]
        app["annual_revenue_predefined"] = presets
        account["revenue"] = {"type": "RANGE", "range": _rng(REVENUE_PRESETS[p] for p in presets)}

    # --- industry / type / tech / products / naics / funding ---
    ind = spec.get("industry") or {}
    if ind:
        if ind.get("include"):
            app["include_industry"] = ind["include"]
        if ind.get("exclude"):
            app["exclude_industry"] = ind["exclude"]
        account["industries"] = _inc_exc(ind, "SMART")
    ct = spec.get("company_type") or {}
    if ct:
        up = {k: [x.upper() for x in v] for k, v in ct.items()}
        if up.get("include"):
            app["company_type_include_any"] = up["include"]
        if up.get("exclude"):
            app["company_type_exclude"] = up["exclude"]
        account["type"] = _inc_exc(up)
    tech = spec.get("technologies") or {}
    if tech:
        if tech.get("include"):
            app["include_technologies"] = tech["include"]
        if tech.get("exclude"):
            app["exclude_technologies"] = tech["exclude"]
        account["technologies"] = _inc_exc(tech, "SMART")
    ps = spec.get("products_and_services") or {}
    if ps:
        if ps.get("include"):
            app["include_products_and_services"] = ps["include"]
        if ps.get("exclude"):
            app["exclude_products_and_services"] = ps["exclude"]
        account["productAndServices"] = _inc_exc(ps, "WORD")
    na = spec.get("naics") or {}
    if na:
        if na.get("include"):
            app["naics_include_any"] = na["include"]
        if na.get("exclude"):
            app["naics_exclude_any"] = na["exclude"]
        account["naics"] = _inc_exc(na)
    if spec.get("funding"):
        app["funding_type"] = [x.upper() for x in spec["funding"]]
        account["funding"] = {"type": app["funding_type"]}

    # --- company keywords (in-app verified; API shape UNVERIFIED) ---
    kw = spec.get("company_keywords") or {}
    if kw.get("include"):
        src = kw.get("sources", ["Company Description", "Company Name", "SEO Description", "Product & Services"])
        app["companies_include_keywords"] = kw["include"]
        app["companies_include_keywords_sources_search_match"] = {s: "Word Match" for s in src}
        account["keyword"] = {"any": {"include": {"mode": "WORD", "content": kw["include"]}}}

    # --- API only: mail gateways (no app filter) ---
    gw = spec.get("exclude_mail_security") or []
    if gw:
        account["mail"] = {"security": {"any": {"exclude": gw}}}  # UNVERIFIED shape
        api_only.append(f"Mail security excluded: {', '.join(gw)} (not available in the app, so the API count will be lower)")

    body = {"page": 0, "size": 100}
    if contact:
        body["contact"] = contact
    if account:
        body["account"] = account
    return app, body, api_only


def approve(api_payload, spec=None):
    """CSM's approved API payload (copied from the app's API Payload tab) -> pull body. Keeps their filters as is,
    then re-adds the API-only filters from the list spec (the app can't show them, so its payload never has them)."""
    body = {k: v for k, v in api_payload.items() if k in ("contact", "account", "lists")}
    body.update({"page": 0, "size": 100})
    gw = (spec or {}).get("exclude_mail_security") or []
    if gw:
        body.setdefault("account", {})["mail"] = {"security": {"any": {"exclude": gw}}}  # UNVERIFIED shape
    return body


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("build", "approve"):
        sys.exit("usage: build <spec.json> <out_dir> | approve <api_payload.txt> <out_dir>")
    cmd, src, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    raw = src.read_text(encoding="utf-8-sig")
    if cmd == "build":
        spec = json.loads(raw)
        app, body, notes = build(spec)
        (out / "inapp_payload.json").write_text(json.dumps(app, indent=2), encoding="utf-8")
        (out / "api_body.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        if src.resolve() != (out / "list_spec.json").resolve():  # approve reads it later
            (out / "list_spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
        print("wrote inapp_payload.json and api_body.json")
        for n in notes:
            print("NOTE:", n)
    elif cmd == "approve":
        start = raw.find("{")  # tolerate the 'POST https://...' line the app prints above the JSON
        sp = out / "list_spec.json"
        spec = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        body = approve(json.loads(raw[start:]), spec)
        (out / "api_body.json").write_text(json.dumps(body, indent=2), encoding="utf-8")
        print("wrote api_body.json from the CSM's approved API payload")
        if spec.get("exclude_mail_security"):
            print("NOTE: re-added mail security exclusion:", ", ".join(spec["exclude_mail_security"]))
        elif not sp.exists():
            print("NOTE: no list_spec.json in the run folder, so no API-only filters were re-added")
    else:
        sys.exit("usage: build|approve <file> <out_dir>")

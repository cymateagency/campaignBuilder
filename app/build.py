"""Build the Campaign Builder page (app/builder.src.html -> app/dist/cymate-campaign-builder.html) for publishing as a
claude.ai artifact.

  python app/build.py [run_dir]

- Satoshi (cymate.io's body face, free from Fontshare) is downloaded and embedded: artifacts can only load Google Fonts.
  The font files are not kept in the repo.
- Preview data (what the page shows when the bridge isn't connected) comes from app/preview.sample.json, a fictional
  client. app/preview.local.json, if present, overrides any of its keys; it is git-ignored, so real client details stay
  on this laptop. With a run_dir, that run's leads and emails (copy.jsonl) replace the sample leads; they are real
  people's details, so only build that way for a page you keep private. app/dist/ is git-ignored.
Publish the result with the Artifact tool and these capabilities:
  {"mcp": {"servers": [{"server": "host:cymate_copy", "tools": [<the bridge tools the page calls>]}]}, "sample": {}}
"""
import base64, json, re, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC, OUT = ROOT / "app" / "builder.src.html", ROOT / "app" / "dist" / "cymate-campaign-builder.html"
SAMPLE, LOCAL = ROOT / "app" / "preview.sample.json", ROOT / "app" / "preview.local.json"
CACHE = ROOT / ".cache" / "fonts"
TOOLS = ["list_clients", "octave_setup_status", "onboarding_context", "octave_copy_agents", "octave_seed_library"]


def satoshi():
    CACHE.mkdir(parents=True, exist_ok=True)
    css_path = CACHE / "satoshi.css"
    if not css_path.exists():
        with urllib.request.urlopen("https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&display=swap", timeout=30) as r:
            css_path.write_bytes(r.read())
    urls = re.findall(r"//cdn\.fontshare\.com[^']*\.woff2", css_path.read_text(encoding="utf-8"))
    out = {}
    for w, u in zip((400, 500, 700), urls):
        f = CACHE / f"satoshi-{w}.woff2"
        if not f.exists():
            with urllib.request.urlopen("https:" + u, timeout=30) as r:
                f.write_bytes(r.read())
        out[w] = base64.b64encode(f.read_bytes()).decode()
    return out


def run_leads(run_dir):
    p = Path(run_dir) / "copy.jsonl"
    if not p.exists():
        sys.exit(f"no {p}")
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append({"first": r.get("first"), "title": r.get("title"), "company": r.get("company"), "industry": r.get("industry"),
                     "staff": r.get("staff"), "domain": r.get("domain"), "src": r.get("copy_medium_source"), "qa": r.get("qa_medium"),
                     "subject": r.get("subject_medium"), "fact": r.get("fact_medium"), "url": r.get("source_url_medium"),
                     "email": r.get("email_medium")})
    return rows


def preview(run_dir):
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    if LOCAL.exists():
        data.update(json.loads(LOCAL.read_text(encoding="utf-8")))
        print(f"preview: {SAMPLE.name} + {LOCAL.name}")
    if run_dir:
        data["leads"] = run_leads(run_dir)
        print(f"preview: {len(data['leads'])} leads from {run_dir}")
    data.pop("_note", None)
    return data


def main():
    s = SRC.read_text(encoding="utf-8")
    data = preview(sys.argv[1] if len(sys.argv) > 1 else None)
    s = s.replace("__PREVIEW__", json.dumps(data, ensure_ascii=False).replace("</", "<" + "\\/"))
    for w, b in satoshi().items():
        s = s.replace(f"__SAT{w}__", b)
    if "<meta charset" not in s:
        s = s.replace("<title>", '<meta charset="utf-8">\n<title>', 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(s, encoding="utf-8")
    print(f"wrote {OUT} ({len(s) // 1024} KB). Capabilities: " + json.dumps(
        {"mcp": {"servers": [{"server": "host:cymate_copy", "tools": TOOLS}]}, "sample": {}}))


if __name__ == "__main__":
    main()

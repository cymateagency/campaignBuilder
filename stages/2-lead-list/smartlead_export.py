"""Export every lead email already in the client's Smartlead campaigns (the dedupe source).

  python stages/2-lead-list/smartlead_export.py <client> <run_dir>
Writes <run_dir>/already_contacted.txt (one lowercase email per line).
"""
import csv, io, sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "lib"))  # shared helpers: lib/common.py
from common import http, smartlead_key

B = "https://server.smartlead.ai/api/v1"
SKIP = ("subsequence", "no show")


def main(client, d):
    k = smartlead_key(client)
    st, camps = http("GET", f"{B}/campaigns/?api_key={k}")
    if st != 200:
        sys.exit(f"Smartlead error {st}: {camps}")
    emails = set()
    for c in camps:
        if any(s in c["name"].lower() for s in SKIP):
            continue
        st, txt = http("GET", f"{B}/campaigns/{c['id']}/leads-export?api_key={k}", timeout=120)  # CSV comes back as text
        if st != 200:
            sys.exit(f"Smartlead leads export failed for campaign {c['id']} '{c['name']}' ({st}). Nothing written; re-run.")
        if not isinstance(txt, str):
            continue  # empty campaign: Smartlead answers with JSON instead of CSV
        for row in csv.DictReader(io.StringIO(txt.lstrip("﻿"))):
            e = (row.get("email") or "").strip().lower()
            if e:
                emails.add(e)
    Path(d).mkdir(parents=True, exist_ok=True)
    Path(d, "already_contacted.txt").write_text("\n".join(sorted(emails)), encoding="utf-8")
    print(f"{len(emails)} emails already in {client} campaigns")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

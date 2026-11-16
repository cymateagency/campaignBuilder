"""Check that this laptop can run the pipeline. Never prints a key, only whether it was found.

  python lib/check_setup.py [client name]

Checks: Python version, AIRTABLE_TOKEN, every shared key in the Cymate row of the Clients table,
the Octave template agent OIDs in config.json, and (if a client is given) that client's Smartlead key.
"""
import sys
from common import CONFIG, tool_key, smartlead_key, octave_key, airtable_token

ok = True


def line(good, label, hint=""):
    global ok
    ok &= good
    print(f"{'OK  ' if good else 'MISS'} {label}" + (f"  -> {hint}" if hint and not good else ""))


line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "install Python 3.10 or newer")
has_token = bool(airtable_token())  # env var, or the value saved with setx on Windows
line(has_token, "AIRTABLE_TOKEN is set", 'run: setx AIRTABLE_TOKEN "pat..." then open a NEW terminal')
if not has_token:
    sys.exit(1)


def probe(label, fn, hint):
    try:
        fn()
        line(True, label)
    except SystemExit as e:
        line(False, label, f"{e} {hint}".strip())


cy = CONFIG["airtable"]["cymate_record"]
client = " ".join(sys.argv[1:]) or None
for name, field in CONFIG["airtable"]["shared_fields"].items():
    if name == "octave":
        continue  # checked below: the client's own key can stand in for it
    if not field:
        print(f"--   '{name}' not configured (optional)")
        continue
    probe(f"shared key '{name}' ({field}) in the {cy} row", lambda n=name: tool_key(n), "")
probe(f"Octave key (from {client + ' row, else ' if client else ''}{cy} row, Cymate workspace)",
      lambda: octave_key(client), "")
for fw, oid in CONFIG["octave_template_agents"].items():
    line(oid.startswith("ca_"), f"Octave agent {fw}: {oid}", "set the agent OID in config.json")
if client:
    probe(f"Smartlead key for '{client}'", lambda: smartlead_key(client), "")
print("\nReady." if ok else "\nFix the MISS lines above, then run this again.")
sys.exit(0 if ok else 1)

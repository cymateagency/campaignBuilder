"""Builder output must match what the AI Ark app produced for the same filters (captured Nov 2026)."""
import json, sys
from pathlib import Path
T = Path(__file__).parent
sys.path.insert(0, str(T.resolve().parent))  # the stage folder
import aiark_payload as ap

spec = json.loads((T / "fixtures/spec_matching_capture.json").read_text(encoding="utf-8"))
app, body, _ = ap.build(spec)
want_app = json.loads((T / "fixtures/captured_app.json").read_text(encoding="utf-8"))
want_api = json.loads((T / "fixtures/captured_api.json").read_text(encoding="utf-8"))
app.pop("latest_active_job_title_only", None)  # verified separately; not in this capture
errs = [f"app key {k}: got {app.get(k)!r} want {v!r}" for k, v in want_app.items() if app.get(k) != v]
errs += [f"app has extra key {k}" for k in app if k not in want_app]
for side in ("contact", "account"):
    if body.get(side) != want_api[side]:
        for k in set(body.get(side, {})) | set(want_api[side]):
            if body.get(side, {}).get(k) != want_api[side].get(k):
                errs.append(f"api {side}.{k}: got {json.dumps(body.get(side, {}).get(k))} want {json.dumps(want_api[side].get(k))}")

# Regressions: a max-only employee range needs a start; approve() must re-add the API-only mail filter.
rng = ap.build({"employees": {"max": 500}})[1]["account"]["employeeSize"]["range"]
if rng != [{"start": 1, "end": 500}]:
    errs.append(f"max-only employees: got {rng}")
appr = ap.approve({"contact": {}, "account": {"revenue": {}}}, {"exclude_mail_security": ["proofpoint"]})
if appr["account"].get("mail") != {"security": {"any": {"exclude": ["proofpoint"]}}} or "revenue" not in appr["account"]:
    errs.append(f"approve did not re-add the mail security exclusion: {appr}")
print("\n".join(errs) if errs else "PASS: in-app payload and API body match the AI Ark capture")
sys.exit(1 if errs else 0)

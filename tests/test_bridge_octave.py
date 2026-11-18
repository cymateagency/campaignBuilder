"""Offline test of the bridge's Octave workspace setup (stage 1): status, copying the template agents into a client's
own workspace, seeding its library as suggestions, and agent runs preferring the client's own agents.
Octave and Airtable are faked: no keys, no credits.

  python tests/test_bridge_octave.py      # prints PASS
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stages" / "3-copy" / "studio"))
_out = sys.stdout
import bridge as B  # noqa: E402  (redirects stdout to stderr for the MCP channel)
sys.stdout = _out

fails = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


OWN_WS, CY_WS = "wa_clientOwn123", B.CONFIG["octave_workspace"]
ROWS = {"Acme": ("own-key", "https://mcp.octavehq.com/mcp?ctx=own", OWN_WS), "Shared": ("cy-key", "https://mcp.octavehq.com/mcp?ctx=cy", CY_WS),
        "Empty": ("", "", None)}
B._client_octave = lambda client: ROWS[client]
B.agent_key = lambda client: ("cymate-shared-key", "shared")
B.common.tool_key = lambda name: "cymate-shared-key"

WS_AGENTS = {OWN_WS: [{"oId": "ca_own_tfkd", "name": "Cymate Template - TFKD (MEDIUM)"}, {"oId": "x", "name": "Some other agent"}]}
CALLS = []


def fake_mcp(url, key, tool, args, timeout=120):
    CALLS.append((tool, key))
    if tool == "list_agents":
        return {"agents": list(WS_AGENTS.get(OWN_WS if key == "own-key" else CY_WS, []))}
    if tool == "list_entities":
        return {"entities": [{"oId": "p1"}] if args["entityType"] == "product" else []}
    if tool == "get_agent":
        return {"data": {"name": f"Cymate Template - {args['oId']}", "updatedAt": "x",
                         "data": {"instructions": "RULES", "model": "ECHO", "jsonSchemaInstructions": "JSON", "tools": {"parallelWebSearch": {"customInstructions": "WEB"}}}}}
    if tool == "create_agent":
        assert key == "own-key" and args["instructions"] == "RULES" and args["enableBrandVoice"] is False
        WS_AGENTS[OWN_WS].append({"oId": "ca_new_" + args["name"][-12:], "name": "Cymate Template - " + B.FW_NAMES[next(fw for fw, o in B.CONFIG["octave_template_agents"].items() if args["name"].endswith(o))]})
        return {"data": {"oId": "ca_created"}}
    if tool == "create_suggestion":
        assert key == "own-key" and args["changeType"] == "add"
        return {"data": {"oId": "sg_" + args["name"]}}
    raise AssertionError(tool)


B.octave_mcp = fake_mcp

s = B.octave_setup_status({"client": "Empty"})
check(not s["airtable"]["octave_key"] and "Create the client's workspace" in s["next"], "no keys: tells the CSM to create the workspace")
s = B.octave_setup_status({"client": "Shared"})
check(s["separate_workspace"] is False and "shared Cymate workspace" in s["next"], "shared Cymate key: asks for the client's own workspace")
s = B.octave_setup_status({"client": "Acme"})
check(s["reachable"] and s["agents"]["TFKD"] == "ca_own_tfkd" and s["agents"]["POKE_THE_BEAR"] is None and s["library"]["product"] == 1,
      "own workspace: finds existing agents and library counts")
check(s["ready"] is False and "Copy the framework agents" in s["next"], "own workspace: next step is copying the agents")

try:
    B.octave_copy_agents({"client": "Shared"}); check(False, "copy into the shared workspace should be refused")
except B.ToolError as e:
    check("no workspace of its own" in str(e), "copy into the shared workspace is refused")
r = B.octave_copy_agents({"client": "Acme"})
check(set(r["created"]) == set(B.FW_NAMES) - {"TFKD"} and r["already_there"] == {"TFKD": "ca_own_tfkd"}, "copies the 4 missing agents, keeps TFKD")
check(all(k == "own-key" for t, k in CALLS if t == "create_agent") and all(k == "cymate-shared-key" for t, k in CALLS if t == "get_agent"),
      "templates are read from Cymate, created with the client's key")

oid, key, where = B.agent_for("Acme", "TFKD")
check((oid, key, where) == ("ca_own_tfkd", "own-key", "client workspace"), "agent runs use the client's own agent and key")
oid, key, where = B.agent_for("Shared", "TFKD")
check(oid == B.CONFIG["octave_template_agents"]["TFKD"] and where == "Cymate workspace", "without its own workspace: the Cymate template agent")

r = B.octave_seed_library({"client": "Acme", "entities": [{"entity_type": "product", "name": "Senior engineers", "instructions": "x"},
                                                           {"entity_type": "persona", "name": "Data leaders", "instructions": "y"}]})
check(len(r["proposed"]) == 2 and not r["failed"] and "Suggestions inbox" in r["next"], "library entities go in as suggestions")
try:
    B.octave_seed_library({"client": "Shared", "entities": [{"entity_type": "product", "name": "x", "instructions": "y"}]}); check(False, "seed should refuse")
except B.ToolError:
    check(True, "seeding the shared workspace is refused")

print("\nPASS" if not fails else f"\n{len(fails)} FAILED")
sys.exit(1 if fails else 0)

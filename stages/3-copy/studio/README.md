# Copy Studio (stage 3, visual)

A copy desk for stage 3 as a claude.ai artifact, built on the same rules, template agents and checks as the terminal flow.

- Copy Studio: https://claude.ai/artifact/KVyCUJDx1ZfaPB156dmTTX (source: `copy_studio.html`)
- Walkthrough (frameworks, agents, how it picks): https://claude.ai/artifact/44ZKNoctjuarW1ZwLdntph (source: `walkthrough/`)
- Videos: [overview](https://www.loom.com/share/b4a3b6af049f4bb0b88cf7c19836e2f1) · [deep dive](https://www.loom.com/share/5757a9d28bd8464f868614e9c45b921a)

## How it works

1. **Input:** the client name (as in Airtable) and a brief for the campaign you want to run. Nothing else.
2. **Gather:** the client's Octave workspace (company, products, personas, segments, use cases, proof; the client's own workspace when Airtable has its Octave key and MCP URL, else matching entities in the Cymate workspace), its Smartlead campaigns ranked by positive reply rate per unique lead (with the copy of the best and worst), and the onboarding form / call transcript in Airtable when present.
3. **Frameworks:** at least two variants tagged by length, a SHORT and a MEDIUM by default (LONG when the campaign needs room), one framework each, picked with the "How to pick" rules in `../reference/frameworks.md`, each with its why. Per Wesley: Octave writes the whole email in a named framework, and every campaign A/B tests lengths.
   - SHORT: 2 Sentence Pain Focus, Poke The Bear · MEDIUM: TFKD, Talking To Other Folks · LONG: Standard Go-To
4. **Brief + personalization plan:** the campaign brief in the format from `frameworks.md`, and a personalization plan (3 to 5 signals in priority order, where to find them, fact to implication to question, what doesn't count, recency, fallback).
5. **Copy:** per variant, Email 1 with 3+ subject lines and 2 follow ups, house-style checks and word limits by length (SHORT 60, MEDIUM/LONG 110), versions, rewrite with feedback, 3 options, and a chat that edits the copy.
6. **Octave agent instructions:** per variant, one paste-ready block built from that framework's live template agent in Octave (read with `agent_template`), with the brief, the filled framework lines and the personalization plan inside.
7. **Test on real leads:** runs each variant's template agent on prospects from the client's Smartlead campaigns (about 2 Octave credits per email), with the stage 3 QA from `octave_copy.py`.

Work is saved per client in the artifact's database (and the browser as a fallback).

## The bridge (`bridge.py`)

The artifact can't reach the internet or hold keys, so `bridge.py` runs on your laptop as a local MCP server. Standard library only; it reads `AIRTABLE_TOKEN` like the rest of the repo and reuses `lib/common.py` and `octave_copy.py`. No tool returns a key.

Tools: `list_clients`, `check_client`, `octave_context`, `smartlead_learnings`, `onboarding_context`, `sample_leads`, `pipeline_run`, `agent_template`, `copy_rules`, `start_agent_runs`, `get_agent_runs`. Agent runs are jobs (start, then poll), because one run can take longer than a connector call may wait.

### Setup (once per laptop)

1. The repo setup from the main README (`python lib/check_setup.py "<client>"` ends with `Ready.`).
2. Add the bridge to the Claude desktop app config (`%APPDATA%\Claude\claude_desktop_config.json` on Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), under `mcpServers`:

```json
"cymate_copy": {
  "command": "<full path to python>",
  "args": ["<full path to cymate-gtm>/stages/3-copy/studio/bridge.py"]
}
```

3. Fully quit and reopen the Claude desktop app, then open the Copy Studio link in the app. Local servers only answer there; in a browser tab you can still paste copy and iterate with Claude.

After changing `bridge.py`, quit and reopen the app so it starts the new version. To try a tool without the app, send it JSON-RPC over stdin (`initialize`, then `tools/call`).

## Changing it

- Frameworks, how to pick, house style: `../reference/frameworks.md` (the bridge serves it to the page as `copy_rules`).
- The template agents: Octave, Cymate workspace, "Cymate Template - ..." (ids in `config.json`). The page reads their live instructions.
- The page: edit `copy_studio.html`, then republish the artifact to the same link.

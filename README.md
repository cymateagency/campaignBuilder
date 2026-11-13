# Cymate GTM Pipeline (Claude Code)

From client onboarding to a draft Smartlead campaign, without Clay, in four stages that can each be run and changed on their own.

| Stage | What it does | Ask Claude |
|---|---|---|
| 1 Onboarding | Reads the onboarding form, onboarding call, PMF matrix, or a typed description; writes the client context and ICP brief; the CSM picks the group and offer | "onboard Clear-Tech" |
| 2 Lead list | Builds the AI Ark search (reviewed in the AI Ark app), pulls, cleans (dedupe, gateways, off-target), finds and verifies emails | "build the list for Clear-Tech G1" |
| 3 Copy | Picks the framework from the context, writes the brief, generates each lead's email with the Octave template agents, checks it, CSM approves 5+ examples, client approves (feedback rounds) | "write the copy for Clear-Tech" |
| 4 Campaign | Exports the approved copy for the `campaign-builder` skill (Cymate's Smartlead SOP builder, by Jairo), which builds the DRAFT with its goal subsequence and runs the SOP checklist | "build the Smartlead campaign" |

Or "build a campaign for Clear-Tech" to go through all four. Claude stops at every gate.

## Setup (once per machine)

1. Install Claude Code, clone this repo and open it: `git clone https://github.com/cymateagency/campaignBuilder.git`, then `cd campaignBuilder` and `claude`
2. Python 3.10+ (standard library only). Commands use `python`; on macOS/Linux use `python3` if `python` is missing. On Windows `python3` opens the Microsoft Store: use `python`.
3. Airtable token with `data.records:read` on the Cymate base. Every other key is read from Airtable.
   - Windows (PowerShell, once): `setx AIRTABLE_TOKEN "pat..."`, then restart the terminal and Claude Code.
   - macOS/Linux: `export AIRTABLE_TOKEN=pat...` in your shell profile.
4. Check: `python lib/check_setup.py "<a client name>"` should end with `Ready.` (it never prints keys).
5. Optional: connect the AI Ark, Octave, Airtable and Fathom MCP servers in Claude Code (catalog lookups, agent edits, call transcripts).
6. Stage 4 uses the `campaign-builder` skill from the Cymate Claude org (Node 18+ for its scripts).

Where the keys live (Airtable Clients table): each client's row has its `🗝️ Smartlead API key` and `Octave API Key`; the shared keys (AI Ark, LeadMagic, Icypeas, MillionVerifier, BounceBan, AI Ark webhook) are on the row named in `config.json` -> `airtable.cymate_record`, in the columns listed under `shared_fields`.

## Changing one stage

Everything a stage needs is in its folder: scripts, `reference/` rules, `templates/`, and its skill in `.claude/skills/cymate-<n>-<stage>/SKILL.md`.
To change the copy, edit `stages/3-copy/` and its skill only. `lib/common.py` is shared by all stages.
After any change: `python tests/test_offline.py` (simulates every stage with fake APIs, no keys, no credits) should print `ALL PASS`.

## Layout

```
CLAUDE.md                       rules Claude always follows
config.json                     Airtable fields, Octave agent ids, gateways (no secrets)
lib/                            common.py (HTTP, Airtable keys, run state, signature), check_setup.py
stages/1-onboarding/            client context template
stages/2-lead-list/             AI Ark payload + pull, Smartlead export, clean, email waterfall, tests
stages/3-copy/                  octave_copy.py, approvals.py, frameworks reference
stages/4-campaign/              export_for_builder.py (inputs for the campaign-builder skill)
.claude/skills/                 one skill per stage + campaign-pipeline (all stages)
tests/test_offline.py           whole-pipeline simulation
runs/                           per-campaign working files (git-ignored: contacts and copy stay local)
```

## Working on it together (GitHub)

`runs/`, `.cache/` and any `.env` are git-ignored, so no contact data or keys go to GitHub.
Pull before you start (`git pull`), commit small changes per stage with a message that names the stage (`copy: ...`), push, and run the offline test before pushing.

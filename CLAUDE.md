# Cymate GTM Pipeline

Takes a Cymate client from onboarding to a draft Smartlead campaign without Clay, in four stages.
Each stage has its own skill and folder, so one stage can be run or changed without touching the others.

## The stages

| # | Stage | Skill | Folder | Gate |
|---|---|---|---|---|
| 1 | Onboarding: onboarding form, call, PMF matrix or typed context -> `client_context.md`, `icp_brief.md` | `cymate-1-onboarding` | `stages/1-onboarding` | **CSM picks group + offer** |
| 2 | Lead list: AI Ark search reviewed in the app, pull, clean, email waterfall -> `verified.jsonl` | `cymate-2-lead-list` | `stages/2-lead-list` | **CSM approves the search and pull size** |
| 3 | Copy: framework from context, brief, Octave agents, QA, approvals -> `copy.jsonl` | `cymate-3-copy` | `stages/3-copy` | **CSM approves 5+ examples, then the client approves** |
| 4 | Campaign: Smartlead DRAFT with the Cymate signature | `cymate-4-campaign` | `stages/4-campaign` | **CSM starts it** |

`campaign-pipeline` runs them in order. Stages hand off through files in `runs/<client>/<campaign>/`; `state.json` records stages, approvals and spend. Resume from the first stage not done.
Shared helpers (HTTP, Airtable keys, run state, signature) are in `lib/common.py`. A change inside one stage folder doesn't affect the others; a change in `lib/` affects all.

## Keys

No key is ever written into this repo, a chat, or a run folder.
The only local secret is `AIRTABLE_TOKEN` (env var, or saved with `setx` on Windows). `lib/common.py` reads every other key from the Airtable Clients table, matching the `👨‍💻 Business` column exactly:
- Per client (the client's row): Smartlead API key, and its Octave API key, which runs the template agents. The script checks the key's workspace through the row's `Octave MCP URL` and refuses one from a workspace without the agents.
- Shared (the row named in `config.json` -> `airtable.cymate_record`, currently `Juan-Test` while testing; the `Cymate` row is kept for internal campaigns): AI Ark key and webhook URL, LeadMagic, Icypeas, MillionVerifier, BounceBan, and an Octave API key used when a client's row has none. Which Airtable column holds each is in `config.json` -> `shared_fields`.

## Source of truth for copy

The campaign brief Claude writes with the CSM (from the onboarding inputs and what the CSM approves) is the only source of truth about a client. The Cymate Octave workspace holds many clients' entities; the template agents are told to ignore all of them and use only the brief. Never attach Octave library entities, motions or playbooks to the template agents.

## Rules that always apply

- Lead lists: `stages/2-lead-list/reference/lead_rules.md`. AI Ark payload keys: `stages/2-lead-list/reference/aiark_payload_map.md`.
- Copy: `stages/3-copy/reference/frameworks.md` (frameworks, how to pick, house style, agent lessons).
- Smartlead: `stages/4-campaign/reference/smartlead_defaults.md`. Check the client's live campaigns before changing settings or writing copy.
- Copy is only written for contacts that passed the ICP check and email verification.
- Every paid step states its cost before it runs and reports what it spent after.
- No copy reaches Smartlead before the CSM approved 5+ examples and the client approved them.
- Never start a campaign. Builds end as DRAFT; the CSM starts it.
- Keep replies short. Deliver one complete file per request, never partial files.
- Run `python tests/test_offline.py` (no keys, no credits) after changing any script.

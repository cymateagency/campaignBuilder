---
name: cymate-4-campaign
description: Stage 4 of the Cymate campaign pipeline. Build the Smartlead campaign as a DRAFT from the approved copy, copying settings, schedule and mailboxes from one of the client's live campaigns, with the Cymate signature, then read it back. Use for "build the campaign", "drop the campaign in Smartlead", or after the client approved the copy in stage 3.
---

# Stage 4: Campaign (Smartlead draft)

Read `CLAUDE.md` and `stages/4-campaign/reference/smartlead_defaults.md`. Run commands with `python` from the repo root. `R` is the run folder.

**In:** `copy.jsonl` and `campaign_spec.json` from stage 3, with the client's approval recorded in `state.json`.
**Out:** a DRAFT Smartlead campaign, `campaign_id` and `upload.csv` in the run folder.

1. Find a live campaign of the client to copy settings from (ask the CSM for its id).
2. `python stages/4-campaign/smartlead_build.py "<client>" R --reference <id> --dry-run`: checks the signature and writes `upload.csv`.
3. `python stages/4-campaign/smartlead_build.py "<client>" R --reference <id>`: settings, schedule and mailboxes from the reference, Email 1 from each lead's custom fields, the signature on Email 1 and every follow up, leads 100 at a time, left as DRAFT. Refuses to run before the client approved the copy, and refuses a second build for the same run unless `--new`. `--no-mailboxes` only for internal tests (the draft can't send).
4. Read the campaign back (status, settings, schedule, sequences, lead count, one lead's custom fields) and report.

Signature (same as the live client campaigns): `{Appreciate it|Best regards|Thanks},` / sender first name / title / website written with a one dot leader (․) so it isn't a link.

**Gate: the CSM starts the campaign in Smartlead.** Never start it.

---
name: cymate-2-lead-list
description: Stage 2 of the Cymate campaign pipeline. Build the AI Ark search for one group, let the CSM review it in the AI Ark app, pull it, clean it (dedupe vs the client's Smartlead campaigns, gateways, off-target titles and industries) and find and verify missing emails. Use for "build the list for <client>", "pull leads", "verify the list", or after stage 1.
---

# Stage 2: Lead list

Read `CLAUDE.md`, `stages/2-lead-list/reference/lead_rules.md` and `stages/2-lead-list/reference/aiark_payload_map.md`. Run commands with `python` from the repo root.

**In:** `icp_brief.md` from stage 1, or the CSM typing the group (industries, size, titles, region, exclusions).
**Out:** `verified.jsonl` (deliverable leads, each tagged with `segment`), `held.jsonl` (gateway contacts), spend in `state.json`.
All scripts are in `stages/2-lead-list/`. `R` below is the run folder.

## 1. Build and review the search
1. Resolve every value from AI Ark's catalogs (`industry_search`, `location_search`, `technology_search`). Never ask the CSM to type values.
2. Write `R/list_spec.json` (see `stages/2-lead-list/templates/list_spec.example.json`) with `"segment"` set to the group name. One group per run folder.
   Exclude noise titles in the search itself (for example "Investment" when the ICP has CIO), not only at cleaning.
3. `python stages/2-lead-list/aiark_payload.py build R/list_spec.json R` then `python stages/2-lead-list/aiark_pull.py count R` (free).
4. Give the CSM the one-line `inapp_payload.json`, the count, the cost (~1 credit per contact) and the paste steps (People Search > Search Payload > In-App Payload > Apply Search).
5. If they change filters they paste back the API Payload: save as `R/approved_payload.txt`, run `aiark_payload.py approve R/approved_payload.txt R` (re-adds the mail-security exclusion).
**Gate: the CSM approves the list and the number of contacts to pull.** Yield is ~35 to 45% after cleaning and verification, so pull ~2.5x the leads needed.

## 2. Pull
`python stages/2-lead-list/aiark_pull.py export R --max N`. AI Ark requires a webhook URL (Airtable, see `config.json`); the script polls and downloads itself. Running `export` again resumes instead of paying twice.

## 3. Clean
`python stages/2-lead-list/smartlead_export.py "<client>" R` then
`python stages/2-lead-list/clean.py R --title-must "<ICP title words>" --title-not "<noise>" --industry-not "<competitors and off-ICP industries>"`.
Report the drop table and list the kept companies so the CSM can spot vendors that slipped through.

## 4. Email waterfall
State the max cost first, then `python stages/2-lead-list/email_waterfall.py R`: LeadMagic then Icypeas for missing emails, MillionVerifier then BounceBan to verify. If the CSM skips it, keep only AI Ark VALID emails in `verified.jsonl`.
Report deliverable leads by source and spend. Hand off to stage 3 (`cymate-3-copy`).

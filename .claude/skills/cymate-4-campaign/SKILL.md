---
name: cymate-4-campaign
description: Stage 4 of the Cymate campaign pipeline. Turn the client-approved copy from stage 3 into the inputs of the campaign-builder skill (Jairo's, the Cymate Smartlead SOP builder) and build the campaign as a DRAFT with its goal subsequence. Use for "build the campaign", "drop the campaign in Smartlead", or after the client approved the copy in stage 3.
---

# Stage 4: Campaign (Smartlead draft via campaign-builder)

The Smartlead build is done by the **`campaign-builder`** skill (Cymate org skill, maintained by Jairo): SOP settings, the goal subsequence the reply agent needs, the SOP checklist, resume after errors, handoff. This stage only prepares its inputs, so the SOP lives in one place.
Run commands with `python` from the repo root. `R` is the run folder.

**In:** `copy.jsonl` and `campaign_spec.json` from stage 3, with the client's approval recorded in `state.json`.
**Out:** `R/builder/spec.json` + `R/builder/leads.csv`, then a DRAFT campaign and subsequence built by campaign-builder.

1. Make sure `R/campaign_spec.json` has:
   - `"type"`: the client's reply-agent type (`ColdOutreach`, `Podcast`, `Signups`, `Form`, `Partnership`, `Webinar`, `Referral`); ask the CSM, it must match the reply-agent config.
   - `"name"`: `<type>_<segment>_<titles>_<size>_<geo>_<source>_<month>`, e.g. `ColdOutreach_banks_dataleaders_200-2000_us_aiark_nov`. Suggest one, the CSM confirms.
   - `"signature"` with the sender's real title (ask the CSM; never invent it).
2. Find, in the client's Smartlead (or ask the CSM): a live campaign whose mailboxes to reuse, and the client's existing goal subsequence (`<type>_Subsequence`, newest one with that prefix).
3. Export:
   `python stages/4-campaign/export_for_builder.py R --mailboxes-from <campaign_id> --subsequence-from <subsequence_id> --source <list tag, e.g. aiark_us_net_new>`
   Optional: `--mailbox-ids 1,2,3` instead of `--mailboxes-from`, `--start-date YYYY-MM-DD` (default next business day), `--max-per-day` (SOP minimum 444). It refuses before the client approved the current copy.
   Email 1 is `{{Email_Copy}}` (each lead's approved email) + the signature + `{{PS}}` when the framework writes one; the subject is `{{Email_Subject}}`; follow ups get the same signature.
4. Run the **campaign-builder** skill with `DIR = R/builder` (the spec and CSV are already written: skip its input collection and spec writing, start at its "Get the client's Smartlead key" step): validate, dry run and show the plan, build after the CSM's OK, hand off the manual steps.

**Gate: the CSM starts the campaign** after the handoff checklist. Never start it unless they say so after seeing the handoff.

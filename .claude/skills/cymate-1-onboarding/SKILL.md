---
name: cymate-1-onboarding
description: Stage 1 of the Cymate campaign pipeline. Turn whatever the CSM has about a client (onboarding form, onboarding call transcript, PMF matrix, or a typed description for clients without a matrix) into client_context.md and an ICP brief, and get the CSM to pick the group and offer to run. Use for "onboard <client>", "new campaign for <client>", "here is the onboarding form / call / PMF matrix".
---

# Stage 1: Onboarding (client context and ICP)

Read `CLAUDE.md` first. Run commands with `python` from the repo root. Keep chat replies short.

**In:** any mix of the onboarding form (PDF/doc), the onboarding call (Fathom link or transcript), the PMF matrix, or the CSM typing the context. None is required on its own: a lower tier client may only have a typed description.
**Out (in `runs/<client>/<campaign>/`):** `client_context.md`, `icp_brief.md`, `state.json` with the chosen group and offer.

## Steps

1. Ask for the Airtable client name (must equal the `👨‍💻 Business` column) and a short campaign name. Create `runs/<client>/<campaign>/` (lowercase, spaces to dashes).
2. Read every input given. For a Fathom call use the Fathom tools (transcript, not memory).
3. Write `client_context.md` with sources at the top and these sections, using only what the inputs say:
   company (what it is, one line), offers (one block per product/offer: problem, alternative, the way, loss, result, proof, terms), buyers (titles, seniority, who feels it, who decides), industries in and out, regions, size and revenue, signals, proof and approved customer names, things not approved yet (for example a case study "once approved"), competitors, risk reduction, sales process, calendar link.
   Mark anything inferred as `(inferred)` and list open questions at the end.
4. Write `icp_brief.md`: one table column per group (industry, size, titles, seniority, signal, region, offer that opens it), exclusions for every group, the offer details, and a recommendation of which group + offer to run first with one line why. Say plainly which signals AI Ark can't filter on.
5. Record in `state.json`: `{"client": ..., "campaign": ..., "stages": {"onboarding": {"done": true, "group": ..., "offer": ...}}}` once the CSM picks.

**Gate: the CSM picks the group and offer.** Then hand off to stage 2 (`cymate-2-lead-list`).

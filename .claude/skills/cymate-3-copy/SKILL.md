---
name: cymate-3-copy
description: Stage 3 of the Cymate campaign pipeline. Pick the framework from the client context, write the campaign brief, generate Email 1 per lead with the Octave template agents, run the free QA checks, get the CSM's approval on 5+ examples, send them to the client and loop on feedback until the client approves. Use for "write the copy for <client>", "test the copy", "the client sent feedback", "client approved the copy", or after stage 2.
---

# Stage 3: Copy

Read `CLAUDE.md` and `stages/3-copy/reference/frameworks.md`. Run commands with `python` from the repo root. `R` is the run folder.

**In:** `verified.jsonl` (stage 2) and the client context (`client_context.md` / `icp_brief.md` from stage 1, or what the CSM types).
**Out:** `campaign_spec.json`, `copy_test.md` (CSM review), `client_review.md` (for the client), `copy.jsonl` (every lead's email), approvals in `state.json`.

## 1. Framework and brief
1. Pick ONE framework with the "How to pick" rules from the group, offer and signal. One line why, saved as `framework_choice`. The PMF matrix tests groups x offers, not frameworks.
2. Write the brief (format in frameworks.md). It is the only source of truth about the client: approved facts only, pain written as common for the role (never as a fact about the reader), exact company spelling, banned topics (unapproved case studies, prices, other timelines).
3. Write `R/campaign_spec.json` (see `stages/3-copy/templates/campaign_spec.example.json`): brief, the one slot with framework and real fallback copy (`{first_name}` allowed), `signature` (closers, the sender's title, the client website), follow ups without a sign-off (stage 4 adds the signature), the reply-agent `type` and the SOP campaign `name` (`<type>_<segment>_<titles>_<size>_<geo>_<source>_<month>`).
   Ask the CSM for the sender title if you don't have it. Never invent it.

## 2. Test and CSM review
`python stages/3-copy/octave_copy.py R --client "<client>" --test 8` (minimum 5). ~2 Octave credits per email; emails run in parallel.
Read every email in `copy_test.md` yourself first: open the sources, check right company, fits the segment, recent, house style. The script already fixes greetings and the "1 to 2 weeks" claim, sends the fallback when the fact is about another company, and flags style problems.
Fix the agent (Octave `update_agent`, full instructions) only for framework problems, the brief for client problems, then re-test (`--fresh` after an agent change).
**Gate: the CSM approves.** `python stages/3-copy/approvals.py csm-approve R --note "..."`

## 3. Client review loop
1. `python stages/3-copy/approvals.py client-review R` writes `client_review.md` (examples with signature and follow ups, no internal notes). The CSM sends it.
2. Client feedback: `approvals.py client-feedback R "<what they said>"`. Change the brief or fallbacks, re-test, `csm-approve`, `client-review` again. Every change to `campaign_spec.json` starts a new round.
3. **Gate: the client approves.** `approvals.py client-approve R --note "..."`

## 4. Full run
`python stages/3-copy/octave_copy.py R --client "<client>"`: writes the remaining leads and reuses the approved test emails for free. It refuses to run before the client approved the current version (`--skip-client-approval` only for internal tests).
Report agent vs fallback counts and Octave credits. Hand off to stage 4 (`cymate-4-campaign`).

---
name: campaign-pipeline
description: Run the whole Cymate campaign pipeline end to end, stage by stage, or resume one. Onboarding, lead list, copy (with CSM and client approval), Smartlead draft. Use for "build a campaign for <client>" or "continue the <client> campaign". For one stage only, use cymate-1-onboarding, cymate-2-lead-list, cymate-3-copy or cymate-4-campaign.
---

# Campaign pipeline (all stages)

The pipeline is four stages. Each has its own skill, folder and gates, so any one can be run or changed alone:

| Stage | Skill | Folder | Gate |
|---|---|---|---|
| 1 Onboarding | `cymate-1-onboarding` | `stages/1-onboarding` | CSM picks group + offer |
| 2 Lead list | `cymate-2-lead-list` | `stages/2-lead-list` | CSM approves the search and pull size |
| 3 Copy | `cymate-3-copy` | `stages/3-copy` | CSM approves 5+ examples, then the client approves (feedback rounds) |
| 4 Campaign | `cymate-4-campaign` | `stages/4-campaign` | CSM starts the draft in Smartlead |

Run them in order. On "continue", read `runs/<client>/<campaign>/state.json` and resume at the first stage not done
(`stages.onboarding`, `count`/`export`/`clean`/`waterfall`, `copy_approval` + `copy`, `build`). For copy approvals: `python stages/3-copy/approvals.py status R`.

Finish with one short summary: list size and drop table, emails by source, framework, approvals, campaign name and id, spend per tool from `state.json`.

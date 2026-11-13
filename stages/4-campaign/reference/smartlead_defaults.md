# Smartlead setup

The Smartlead SOP (settings, schedule, 31 min between emails, 444+ new leads a day, 30/70 follow ups, 4% bounce pause,
AI categories, goal subsequence, campaign name prefix, checklist and handoff) lives in the **campaign-builder** skill
(`scripts/lib/config.mjs` and `references/process-context.md` in that skill). This repo doesn't repeat it, so it can't drift.

What this repo adds before the builder:

- Email 1 per lead from stage 3 (`{{Email_Copy}}`, `{{Email_Subject}}`, optional `{{PS}}`), approved by the CSM and the client.
- Signature (as in the live client campaigns, set in `campaign_spec.json` -> `signature`): `{Appreciate it|Best regards|Thanks},` /
  `%sender-firstname%` / the sender's title / the client website written with a one dot leader (`clear-tech․com`, U+2024) so it
  is not a link. Added to Email 1 and every follow up.
- `stages/4-campaign/export_for_builder.py` writes the builder's `spec.json` (inline mode) and `leads.csv`.

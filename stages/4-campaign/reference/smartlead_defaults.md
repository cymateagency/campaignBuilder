# Smartlead defaults

Always copy settings from a live campaign of the same client (`smartlead_build.py --reference <id>`) instead of these notes. These are what Cymate campaigns used in Nov 2026, for checking:

- Name: `Meeting_<Angle>` (or `Conference_<Event>`).
- Plain text, forced plain text, no open or click tracking, no unsubscribe tag.
- Stop on reply. Follow-up percentage 30. AI ESP matching on.
- Bounce auto-pause at 4%.
- Out of office: auto-categorize on, auto-reactivate off (Smartlead refuses both on).
- AI categories: Interested, Not Interested, Out Of Office.
- Schedule: Mon to Fri, client's time zone, jittered start (e.g. 08:26), min 20 to 31 min between emails.
- New leads per day: size so the list lasts the campaign window (about 300/day on 60 mailboxes).
- Mailboxes: the same set the client's live campaigns use.
- Email 1 A/B: one variant per framework slot, each reading the lead's `{{subject_<slot>}}` and `{{email_<slot>}}` custom fields, then the sign-off. `smartlead_build.py` uploads `email_<slot>` as HTML (`<div>` per line, `<br>` between paragraphs) so line breaks survive. Check one lead's preview in Smartlead on the first build.
- Signature (as in the live client campaigns, set in `campaign_spec.json` -> `signature`): `{Appreciate it|Best regards|Thanks},` / `%sender-firstname%` / the sender's title / the client website written with a one dot leader (`clear-tech․com`, U+2024) so it is not a link. `smartlead_build.py` adds it to Email 1 and every follow up.
- Spintax: never three braces in a row. Put a variable branch first: `{triage at {{company_name}}|...}`.
- Upload leads 100 per request with `ignore_duplicate_leads_in_other_campaign: false`. Builds end as DRAFT.
- API endpoints used: `/campaigns/create`, `/campaigns/{id}/sequences` (variants in `seq_variants`, verify on first build), `/settings`, `/schedule`, `/email-accounts`, `/leads`, `/leads-export`, `/analytics`.

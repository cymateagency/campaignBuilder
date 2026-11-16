# Lead list rules

- Job titles always use Word Match (Jairo's rule). Exclude noise titles: assistant, intern, coordinator, analyst (unless the ICP is analysts), recruiter, sales, marketing, consultant, advisor, student, retired, former, plus anything the sample shows.
- Don't trust company keywords alone. Review results and exclude unrelated industries (advertising, consulting, publishing...). Check the first 10 pages of results, exclude the noisy industries, then accept the rest. No list is 100% perfect.
- Searches in the same industry reuse the same industry exclusion list.
- Outreach is in English. "Global" means APAC, EMEA, The Americas and ANZ. "The Americas" means North, Central and South America.
- Revenue default: $25M+ (preset buckets so the app and API counts match).
- Multi-thread: several people per company is fine. Don't cap to one contact per account.
- Hold contacts behind Proofpoint, Mimecast and Cisco IronPort gateways in a separate file. They filter cold email silently: no bounce, no reply.
- Remove anyone already in any of the client's Smartlead campaigns (except subsequence and no-show campaigns). `clean.py` checks emails AI Ark returned; `email_waterfall.py` checks emails it finds, before paying to verify them.
- Yield planning: about 35 to 45% of an AI Ark pull ends up usable before the email waterfall. Pull about 2.5x the leads you need.
- Copy is only written for contacts that passed the ICP check and email verification.
- AI Ark credits: export costs about 1 credit per matched contact. Always show the count and cost and get the CSM's yes first.

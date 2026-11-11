# Copy frameworks (v2)

Source docs: [v2 map](https://docs.google.com/document/d/1rfZSWsJn7yI4NMupawxFA4WxQEUEzWH2MSDP2cP70UU/edit) · [v1 with Jairo's comments](https://docs.google.com/document/d/1DNZEYQpjiOJSAUNHOHvFC89sz5vfV4dKcj1RXHrTbHc/edit) · [FGC Email Template Mixtape](https://app.notion.com/p/cymateclients/FGC-Email-Template-Mixtape-17877b9c0a628352a14c818bf63e49cf) · [Intent Signals SOP](https://docs.google.com/document/d/1uerKILLzpamKLYHpdo_MnFGfw3piHI8sXSJ3I26hVq4/edit)

Each campaign uses **one** framework, picked from the context (the group, the offer and the signal) with the rules below. The PMF matrix tests groups x offers; the email structure is not a test variable. Every lead in the campaign gets that framework, so `campaign_spec.json` has a single slot.
The slot labels (LONG, MEDIUM, SHORT, SHORT_B) only describe a framework's length. A multi-slot spec still works if a test of frameworks is ever wanted, but each lead then pays for one email per slot.

## How to pick

1. Signal campaign: the matching signal copy. Number plus $ value: add Trigger > Quick Pitch > Calculation.
2. Local business owner: Local Business.
3. Buyer unaware of the problem: TFKD (MEDIUM), Poke The Bear (SHORT_B).
4. Same pain across a niche: Talking To Other Folks (MEDIUM), 2 Sentence Pain Focus or 2 Step (SHORT).
5. C-level: Short w/ Impact, PWJ, Feedback Only opt 2.
6. Uses a competitor: Feedback Only opt 1.
7. Client has an asset: Lead Magnet.
8. Strong same-niche case study: Pain Point + Case Study.
9. Default: TFKD, with Standard Go-To as the LONG.

Default with no signal and no same-niche case study: TFKD.

## Cymate frameworks

- **TFKD** (Think, Feel, Know, Do) | MEDIUM | default
  `Hey {{first_name}}, since you're {{personalization}}, I'm curious if {{poke-the-bear question}}?` / `This is difficult because {{pain point}}.` / `We help {{offer/claim}} using our {{unique mechanism}}, {{risk reduction}}.` / `{{soft CTA}}`
- **Talking To Other Folks** | MEDIUM | same pain across a niche plus a case study
- **2 Sentence Pain Focus** | SHORT | get a reply before pitching. No claim, no CTA.
- Soft CTAs: "Open to learning more?" / "Mind if I send over more info?" / "If we could do the same for you, would that be worth exploring?"
- Signal copy (SOP): Hiring (LONG, one role, tie to pain, offer + case study) · Job Changes (MEDIUM, lead with the move and what they inherit, never congratulate) · Funding (MEDIUM, state the round, what it lets them do now, proof from a similar stage, never "now that you have budget") · Ad Library (LONG, reference the activity, marketing/growth offers only).

## Mixtape templates (kept, cleaned to house style)

Local Business (MEDIUM) · Trigger > Quick Pitch > Calculation > CTA (MEDIUM) · Trigger > Agitation > Social Proof > CTA (MEDIUM) · Ask Before Pitch (SHORT_B) · Pain Point + Case Study (MEDIUM) · 2 Step (SHORT) · Poke The Bear (SHORT_B) · Short w/ Impact (SHORT, CTA: "Hey {{first_name}}, curious if you're open to new ideas on [topic]? [case study, impact, KPI]. Open to learning more?") · PWJ Pattern Interrupt (SHORT) · Selling Software to Sales (MEDIUM) · Insight Validation (MEDIUM) · Feedback Only opt 1 (SHORT_B) · Feedback Only opt 2 (SHORT_B) · Lead Magnet (MEDIUM) · Standard Go-To Sequence (LONG) · Neutral Insight (follow-up only) · Bullets + Referral (follow-up only). The MEME follow-up is removed (images break plain text).

## House style (every agent follows it)

Plain text. No hyphens or dashes (open question: TFKD and Talking To Other Folks as sent open with a dash after the name; until Jairo answers, use a comma). No intensifiers. Lowercase subject lines. No tracked URLs, no calendar links in Email 1. Reply-for-link CTA. Conversational, below 6th-grade reading level. No compliment-forward openers, no bump-style follow-ups. Email 1 says plainly what the client company is and the outcome for the reader. Under 110 words.

## Template agents (Octave)

One CONTENT agent per framework, built once (Nov 2026) in the **Cymate** Octave workspace and reused for every client. Agent OIDs live in `config.json`. Nobody copies or edits them per client.

| Framework key | Octave agent | Slot | OID |
|---|---|---|---|
| `STANDARD_GO_TO` | Cymate Template - Standard Go-To (LONG) | LONG | `ca_VahcGJxKyAEZQ37RjwHkl` |
| `TFKD` | Cymate Template - TFKD (MEDIUM) | MEDIUM | `ca_gdXH5Mfu6Lk8Fwhqg5Dcb` |
| `TALKING_TO_OTHER_FOLKS` | Cymate Template - Talking To Other Folks (MEDIUM) | MEDIUM | `ca_z3bfT8kesDMJ3G5wG9FaK` |
| `TWO_SENTENCE_PAIN` | Cymate Template - 2 Sentence Pain Focus (SHORT) | SHORT | `ca_2dw0tziNgfowvykuLgUVX` |
| `POKE_THE_BEAR` | Cymate Template - Poke The Bear (SHORT_B) | SHORT_B | `ca_8vCSaYuWQSZj5WSX9gbC1` |

Lessons from the first Clear-Tech test (Nov 2026), now in the TFKD agent and to copy into the others when they are used: start the body with the literal `Hey {{first_name}},` and never write a person's name (agents picked up names from their research); never state the prospect has the pain unless the fact shows it; the company must be the one at the lead's domain (a same-name company abroad was used); the fact must match the segment's facts that count; every sentence under 25 words. `octave_copy.py` also rewrites the greeting to the lead's real first name and runs free QA checks (see its docstring).

Every agent has the same hard "SOURCE OF TRUTH" rules: the brief in the runtime context is the only source about the client; ignore every library entity in the workspace; never invent offers, numbers, customers or timeframes; with no `CLIENT:` line, return an empty body; research only the prospect's company. Brand voice and CRM tools are off. Don't attach products, personas, motions or playbooks to these agents.
Standard Go-To also returns a `ps` (the P.S. analogy), which `smartlead_build.py` places after the sign-off.

- **The agent holds what never changes:** the framework structure and soft CTAs, house style, the JSON output contract, the quality rules (true fact, right company, fits the segment, recent), and "use only the campaign brief, ignore the Octave library" (the workspace holds other clients' entities).
- **The campaign brief holds the client.** Claude writes it once per campaign with the CSM, from the onboarding form, the PMF matrix and anything the CSM approves (the client's Octave library only as optional reference, read through their `Octave MCP URL`), and `octave_copy.py` passes it as runtime context on every run, plus `Segment: <value>`.
- Settings: model ECHO (~2 credits a run), web search on with custom instructions (services pages, news, partner pages, LinkedIn, last 12 months), output JSON.
- Output contract: `{"subject": "...", "body": "...", "ps": "...", "confidence": "high"|"low", "fact_used": "...", "source_url": "..."}` (`ps` is empty except for Standard Go-To). `fact_used` starts with the company name. Low confidence uses the slot's fallback copy.

### Campaign brief format

```
CLIENT: <name> - <one line on what the company is>
OFFER: <the one offer>
OUTCOME FOR THE READER: <...>
UNIQUE MECHANISM: <...>
RISK REDUCTION: <...>
PROOF: <case studies and numbers the client approved>
PAIN POINTS: <per persona>
BANNED WORDS AND TOPICS: <...>
SEGMENTS:
- <segment>: what these companies do, which facts count, the question to ask
SOFT CTA: <one of the soft CTAs>
SUBJECT LINES: <2-4 lowercase options>
```

### Base agent instructions: TFKD (first one to build)

```
CONTEXT
You write one cold email (Email 1) in the TFKD framework for a Cymate client.
Everything about the client is in the runtime context under CLIENT, OFFER, PROOF, SEGMENTS and the rest of the campaign brief. Use only that brief.
Ignore any library entities, personas, products or proof points that are not in the brief: they belong to other clients.
The runtime context ends with "Segment: <name>". Use that segment's rules.

FRAMEWORK
Line 1: Hey {first name}, since you're <one concrete, recent fact about their company that fits the segment>, I'm curious if <poke-the-bear question tied to the segment's pain>?
Line 2: This is difficult because <the pain point, in the reader's words>.
Line 3: <Client> helps <offer/outcome> using <unique mechanism>, <risk reduction>.
Line 4: <the soft CTA from the brief>.

RESEARCH
Search the company's own site (services, news, partners), recent press and LinkedIn from the last 12 months.
Confirm the company by domain before using any fact. Use a concrete fact with a source URL, never a generic one.

STYLE
Plain text, under 110 words, below 6th-grade reading level. No hyphens or dashes, no intensifiers, no compliments, no hype.
Say plainly what the client is and the outcome for the reader. Never use a banned word or topic from the brief.

CONFIDENCE
high: a concrete fact from the last 12 months, with a source URL, about the right company, that fits the segment.
low: anything else. Still write the email, but mark it low.

OUTPUT (JSON only)
{"subject": "<one subject from the brief, lowercase>", "body": "<the email>", "confidence": "high|low",
 "fact_used": "<company name>: <fact>", "source_url": "<url>"}
```

Build the other framework agents from the same five sections, changing only FRAMEWORK and its examples. Test each one on 5 to 10 real leads per segment and add a rule for every failure (see the `cymate-3-copy` skill).

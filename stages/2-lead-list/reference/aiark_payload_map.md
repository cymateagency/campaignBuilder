# AI Ark payload map

`stages/2-lead-list/aiark_payload.py` builds both payloads from one list spec. `tests/test_payload.py` checks the builder against a real capture from the app (Nov 2026).

## The review loop

1. Build the spec, run `aiark_payload.py build`, run `aiark_pull.py count`.
2. Give the CSM `inapp_payload.json`. In AI Ark: People Search > add any filter > **Search Payload** > **In-App Payload** tab > paste > **Apply Search**. The total should match our count, apart from the API-only filters listed below.
3. The CSM reviews the contacts. If they change filters, they open Search Payload > **API Payload** tab > Copy, and paste it back.
4. Run `aiark_payload.py approve <their_payload.txt> <run_dir>`. That approved API payload is what we pull. `approve` re-adds the mail-security exclusion (API only) from the run's `list_spec.json`, which `build` saves there.

## Keys

| Filter | Spec key | In-app key | API body | Status |
|---|---|---|---|---|
| Titles include / exclude | `titles.include/exclude` | `include_latest_title`, `exclude_latest_title` | `contact.experience.latest.title.any.{include,exclude}` `{mode, content}` | verified |
| Title must contain all | `titles.all` | `all_latest_title` | `contact.experience.latest.title.all.include` | verified |
| Title match type (Word Match rule) | `titles.match` | `exact_match: {include_latest_title: "WORD", ...}` | `mode: "WORD"` | verified |
| Not only primary role | (always) | `latest_active_job_title_only: false` | n/a | verified (skill test) |
| Seniority | `seniority.include` | `include_seniority` (UPPERCASE) | `contact.seniority.any.include` | verified |
| Seniority exclude | `seniority.exclude` | `exclude_seniority` | `contact.seniority.any.exclude` | UNVERIFIED |
| Department / function | `department.include` | `include_department_and_function` | `contact.departmentAndFunction.any.include` | verified |
| Time in role | `time_in_role.{min_years,max_years}` | `time_in_current_job_role: {from:{years}, to:{years}}` | `contact.experience.current.duration.currentJob.{min,max}: {year, month}` | min verified, max UNVERIFIED |
| Time at company | `time_in_company` | `time_in_current_company` | `...duration.currentCompany` | min verified |
| Total experience | `total_experience` | `time_in_work_experience` | `...duration.total` | min verified |
| Skills | `skills` | `include_skills`, `exclude_skills`, `exact_match.include_skills` | `contact.skill.any` (include WORD, exclude SMART) | verified |
| Person location | `person_location` | `location_include` / `location_exclude`: `{continent, country, state}` | `contact.location.any`: `"North America United States Texas"` | verified |
| Company HQ | `hq_location` | `location_include_account` / `location_exclude_account` | `account.location.any` | verified |
| Employees (presets) | `employees.presets` | `employee_size_predefined` | `account.employeeSize {type: RANGE, range}` | verified |
| Employees (custom) | `employees.min/max` | `employee_size_custom: {min, max}` | `account.employeeSize` | verified (skill test) |
| Revenue | `revenue: "25M+"` or `{presets}` | `annual_revenue_predefined` | `account.revenue {type: RANGE, range}` | labels to $100M-$500M verified; higher UNVERIFIED |
| Industry | `industry` | `include_industry`, `exclude_industry` (Title Case) | `account.industries.any` mode SMART | verified |
| Company type | `company_type` | `company_type_include_any`, `company_type_exclude` | `account.type.any` | verified |
| Technologies | `technologies` | `include_technologies`, `exclude_technologies` | `account.technologies.any` mode SMART | verified |
| Products and services | `products_and_services` | `include_/exclude_products_and_services` | `account.productAndServices.any` mode WORD | verified |
| NAICS | `naics` | `naics_include_any`, `naics_exclude_any` | `account.naics.any` | verified |
| Funding | `funding` | `funding_type` | `account.funding.type` | verified |
| Company keywords | `company_keywords` | `companies_include_keywords` + `companies_include_keywords_sources_search_match` | `account.keyword.any.include` mode WORD | app verified, API UNVERIFIED |
| Mail gateway | `exclude_mail_security` | none (no app filter) | `account.mail.security.any.exclude` | API only, shape UNVERIFIED |

Also seen in the app (not in the builder yet): `include/exclude_current_company` and `include/exclude_person_id` (`{name, id}`), `include/exclude_education_school` (`{name, id, type}`), `include/exclude_languages_for_contact`, `employee_by_department_*`, `number_of_retail_locations`.

## Value catalogs

Values come from AI Ark, not from the CSM: industries (`industry_search`, 921 entries; the app uses Title Case), locations (`location_search`), technologies (`technology_search`). Seniority, department, company type, funding and mail security are fixed enums.

Employee presets: 1-10, 11-20, 21-50, 51-100, 101-200, 201-500, 501-1000, 1001-2000, 2001-5000, 5001-10000, 10001+.
Revenue: team default **$25M+** = $25M-$50M, $50M-$100M, $100M-$500M, $500M-$1B, $1B-$5B, $5B-$10B, $10B+. The app has no custom revenue range, so the API uses the same buckets and the counts stay comparable.

When a count in the app doesn't match ours, check the UNVERIFIED rows first, fix the key here and in the builder, and add the case to the test.

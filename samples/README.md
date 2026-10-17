# Sample policies

Both are fictional drafts with deliberately planted gaps. Test them with **Policy type: AML/KYC**, country **Pakistan** (region Punjab), which matches the seeded global corpus (FATF Recommendations, Basel Core Principles, Basel AML guidelines).

| File | Institution type |
| --- | --- |
| `sample_aml_policy.txt` | Commercial bank (also the source of the frontend mock report) |
| `demo_digital_bank_aml_policy.txt` / `.docx` | Digital bank (same text; the `.docx` exercises the Word parser) |

## Answer key: `demo_digital_bank_aml_policy`

Expected findings, based on the FATF Recommendations. Wording and severity will vary between runs.

| Clause | Planted gap | Likely type | FATF basis |
| --- | --- | --- | --- |
| 3.2 | Compliance head reports to the growth/sales lead | Insufficient | R.18 (compliance officer at management level) |
| 3.3 | No independent audit of the AML programme | Contradiction | R.18 (independent audit function) |
| 4.2 | New products assessed up to 6 months *after* launch | Contradiction | R.15 (assess risk before launch) |
| 5.2 | Unverified wallets with no time limit | Contradiction | R.10 (no anonymous accounts; verify identity) |
| 5.3 | Beneficial ownership threshold of 40% | Insufficient | R.10 / R.24–25 interpretive notes |
| 5.4 | Purpose of relationship only "when easy" | Ambiguous | R.10 (understand purpose and intended nature) |
| 6.2 | PEPs opened without senior management approval | Contradiction | R.12 |
| 7.1 | Sanctions screening at onboarding only | Insufficient | R.6 |
| 7.2 | Asset freeze delayed up to 10 business days | Contradiction | R.6 ("without delay") |
| 8.1 | Required originator/beneficiary information omitted | Contradiction | R.16 |
| 9.1 | Correspondent relationships with shell banks allowed | Contradiction | R.13 |
| 10.2 | STRs filed within 30 days of alert closure | Insufficient | R.20 ("promptly") |
| 11.1 | Records kept 4 years | Contradiction | R.11 (at least five years) |
| — | No tipping-off prohibition | Missing | R.21 |

Clauses that should **not** be flagged (they are reasonable): 1.1–2.3, 5.1, 6.1, 10.1, 12.1.

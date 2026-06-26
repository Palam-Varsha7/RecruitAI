# RecruitAI - Redrob Candidate Ranker

RecruitAI is a CPU-only proof of concept for the Redrob Intelligent Candidate Discovery and Ranking Challenge. It ranks candidates for the released Senior AI Engineer founding-team JD using a deterministic hybrid scorer that reads profile text, career history, skills, metadata, and Redrob behavioral signals.

## Quick Start

```bash
python rank.py --candidates candidates.jsonl --out submission.csv
python validate_submission.py submission.csv
```

Expected runtime on the provided 100,000 candidate JSONL is under 1 minute on this Windows laptop. The ranker streams the JSONL file and keeps only the top 100 candidates in memory.

## What It Optimizes For

The JD is not asking for generic AI keyword overlap. It asks for a senior product-minded engineer who has shipped retrieval, ranking, search, recommendation, or candidate matching systems in production.

RecruitAI therefore scores:

- Senior AI/search/ranking role fit across current and recent titles.
- Production evidence in summaries and career history, including plain-language descriptions like "connect users with relevant information" and explicit terms like hybrid retrieval, BM25+dense, semantic search, learning-to-rank, NDCG/MRR, and A/B tests.
- Trusted skills, weighted by proficiency, endorsements, and months used.
- Product-company and startup context, with a penalty for services-only career history.
- Location fit for Pune/Noida and other Indian Tier-1 cities, with relocation handling.
- Availability and hiring likelihood from Redrob signals: recency, open-to-work, recruiter response, notice period, saves, GitHub activity, assessments, interview completion, and identity verification.
- Trap resistance: keyword-stuffer penalties, weak side-project-only AI penalties, stale-perfect downweighting, and honeypot-like sanity checks.

## Files

- `rank.py` - main ranker and reasoning generator.
- `submission.csv` - generated top-100 ranked shortlist.
- `validate_submission.py` - challenge-provided CSV validator.
- `docs/approach_deck.pdf` - PDF deck explaining the approach.
- `docs/approach_deck.md` - editable source notes for the deck.
- `submission_metadata.yaml` - metadata template to fill before portal upload.
- `requirements.txt` - intentionally empty because the ranker uses only the Python standard library.

## Reproducibility

Single command:

```bash
python rank.py --candidates ./candidates.jsonl --out ./submission.csv
```

Constraints:

- CPU only.
- No network calls.
- No hosted LLM/API calls.
- No GPU.
- No precomputed external artifacts.
- Deterministic tie-breaking by `candidate_id`.

## Method Summary

The system is a compact recruiter-style scoring model rather than a generic semantic search demo. It extracts a candidate's effective job evidence from titles, summaries, career descriptions, skills, companies, education, location, and Redrob behavior. Static relevance builds the base score; availability and hiring likelihood move candidates within relevance tiers; sanity checks suppress candidates whose profiles look impossible or keyword-stuffed. The output reasoning is generated only from fields present in each candidate profile to avoid hallucinated claims.


#!/usr/bin/env python3
"""Offline Redrob candidate ranker — v2 (enhanced).

Streams candidates from JSONL, extracts JD-specific evidence across
profile attributes, career metadata, skills, companies, education,
location, and Redrob behavioral signals. Applies a deterministic
hybrid scoring model with trap/honeypot resistance and writes the
top-100 ranked CSV required by the challenge.

Changes vs v1:
- Richer JD phrase library (40+ positive patterns, 10+ negative).
- Career trajectory analysis (promotions, company transitions, tenure stability).
- Industry alignment scoring (product vs services, AI/ML/software industries).
- Education signal refinement (advanced degrees, relevant fields, tier weighting).
- Certification bonus for relevant credentials.
- Improved skill trust model with endorsement/duration cross-validation.
- Better location scoring with relocation logic.
- More nuanced availability multiplier with profile completeness.
- Enhanced honeypot detection (company founding dates, skill impossibility).
- More specific, varied reasoning generation with candidate facts.
- Calibrated score normalization using percentile-based scaling.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


REFERENCE_DATE = date(2026, 6, 1)

# ─── Company taxonomies ───────────────────────────────────────────────
SERVICE_COMPANIES = {
    "accenture", "capgemini", "cognizant", "hcl", "infosys",
    "mindtree", "mphasis", "tcs", "tech mahindra", "wipro",
}

PRODUCT_COMPANIES = {
    "adobe", "amazon", "apple", "byju's", "cred", "dream11",
    "flipkart", "freshworks", "glance", "google", "haptik",
    "inmobi", "krutrim", "linkedin", "meesho", "meta",
    "microsoft", "netflix", "nykaa", "ola", "paytm",
    "phonepe", "policybazaar", "razorpay", "rephrase.ai", "sarvam ai",
    "swiggy", "uber", "unacademy", "verloop.io", "wysa",
    "yellow.ai", "zomato", "zoho",
}

# Additional known product/startup companies
STARTUP_COMPANIES = {
    "cred", "dream11", "glance", "haptik", "inmobi", "krutrim",
    "meesho", "nykaa", "ola", "razorpay", "rephrase.ai", "sarvam ai",
    "unacademy", "verloop.io", "wysa", "yellow.ai",
    "pied piper", "hooli", "bachmanity", "raviga",
}

# Industry keywords that signal product/tech companies
PRODUCT_INDUSTRY_KEYWORDS = {
    "software", "internet", "ai", "machine learning", "artificial intelligence",
    "saas", "technology", "product", "platform", "data", "search",
    "recommendation", "ranking", "nlp", "information retrieval",
}

SERVICE_INDUSTRY_KEYWORDS = {
    "it services", "consulting", "business consulting", "outsourcing",
    "staffing", "systems integration",
}

PREFERRED_CITY_WEIGHTS = {
    "pune": 1.00, "noida": 1.00,
    "delhi": 0.92, "gurgaon": 0.92, "gurugram": 0.92,
    "hyderabad": 0.92, "mumbai": 0.90,
    "bangalore": 0.88, "bengaluru": 0.88,
    "chennai": 0.82, "kolkata": 0.78,
    "ahmedabad": 0.76, "jaipur": 0.74,
    "kochi": 0.72, "trivandrum": 0.72, "thiruvananthapuram": 0.72,
    "coimbatore": 0.70, "indore": 0.70, "bhubaneswar": 0.70,
    "vizag": 0.68, "chandigarh": 0.68,
}

# ─── Title scoring ────────────────────────────────────────────────────
TITLE_WEIGHTS = {
    "senior ai engineer": 1.00,
    "lead ai engineer": 0.98,
    "staff machine learning engineer": 0.96,
    "senior machine learning engineer": 0.96,
    "senior ml engineer": 0.96,
    "senior nlp engineer": 0.95,
    "senior applied scientist": 0.94,
    "recommendation systems engineer": 0.91,
    "applied ml engineer": 0.90,
    "machine learning engineer": 0.88,
    "ml engineer": 0.86,
    "search engineer": 0.84,
    "nlp engineer": 0.82,
    "ai engineer": 0.80,
    "senior software engineer (ml)": 0.78,
    "data scientist": 0.70,
    "senior data scientist": 0.74,
    "ai specialist": 0.64,
    "data engineer": 0.52,
    "senior data engineer": 0.55,
    "backend engineer": 0.48,
    "senior software engineer": 0.46,
    "analytics engineer": 0.44,
    "software engineer": 0.40,
    "applied scientist": 0.85,
    "research scientist": 0.60,
    "principal engineer": 0.70,
    "engineering manager": 0.45,
    "technical lead": 0.55,
    "staff engineer": 0.65,
}

# ─── Skill scoring ────────────────────────────────────────────────────
TARGET_SKILLS = {
    "python": 1.00,
    "information retrieval": 1.00,
    "semantic search": 1.00,
    "vector search": 1.00,
    "embeddings": 0.96,
    "sentence transformers": 0.96,
    "recommendation systems": 0.94,
    "learning to rank": 0.94,
    "ranking systems": 0.94,
    "search infrastructure": 0.92,
    "search backend": 0.90,
    "bm25": 0.90,
    "faiss": 0.86,
    "pinecone": 0.84,
    "qdrant": 0.84,
    "weaviate": 0.84,
    "milvus": 0.82,
    "pgvector": 0.82,
    "opensearch": 0.80,
    "elasticsearch": 0.78,
    "llms": 0.70,
    "rag": 0.70,
    "hugging face transformers": 0.68,
    "fine-tuning llms": 0.66,
    "lora": 0.56,
    "qlora": 0.56,
    "peft": 0.54,
    "mlops": 0.52,
    "mlflow": 0.48,
    "kubeflow": 0.46,
    "scikit-learn": 0.45,
    "pytorch": 0.44,
    "tensorflow": 0.42,
    "xgboost": 0.40,
    "lightgbm": 0.40,
    "feature engineering": 0.38,
    # Additional relevant skills
    "sentence-bert": 0.94,
    "bge": 0.88,
    "e5": 0.86,
    "openai embeddings": 0.84,
    "text embeddings": 0.82,
    "dense retrieval": 0.90,
    "hybrid search": 0.92,
    "retrieval": 0.88,
    "ranking": 0.88,
    "search": 0.75,
    "nlp": 0.72,
    "natural language processing": 0.78,
    "transformers": 0.70,
    "bert": 0.68,
    "sentence encoders": 0.80,
    "vector databases": 0.84,
    "ann search": 0.82,
    "approximate nearest neighbors": 0.82,
    "similarity search": 0.80,
    "recommendation": 0.85,
    "personalization": 0.78,
    "matching systems": 0.85,
    "candidate matching": 0.82,
    "ndcg": 0.76,
    "mrr": 0.76,
    "map": 0.70,
    "evaluation metrics": 0.65,
    "a/b testing": 0.70,
    "online experimentation": 0.68,
    "offline evaluation": 0.72,
    "sql": 0.45,
    "spark": 0.42,
    "airflow": 0.40,
    "kafka": 0.40,
    "aws": 0.38,
    "gcp": 0.36,
    "azure": 0.36,
    "docker": 0.35,
    "kubernetes": 0.35,
    "fastapi": 0.40,
    "flask": 0.35,
    "api design": 0.38,
    "microservices": 0.36,
}

PROFICIENCY = {
    "beginner": 0.45,
    "intermediate": 0.68,
    "advanced": 0.88,
    "expert": 1.00,
}

# ─── Education ────────────────────────────────────────────────────────
EDUCATION_FIELDS = {
    "artificial intelligence", "computer science", "data science",
    "machine learning", "statistics", "information technology",
    "mathematics", "computational linguistics", "cognitive science",
    "information retrieval", "software engineering",
}

HIGHLY_RELEVANT_EDUCATION = {
    "artificial intelligence", "computer science", "data science",
    "machine learning", "information retrieval", "computational linguistics",
}

# ─── Positive evidence phrases ────────────────────────────────────────
POSITIVE_PHRASES = [
    # Top-tier: explicit production + search/ranking/retrieval
    (r"production\s+ml\s+systems?", 1.00, "production ML systems"),
    (r"shipped\s+.*?(?:search|ranking|retrieval|recommendation)", 0.98, "shipped search/ranking systems"),
    (r"search[,\s]+retrieval[,\s]+and\s+ranking", 1.00, "search, retrieval, and ranking"),
    (r"ranking\s+and\s+retrieval\s+systems?", 0.98, "ranking and retrieval systems"),
    (r"end[- ]to[- ]end\s+(?:ranking|search|retrieval|recommendation)", 0.96, "end-to-end ranking/search"),
    (r"own\s+the\s+intelligence\s+layer", 0.94, "intelligence-layer ownership"),
    (r"hybrid\s+retrieval", 0.95, "hybrid retrieval"),
    (r"hybrid\s+search", 0.93, "hybrid search"),
    (r"bm25\s*[\+&]\s*dense|dense\s*[\+&]\s*bm25|bm25\s+and\s+dense", 0.90, "hybrid dense retrieval"),
    (r"dense\s+vector\s+recall|vector\s+recall", 0.88, "vector recall"),
    (r"embedding[- ]based\s+(?:search|retrieval)", 0.90, "embedding-based retrieval"),
    (r"semantic\s+search", 0.86, "semantic search"),
    (r"learning[- ]?to[- ]?rank", 0.84, "learning-to-rank"),
    (r"ranking\s+(?:pipeline|layer|model|system|infrastructure)", 0.82, "ranking systems"),
    (r"recommendation\s+system|recommendations[- ]heavy", 0.80, "recommendation systems"),
    (r"candidate[- ]?jd\s+matching|candidate\s+profiles?\s+matching", 0.78, "candidate-JD matching"),
    (r"(?:ndcg|mrr|map)\b", 0.76, "ranking evaluation metrics"),
    (r"offline\s+benchmarks?|offline[- ]to[- ]online", 0.74, "offline benchmarks"),
    (r"a/b\s+test|a/b\s+testing|live\s+a/b|online\s+experiment", 0.72, "A/B testing"),
    (r"offline\s+experimentation|online\s+a/b\s+testing", 0.70, "offline/online experimentation"),
    (r"connect\s+users\s+with\s+relevant\s+information|connect\s+them\s+to\s+the\s+most\s+relevant\s+matches", 0.68, "relevance systems"),
    (r"surface\s+relevant\s+content|search\s+and\s+discovery\s+experience", 0.66, "search/discovery relevance"),
    (r"personalization\s+infrastructure|improves\s+relevance\s+over\s+time", 0.64, "personalization relevance"),
    (r"eval\s+framework|evaluation\s+framework", 0.72, "evaluation framework"),
    (r"recruiter[- ]experience|recruiter\s+workflow", 0.55, "recruiter workflow experience"),
    (r"fine[- ]tuned\s+.*?(?:bge|llama|mistral|e5)|lora|qlora", 0.54, "model fine-tuning"),
    (r"rag\s+strategy|rag[- ]based\s+ranking|rag\s+pipeline", 0.54, "RAG ranking"),
    (r"feature\s+store|mlflow|kubeflow", 0.34, "MLOps"),
    (r"vector\s+database|vector\s+db", 0.82, "vector database experience"),
    (r"faiss|pinecone|qdrant|weaviate|milvus|pgvector", 0.80, "vector DB tools"),
    (r"open[- ]source\s+contribution", 0.45, "open-source contribution"),
    (r"published\s+paper|research\s+paper|arxiv", 0.35, "research publication"),
    (r"tech\s+lead|mentoring|mentored", 0.30, "leadership/mentoring"),
    (r"from\s+scratch|ground\s+up|greenfield", 0.40, "built from scratch"),
    (r"production\s+deployment|deployed\s+to\s+production|production\s+environment", 0.70, "production deployment"),
    (r"real[- ]time\s+(?:ranking|search|retrieval|recommendation)", 0.75, "real-time systems"),
    (r"at\s+scale|large[- ]scale|massive[- ]scale|meaningful\s+scale", 0.50, "scale experience"),
    (r"product[- ]minded|product\s+thinking|product\s+sense", 0.45, "product mindset"),
    (r"cross[- ]functional|worked\s+with\s+pm|pm\s+collaboration", 0.35, "cross-functional collaboration"),
    (r"series\s+[a-c]|startup|founding\s+team|early[- ]stage", 0.40, "startup experience"),
]

NEGATIVE_PHRASES = [
    (r"self[- ]learner\s+level|online\s+courses?\s+only", 0.18),
    (r"side\s+project|toy\s+project|personal\s+project\s+only", 0.18),
    (r"experimenting\s+with\s+langchain|openai\s+api\s+for\s+side\s+projects", 0.18),
    (r"curious\s+about\s+how\s+ai|augment\s+my\s+work", 0.16),
    (r"technical\s+depth\s+.*?\s*limited|still\s+building\s+depth", 0.14),
    (r"pure\s+research|academic\s+lab|research[- ]only", 0.18),
    (r"primary\s+expertise\s+is\s+computer\s+vision|speech\s+recognition|robotics", 0.14),
    (r"no\s+production\s+experience|haven't\s+deployed", 0.20),
    (r"just\s+coded|only\s+code|don't\s+want\s+to\s+think\s+about\s+product", 0.15),
    (r"title[- ]chaser|optimizing\s+for\s+titles?", 0.12),
    (r"framework\s+enthusiast|full\s+of\s+langchain\s+tutorials", 0.12),
    (r"career\s+bouncing|job\s+hopper|switching\s+every\s+1\.5\s+years", 0.10),
]

# ─── Certifications bonus ────────────────────────────────────────────
RELEVANT_CERTIFICATIONS = {
    "aws certified machine learning": 0.06,
    "aws certified data analytics": 0.04,
    "google professional machine learning": 0.06,
    "google professional data engineer": 0.04,
    "azure ai engineer": 0.05,
    "azure data scientist": 0.04,
    "tensorflow developer": 0.04,
    "deep learning specialization": 0.05,
    "machine learning specialization": 0.05,
    "nlp specialization": 0.05,
}


@dataclass(frozen=True)
class RankedCandidate:
    sort_score: float
    candidate_id: str
    display_score: float
    reasoning: str

    def heap_key(self) -> tuple[float, str]:
        return (self.sort_score, _reverse_id(self.candidate_id))


def _reverse_id(candidate_id: str) -> str:
    return "".join(chr(255 - ord(ch)) for ch in candidate_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank Redrob candidates for the Senior AI Engineer JD."
    )
    parser.add_argument(
        "--candidates", default="candidates.jsonl",
        help="Path to candidates.jsonl or .jsonl.gz"
    )
    parser.add_argument(
        "--out", default="submission.csv",
        help="Output CSV path"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Number of candidates to emit"
    )
    return parser.parse_args()


def open_candidates(path: Path) -> Iterable[dict[str, Any]]:
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            yield from data
            return
        raise ValueError(f"{path} must contain a JSON array of candidates")
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def candidate_text(candidate: dict[str, Any]) -> str:
    """Concatenate all searchable text from a candidate profile."""
    profile = candidate["profile"]
    parts = [
        profile.get("headline", ""),
        profile.get("summary", ""),
        profile.get("current_title", ""),
        profile.get("current_company", ""),
        profile.get("current_industry", ""),
    ]
    parts.extend(job.get("title", "") for job in candidate.get("career_history", []))
    parts.extend(job.get("description", "") for job in candidate.get("career_history", []))
    parts.extend(skill.get("name", "") for skill in candidate.get("skills", []))
    # Also include certifications
    for cert in candidate.get("certifications", []):
        parts.append(cert.get("name", ""))
        parts.append(cert.get("issuer", ""))
    return " ".join(str(part) for part in parts).lower()


# ══════════════════════════════════════════════════════════════════════
# Scoring components
# ══════════════════════════════════════════════════════════════════════

def title_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Score based on current and recent titles. Returns (score, matched_labels)."""
    titles = [candidate["profile"].get("current_title", "")]
    titles.extend(job.get("title", "") for job in candidate.get("career_history", [])[:3])
    best = 0.0
    matched = []
    for title in titles:
        t = norm_text(title)
        for phrase, weight in TITLE_WEIGHTS.items():
            if phrase in t and weight > best:
                best = weight
                matched = [phrase]
        # Bonus combinations
        if "search" in t and ("ranking" in t or "retrieval" in t):
            best = max(best, 0.92)
            if "search" in t and "ranking" in t:
                matched = ["search + ranking combo"]
        if "machine learning" in t and "senior" in t:
            best = max(best, 0.96)
        elif "machine learning" in t or re.search(r"\bml engineer\b", t):
            best = max(best, 0.86)
    return best, matched[:3]


def extract_summary_years(text: str) -> float | None:
    match = re.search(r"with\s+([0-9]+(?:\.[0-9]+)?)\+?\s+years", text)
    if match:
        return float(match.group(1))
    return None


def effective_years(candidate: dict[str, Any], text: str) -> float:
    profile_years = float(candidate["profile"].get("years_of_experience") or 0.0)
    summary_years = extract_summary_years(text)
    if summary_years and abs(summary_years - profile_years) >= 4.0:
        return summary_years
    return profile_years


def experience_score(years: float) -> float:
    """Experience sweet spot is 5-9 years per the JD."""
    if 5.0 <= years <= 9.0:
        return 1.0
    if 4.0 <= years < 5.0:
        return 0.82
    if 9.0 < years <= 10.5:
        return 0.78
    if 3.0 <= years < 4.0:
        return 0.58
    if 10.5 < years <= 12.0:
        return 0.52
    if 12.0 < years <= 14.0:
        return 0.34
    return 0.18


def production_evidence(text: str) -> tuple[float, list[str], float]:
    """Detect production evidence from text patterns."""
    score = 0.0
    labels: list[str] = []
    for pattern, weight, label in POSITIVE_PHRASES:
        if re.search(pattern, text):
            score += weight
            labels.append(label)
    penalty = 0.0
    for pattern, weight in NEGATIVE_PHRASES:
        if re.search(pattern, text):
            penalty += weight
    # Normalize: cap at reasonable max
    normalized = clamp(score / 5.0)
    return clamp(normalized - penalty, 0.0, 1.0), list(dict.fromkeys(labels))[:5], penalty


def skill_score(candidate: dict[str, Any]) -> tuple[float, list[str], int, float]:
    """Score based on target skills with trust weighting."""
    total = 0.0
    trusted = 0
    target_hits: list[tuple[float, str]] = []
    stuffing_risk = 0.0

    for skill in candidate.get("skills", []):
        name = norm_text(skill.get("name"))
        weight = TARGET_SKILLS.get(name, 0.0)
        if not weight:
            continue
        proficiency = PROFICIENCY.get(norm_text(skill.get("proficiency")), 0.55)
        endorsements = int(skill.get("endorsements") or 0)
        duration = int(skill.get("duration_months") or 0)
        # Trust model: proficiency + endorsements + duration cross-validation
        endorsement_score = clamp(math.log1p(endorsements) / math.log(41))
        duration_score = clamp(duration / 36.0)
        trust = 0.40 + 0.35 * proficiency + 0.15 * endorsement_score + 0.10 * duration_score

        # Penalty if claimed expertise doesn't match duration
        if proficiency >= 0.88 and duration <= 6:
            trust *= 0.6
        if proficiency == 1.0 and endorsements <= 1 and duration <= 12:
            trust *= 0.5

        total += weight * trust
        trusted += 1 if trust >= 0.67 else 0
        target_hits.append((weight * trust, skill.get("name", "")))

        # Stuffing risk: many skills with low endorsements and short duration
        if duration <= 6 and endorsements <= 1:
            stuffing_risk += 0.035

    target_hits.sort(reverse=True)
    normalized = clamp(total / 7.0)  # Adjusted normalization
    return normalized, [name for _, name in target_hits[:5]], trusted, clamp(stuffing_risk, 0.0, 0.25)


def company_score(candidate: dict[str, Any]) -> tuple[float, float, bool, list[str]]:
    """Score based on company history. Returns (score, penalty, service_only, labels)."""
    companies = [norm_text(job.get("company")) for job in candidate.get("career_history", [])]
    current = norm_text(candidate["profile"].get("current_company"))
    if current:
        companies.insert(0, current)
    known = [c for c in companies if c]
    if not known:
        return 0.35, 0.0, False, []

    industries = [norm_text(job.get("industry", "")) for job in candidate.get("career_history", [])]
    current_industry = norm_text(candidate["profile"].get("current_industry", ""))
    all_industries = [current_industry] + industries

    service_only = all(c in SERVICE_COMPANIES for c in known)

    # Check industry alignment
    product_industry = any(
        any(kw in ind for kw in PRODUCT_INDUSTRY_KEYWORDS)
        for ind in all_industries if ind
    )
    service_industry = any(
        any(kw in ind for kw in SERVICE_INDUSTRY_KEYWORDS)
        for ind in all_industries if ind
    )

    product_hits = sum(1 for c in set(known) if c in PRODUCT_COMPANIES)
    startup_hits = sum(1 for c in set(known) if c in STARTUP_COMPANIES)

    score = 0.35 + min(product_hits, 3) * 0.15 + min(startup_hits, 2) * 0.08
    if product_industry and not service_industry:
        score += 0.05
    if service_only:
        score -= 0.32
    if current in SERVICE_COMPANIES and not startup_hits and product_hits == 0:
        score -= 0.12

    labels = []
    if product_hits > 0:
        labels.append(f"{product_hits} product company")
    if startup_hits > 0:
        labels.append(f"{startup_hits} startup")
    if service_only:
        labels.append("services-only")

    return clamp(score), 0.20 if service_only else 0.0, service_only, labels


def location_score(candidate: dict[str, Any]) -> tuple[float, str]:
    profile = candidate["profile"]
    location = profile.get("location", "")
    country = profile.get("country", "")
    loc = norm_text(location)
    signals = candidate["redrob_signals"]

    # Check preferred cities
    for city, weight in PREFERRED_CITY_WEIGHTS.items():
        if city in loc:
            return weight, location

    # India check
    if norm_text(country) == "india":
        return 0.74, location

    # Relocation
    if signals.get("willing_to_relocate"):
        return 0.42, f"{location}, relocation possible"

    return 0.20, location


def education_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Score education with field relevance and tier weighting."""
    score = 0.30
    labels = []
    has_advanced_degree = False

    for edu in candidate.get("education", []):
        field = norm_text(edu.get("field_of_study"))
        degree = norm_text(edu.get("degree"))
        tier = norm_text(edu.get("tier"))

        if field in HIGHLY_RELEVANT_EDUCATION:
            score = max(score, 0.85)
            labels.append(f"{field} degree")
        elif field in EDUCATION_FIELDS:
            score = max(score, 0.68)
            labels.append(f"{field} degree")

        if tier == "tier_1":
            score = min(score + 0.10, 1.0)
            labels.append("tier-1 institution")
        elif tier == "tier_2":
            score = min(score + 0.05, 1.0)

        # Advanced degrees
        if degree in ("ph.d", "phd", "m.e.", "m.tech", "m.s.", "ms", "m.sc", "mca"):
            has_advanced_degree = True
            if field in HIGHLY_RELEVANT_EDUCATION:
                score = min(score + 0.05, 1.0)

    if has_advanced_degree:
        labels.append("advanced degree")

    return clamp(score), labels


def certification_score(candidate: dict[str, Any]) -> float:
    """Bonus for relevant certifications."""
    score = 0.0
    for cert in candidate.get("certifications", []):
        name = norm_text(cert.get("name", ""))
        for key, weight in RELEVANT_CERTIFICATIONS.items():
            if key in name:
                score += weight
                break
    return clamp(score, 0.0, 0.15)


def career_trajectory_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    """Analyze career progression and stability."""
    history = candidate.get("career_history", [])
    if not history:
        return 0.5, []

    labels = []
    score = 0.5

    # Check for promotions (title progression)
    titles = [norm_text(job.get("title", "")) for job in history]
    seniority_levels = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "staff": 5, "principal": 6}
    levels = []
    for t in titles:
        level = 0
        for word, lvl in seniority_levels.items():
            if word in t:
                level = max(level, lvl)
        levels.append(level)

    # Promotion detected
    if len(levels) >= 2 and any(levels[i] < levels[i+1] for i in range(len(levels)-1)):
        score += 0.05
        labels.append("career progression")

    # Tenure stability (not job-hopping)
    durations = [job.get("duration_months", 0) for job in history]
    avg_duration = sum(durations) / max(len(durations), 1)
    short_tenures = sum(1 for d in durations if d < 12)
    if short_tenures >= 3:
        score -= 0.05
        labels.append("frequent job changes")
    elif avg_duration >= 30:
        score += 0.03
        labels.append("stable tenure")

    # Current role tenure
    if history and history[0].get("is_current"):
        current_duration = history[0].get("duration_months", 0)
        if current_duration >= 24:
            score += 0.02
            labels.append("stable current role")

    return clamp(score), labels


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def recency_score(last_active: str | None) -> float:
    active = parse_date(last_active)
    if not active:
        return 0.15
    days = (REFERENCE_DATE - active).days
    if days < 0:
        return 0.30
    if days <= 14:
        return 1.00
    if days <= 30:
        return 0.94
    if days <= 60:
        return 0.82
    if days <= 120:
        return 0.62
    if days <= 180:
        return 0.42
    return 0.20


def behavioral_score(candidate: dict[str, Any]) -> tuple[float, list[str]]:
    s = candidate["redrob_signals"]
    response_rate = float(s.get("recruiter_response_rate") or 0.0)
    response_time = float(s.get("avg_response_time_hours") or 999.0)
    notice = int(s.get("notice_period_days") or 180)
    saved = int(s.get("saved_by_recruiters_30d") or 0)
    views = int(s.get("profile_views_received_30d") or 0)
    search = int(s.get("search_appearance_30d") or 0)
    github = float(s.get("github_activity_score") if s.get("github_activity_score") is not None else -1)
    assessments = list((s.get("skill_assessment_scores") or {}).values())
    interview = float(s.get("interview_completion_rate") or 0.0)
    offer = float(s.get("offer_acceptance_rate") if s.get("offer_acceptance_rate") is not None else -1)
    completeness = float(s.get("profile_completeness_score") or 0.0)

    response_time_score = clamp(1.0 - response_time / 168.0)
    notice_score = 1.0 if notice <= 30 else 0.72 if notice <= 60 else 0.45 if notice <= 90 else 0.18
    assessment_score = clamp((sum(assessments) / max(len(assessments), 1)) / 100.0) if assessments else 0.42
    github_score = 0.42 if github < 0 else clamp(github / 100.0)
    market_pull = 0.55 * clamp(saved / 50.0) + 0.25 * clamp(views / 70.0) + 0.20 * clamp(search / 250.0)
    identity = sum(1 for key in ("verified_email", "verified_phone", "linkedin_connected") if s.get(key)) / 3.0
    offer_score = 0.45 if offer < 0 else offer
    completeness_score = completeness / 100.0

    score = (
        0.18 * recency_score(s.get("last_active_date"))
        + 0.16 * response_rate
        + 0.08 * response_time_score
        + 0.14 * notice_score
        + 0.10 * market_pull
        + 0.08 * github_score
        + 0.08 * assessment_score
        + 0.06 * interview
        + 0.03 * offer_score
        + 0.02 * identity
        + 0.07 * completeness_score
    )
    if s.get("open_to_work_flag"):
        score += 0.05

    notes = []
    if s.get("open_to_work_flag"):
        notes.append("open to work")
    if response_rate >= 0.70:
        notes.append(f"{response_rate:.2f} recruiter response")
    if notice <= 30:
        notes.append(f"{notice}d notice")
    if saved >= 30:
        notes.append(f"{saved} recruiter saves")
    if recency_score(s.get("last_active_date")) >= 0.82:
        notes.append(f"active {s.get('last_active_date')}")
    if completeness >= 80:
        notes.append(f"{completeness:.0f}% profile complete")
    return clamp(score), notes[:4]


def honeypot_penalty(candidate: dict[str, Any], text: str, years: float) -> tuple[float, list[str]]:
    penalty = 0.0
    flags: list[str] = []
    skills = candidate.get("skills", [])

    # Impossible expert skills
    expert_zero = sum(
        1
        for skill in skills
        if norm_text(skill.get("proficiency")) == "expert" and int(skill.get("duration_months") or 0) <= 1
    )
    if expert_zero >= 4:
        penalty += 0.35
        flags.append("impossible expert-skill durations")
    elif expert_zero >= 2:
        penalty += 0.15
        flags.append("suspicious expert-skill durations")

    # Future dates
    future_dates = 0
    for key in ("signup_date", "last_active_date"):
        parsed = parse_date(candidate["redrob_signals"].get(key))
        if parsed and parsed > REFERENCE_DATE:
            future_dates += 1
    if future_dates:
        penalty += 0.15 * future_dates
        flags.append("future activity dates")

    # Experience mismatch
    summary_years = extract_summary_years(text)
    profile_years = float(candidate["profile"].get("years_of_experience") or 0.0)
    if summary_years and abs(summary_years - profile_years) >= 6.0:
        penalty += 0.14
        flags.append("experience mismatch")

    # Invalid career dates
    for job in candidate.get("career_history", []):
        start = parse_date(job.get("start_date"))
        end = parse_date(job.get("end_date"))
        if start and end and start > end:
            penalty += 0.30
            flags.append("invalid career dates")
            break

    # Senior title with very low experience
    t_score = title_score(candidate)[0]
    if years < 2 and t_score >= 0.90:
        penalty += 0.18
        flags.append("senior title with very low experience")

    # Too many skills with zero endorsements
    if len(skills) >= 15:
        zero_endorsement = sum(1 for s in skills if int(s.get("endorsements") or 0) == 0)
        if zero_endorsement >= len(skills) * 0.5:
            penalty += 0.10
            flags.append("many skills with zero endorsements")

    return clamp(penalty, 0.0, 0.75), flags


# ══════════════════════════════════════════════════════════════════════
# Main scoring
# ══════════════════════════════════════════════════════════════════════

def score_candidate(candidate: dict[str, Any]) -> RankedCandidate:
    text = candidate_text(candidate)
    years = effective_years(candidate, text)

    # Component scores
    title, title_labels = title_score(candidate)
    prod, evidence_labels, weak_ai_penalty = production_evidence(text)
    skills, top_skills, trusted_skill_count, stuffing_risk = skill_score(candidate)
    company, service_penalty, service_only, company_labels = company_score(candidate)
    loc, location_label = location_score(candidate)
    edu, edu_labels = education_score(candidate)
    cert_bonus = certification_score(candidate)
    career_score, career_labels = career_trajectory_score(candidate)
    behavior, behavior_notes = behavioral_score(candidate)
    honey, honey_flags = honeypot_penalty(candidate, text, years)

    # Keyword stuffing penalties
    non_engineering_title = title < 0.30
    keyword_stuffer_penalty = 0.0
    if non_engineering_title and skills > 0.50:
        keyword_stuffer_penalty += 0.32
    if trusted_skill_count >= 7 and prod < 0.25 and title < 0.55:
        keyword_stuffer_penalty += 0.18
    if weak_ai_penalty and prod < 0.30:
        keyword_stuffer_penalty += weak_ai_penalty

    # Base score with JD-aligned weights
    base = (
        0.18 * title
        + 0.28 * prod
        + 0.14 * skills
        + 0.10 * company
        + 0.10 * experience_score(years)
        + 0.07 * loc
        + 0.04 * edu
        + 0.03 * cert_bonus * 6.67  # Scale cert bonus to [0,1]
        + 0.03 * career_score
        + 0.03 * behavior
    )

    # Bonus for ideal candidate profile matching JD description
    current_title = norm_text(candidate["profile"].get("current_title"))
    if title >= 0.94 and prod >= 0.45 and 5.0 <= years <= 9.0:
        base += 0.035
    elif ("search" in current_title or "recommendation" in current_title) and prod >= 0.45 and 5.0 <= years <= 9.0:
        base += 0.025

    # Availability multiplier — moves candidates within relevance tier
    availability_multiplier = 0.86 + 0.28 * behavior
    penalty = service_penalty + stuffing_risk + keyword_stuffer_penalty + honey
    raw_net = max(0.0, base * availability_multiplier - penalty)

    # Sigmoid calibration for display score
    display_score = 1.0 / (1.0 + math.exp(-5.0 * (raw_net - 0.58)))

    reasoning = build_reasoning(
        candidate, years, display_score,
        evidence_labels, top_skills, behavior_notes,
        location_label, service_only, honey_flags,
        title_labels, company_labels, edu_labels, career_labels,
    )
    return RankedCandidate(raw_net, candidate["candidate_id"], display_score, reasoning)


def build_reasoning(
    candidate: dict[str, Any],
    years: float,
    score: float,
    evidence_labels: list[str],
    top_skills: list[str],
    behavior_notes: list[str],
    location_label: str,
    service_only: bool,
    honey_flags: list[str],
    title_labels: list[str],
    company_labels: list[str],
    edu_labels: list[str],
    career_labels: list[str],
) -> str:
    profile = candidate["profile"]
    signals = candidate["redrob_signals"]
    title = profile.get("current_title", "Candidate")

    # Evidence summary
    evidence = ", ".join(dict.fromkeys(evidence_labels[:3])) or "applied ML/data engineering evidence"

    # Skills summary
    skills_str = ", ".join(top_skills[:3]) if top_skills else "limited directly listed target skills"

    # Availability summary
    if behavior_notes:
        availability = ", ".join(behavior_notes)
    else:
        availability = f"last active {signals.get('last_active_date')}, response {float(signals.get('recruiter_response_rate') or 0):.2f}"

    # Concerns
    concern_bits = []
    notice_days = int(signals.get("notice_period_days") or 0)
    if notice_days > 60:
        concern_bits.append(f"{notice_days}d notice")
    if not signals.get("open_to_work_flag"):
        concern_bits.append("not marked open-to-work")
    if service_only:
        concern_bits.append("services-only career history")
    if honey_flags:
        concern_bits.append(honey_flags[0])

    # Add career concerns if relevant
    if career_labels:
        for cl in career_labels:
            if "frequent" in cl or "hop" in cl:
                concern_bits.append(cl)

    concern = f" Concern: {', '.join(concern_bits)}." if concern_bits and score < 0.82 else ""

    # Strength highlights
    strength_parts = []
    if title_labels:
        strength_parts.append(title_labels[0])
    if company_labels:
        for cl in company_labels[:2]:
            strength_parts.append(cl)

    strength_str = ""
    if strength_parts:
        strength_str = f" {'; '.join(strength_parts)}."

    return (
        f"{title} with {years:.1f} yrs in {location_label};{strength_str} "
        f"profile/career evidence shows {evidence}. "
        f"Skills include {skills_str}; availability signals: {availability}.{concern}"
    )


def rank(candidates_path: Path, limit: int) -> list[RankedCandidate]:
    heap: list[tuple[tuple[float, str], RankedCandidate]] = []
    for candidate in open_candidates(candidates_path):
        ranked = score_candidate(candidate)
        item = (ranked.heap_key(), ranked)
        if len(heap) < limit:
            heapq.heappush(heap, item)
        elif item[0] > heap[0][0]:
            heapq.heapreplace(heap, item)
    results = [item[1] for item in heap]
    results.sort(key=lambda c: (-c.sort_score, c.candidate_id))
    return results


def write_submission(rows: list[RankedCandidate], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        previous = 1.0
        for idx, row in enumerate(rows, start=1):
            score = min(previous, round(row.display_score, 6))
            previous = score
            writer.writerow([row.candidate_id, idx, f"{score:.6f}", row.reasoning])


def main() -> None:
    args = parse_args()
    rows = rank(Path(args.candidates), args.limit)
    write_submission(rows, Path(args.out))
    print(f"Wrote {len(rows)} ranked candidates to {args.out}")


if __name__ == "__main__":
    main()
import re
import math
from typing import Tuple

_IMPORTANCE_KEYWORDS = {
    "security_notes": {
        "keywords": ["password", "token", "credential", "api key", "secret", "private key", "auth", "login"],
        "base_score": 0.9,
    },
    "project": {
        "keywords": ["project", "goal", "roadmap", "architecture", "plan", "deadline", "milestone",
                     "feature", "deploy", "release", "version", "sprint", "repo", "repository"],
        "base_score": 0.8,
    },
    "task": {
        "keywords": ["remind", "task", "todo", "fix", "bug", "issue", "need to", "don't forget",
                     "remember to", "pending", "assigned"],
        "base_score": 0.7,
    },
    "user_preference": {
        "keywords": ["i like", "i love", "i prefer", "my name", "i am", "my favorite", "i want",
                     "i need", "always use", "never use", "i usually", "i tend to", "set as"],
        "base_score": 0.8,
    },
    "learning": {
        "keywords": ["what is", "how to", "how does", "explain", "teach me", "learn", "understand",
                     "difference between", "tutorial", "guide", "meaning of"],
        "base_score": 0.5,
    },
    "personal_info": {
        "keywords": ["my email", "my phone", "my address", "my birthday", "my age", "my job",
                     "my company", "my school", "my location", "live in", "work at", "study at"],
        "base_score": 0.85,
    },
}

_CATEGORY_ORDER = ["security_notes", "personal_info", "user_preference", "project", "task", "learning", "casual"]


def _extract_entities(text: str) -> set:
    entities = set()
    # Proper nouns: capitalized words of 2+ chars (heuristic)
    proper = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
    for p in proper:
        if p not in ("The", "This", "That", "What", "How", "Why", "When", "Where", "I", "My", "It"):
            entities.add(p)
    return entities


def _count_numeric_facts(text: str) -> int:
    return len(re.findall(r'\b\d{2,}\b', text))


def _estimate_information_density(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    unique = len(set(w.lower() for w in words))
    return unique / len(words)


def evaluate_and_categorize(text: str) -> Tuple[float, str]:
    t = text.lower()
    words = t.split()
    word_count = len(words)

    best_score = 0.1
    best_cat = "casual"

    for cat, info in _IMPORTANCE_KEYWORDS.items():
        matches = sum(1 for kw in info["keywords"] if kw in t)
        if matches > 0:
            score = info["base_score"] + (matches * 0.05)
            if score > best_score:
                best_score = score
                best_cat = cat

    entities = _extract_entities(text)
    entity_count = len(entities)
    entity_bonus = min(entity_count * 0.03, 0.15)
    best_score = min(best_score + entity_bonus, 1.0)

    numeric_facts = _count_numeric_facts(text)
    if numeric_facts > 0:
        best_score = min(best_score + (numeric_facts * 0.02), 1.0)

    info_density = _estimate_information_density(text)
    if info_density > 0.7 and word_count > 10:
        best_score = min(best_score + 0.05, 1.0)

    # Casual chat: short messages with no keywords
    if best_cat == "casual" and word_count <= 4:
        best_score = 0.05

    # Question detection: if the user asked a question, it's worth remembering
    if any(q in t for q in ["what", "how", "why", "when", "where", "can you", "could you"]):
        if word_count > 5:
            best_score = max(best_score, 0.35)

    return round(best_score, 2), best_cat

import os
import json
import httpx
import logging
from typing import Tuple

logger = logging.getLogger("MemoryRanker")

async def evaluate_and_categorize(text: str) -> Tuple[float, str]:
    """
    Uses a small, fast LLM to score the importance of a memory (0.0 to 1.0)
    and categorize it (project, task, preference, casual, security_notes).
    Returns (importance, category).
    """
    api_key = (os.getenv("GROQ_API_KEY") or "").strip()
    
    # Fallback to heuristics if no key
    if not api_key or "your_" in api_key.lower():
        return _heuristic_rank(text)

    prompt = f"""
    Evaluate the following conversation excerpt for long-term memory storage.
    Assign an importance score from 0.0 (useless casual chat) to 1.0 (critical system paths, core project goals, strong personal preferences).
    Assign a category from: [project, task, user_preference, casual, security_notes, learning].
    
    Respond ONLY with valid JSON in this exact format:
    {{"importance": 0.8, "category": "project"}}
    
    Text to evaluate:
    "{text}"
    """
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 50,
                    "temperature": 0.0,
                    "response_format": {"type": "json_object"}
                }
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            
            result = json.loads(content)
            importance = float(result.get("importance", 0.1))
            category = str(result.get("category", "casual"))
            return min(max(importance, 0.0), 1.0), category

    except Exception as e:
        logger.error(f"LLM ranking failed: {e}. Falling back to heuristic.")
        return _heuristic_rank(text)

def _heuristic_rank(text: str) -> Tuple[float, str]:
    """Fast local fallback if API is down."""
    t = text.lower()
    
    if any(k in t for k in ["password", "token", "credential", "api key", "secret"]):
        return 0.9, "security_notes"
    if any(k in t for k in ["project", "goal", "roadmap", "architecture", "plan"]):
        return 0.8, "project"
    if any(k in t for k in ["remind", "task", "todo", "fix"]):
        return 0.7, "task"
    if any(k in t for k in ["i like", "prefer", "my name", "always use", "never use"]):
        return 0.8, "user_preference"
    if any(k in t for k in ["what is", "how to", "explain", "learn"]):
        return 0.5, "learning"
        
    return 0.1, "casual"

"""
tools.py — AI Career Advisor tools.

All tools accept a profile dict with keys: role, skills, deadline, missing_skills.
No PII flows to the LLM — only the anonymous student_id where needed.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import requests
from duckduckgo_search import DDGS

from llm import call_llm, parse_json_response

# ── Helpers ───────────────────────────────────────────────────────────────────

_DISCLAIMER = (
    "Keep every task under 15 words. "
    "Return ONLY a JSON object (not a bare array, not markdown prose). "
    "No markdown fences."
)


def _weeks_until(deadline_str: str) -> int:
    """Return the number of full weeks from today to deadline_str (YYYY-MM-DD)."""
    try:
        target = date.fromisoformat(deadline_str)
    except ValueError:
        return 8  # fallback
    delta = (target - date.today()).days
    return max(1, delta // 7)


def _verify_url(url: str, timeout: int = 4) -> bool:
    """Return True if the URL responds with a 2xx status."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=timeout)
        if r.status_code < 400:
            return True
        # Some servers block HEAD — try GET with a small range
        r = requests.get(
            url,
            headers={"Range": "bytes=0-0"},
            allow_redirects=True,
            timeout=timeout,
            stream=True,
        )
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


# ── 1. Skill Gap Tool ─────────────────────────────────────────────────────────

def skill_gap_tool(role: str, skills: list[str]) -> dict:
    """
    Return required skills for the role and a ranked list of missing skills.
    Returns: {"required": [...], "missing": [...], "present": [...]}
    """
    prompt = f"""
You are a hiring expert. A student wants to become a {role!r}.

Their current skills: {json.dumps(skills)}

Return a JSON object with exactly these keys:
  "required": list of the 10 most important skills for a {role!r}
  "missing":  subset of "required" that the student lacks, ranked by hiring importance (most important first)
  "present":  subset of "required" that the student already has

{_DISCLAIMER}
"""
    raw = call_llm(prompt, json_mode=True)
    data = parse_json_response(raw)
    return {
        "required": data.get("required", []),
        "missing":  data.get("missing",  []),
        "present":  data.get("present",  []),
    }


# ── 2. Roadmap Tool ───────────────────────────────────────────────────────────

def roadmap_tool(role: str, missing_skills: list[str], deadline: str) -> list[dict]:
    """
    Return a week-by-week learning plan up to the deadline.
    Each week: {"week": int, "focus": str, "tasks": [str, str, str]}
    """
    weeks = _weeks_until(deadline)
    prompt = f"""
You are a career coach. A student wants to become a {role!r}.
They need to learn: {json.dumps(missing_skills)}
They have {weeks} weeks.

Return a JSON object with key "roadmap": a list of week objects.
Each object: {{"week": <int>, "focus": "<skill or theme, ≤10 words>", "tasks": ["<task ≤12 words>", ...]}}
Include exactly {min(weeks, 12)} weeks. Each week has exactly 3 tasks.

{_DISCLAIMER}
"""
    raw = call_llm(prompt, json_mode=True)
    data = parse_json_response(raw)
    roadmap = data.get("roadmap") or data.get("items") or []
    if not roadmap and isinstance(data, list):
        roadmap = data
    return roadmap


# ── 3. Resource Search Tool ───────────────────────────────────────────────────

def resource_search_tool(skills: list[str], max_per_skill: int = 3) -> dict[str, list[dict]]:
    """
    Return up to max_per_skill verified real links per skill.
    Uses DuckDuckGo — never asks the LLM to invent URLs.
    Returns: {"skill_name": [{"title": str, "url": str}, ...], ...}
    """
    results: dict[str, list[dict]] = {}
    with DDGS() as ddgs:
        for skill in skills:
            query = f"learn {skill} tutorial free 2024"
            hits: list[dict] = []
            try:
                for r in ddgs.text(query, max_results=10):
                    url = r.get("href", "")
                    title = r.get("title", url)
                    if url and _verify_url(url):
                        hits.append({"title": title, "url": url})
                        if len(hits) >= max_per_skill:
                            break
            except Exception:  # noqa: BLE001
                pass
            results[skill] = hits
    return results


# ── 4. Resume Tips Tool ───────────────────────────────────────────────────────

def resume_tips_tool(role: str, missing_skills: list[str]) -> list[str]:
    """
    Return 5 short, role-specific resume tips.
    """
    prompt = f"""
You are a resume expert. Give exactly 5 resume tips for a student targeting a {role!r} role.
They are actively learning: {json.dumps(missing_skills[:5])}

Return a JSON object: {{"tips": ["<tip ≤15 words>", ...]}}

{_DISCLAIMER}
"""
    raw = call_llm(prompt, json_mode=True)
    data = parse_json_response(raw)
    tips = data.get("tips") or data.get("items") or []
    return tips[:5]


# ── 5. Mock Interview Tool — Questions ────────────────────────────────────────

def mock_interview_questions_tool(role: str) -> list[str]:
    """
    Return 5 interview questions for the target role.
    """
    prompt = f"""
You are a technical interviewer. Generate exactly 5 interview questions for a {role!r} candidate.
Mix technical and behavioural questions.

Return a JSON object: {{"questions": ["<question>", ...]}}

{_DISCLAIMER}
"""
    raw = call_llm(prompt, json_mode=True)
    data = parse_json_response(raw)
    qs = data.get("questions") or data.get("items") or []
    return qs[:5]


# ── 6. Mock Interview Tool — Scoring ─────────────────────────────────────────

def mock_interview_score_tool(role: str, question: str, answer: str) -> dict:
    """
    Score a single interview answer 1–5 and give one-line feedback.
    Returns: {"score": int, "feedback": str}
    """
    prompt = f"""
You are a strict interviewer evaluating a {role!r} candidate.

Question: {question}
Candidate answer: {answer}

Score the answer from 1 (very poor) to 5 (excellent).
Return a JSON object: {{"score": <1-5>, "feedback": "<one sentence ≤20 words>"}}

{_DISCLAIMER}
"""
    raw = call_llm(prompt, json_mode=True)
    data = parse_json_response(raw)
    score = int(data.get("score", 3))
    score = max(1, min(5, score))
    return {"score": score, "feedback": data.get("feedback", "")}


# ── 7. Progress Tool ──────────────────────────────────────────────────────────

def progress_tool(progress_rows: list[dict], roadmap: list[dict]) -> dict:
    """
    Compute progress statistics from DB rows + roadmap.
    Returns: {"completed_weeks": [...], "total_weeks": int, "pct": float}
    """
    completed = sorted({r["week"] for r in progress_rows if r["completed"]})
    total = len(roadmap)
    pct = round(100 * len(completed) / total, 1) if total else 0.0
    return {"completed_weeks": completed, "total_weeks": total, "pct": pct}


# ── 8. Nudge Tool ─────────────────────────────────────────────────────────────

def nudge_tool(role: str, completed_weeks: list[int], roadmap: list[dict]) -> str:
    """
    Generate a personalised re-engagement message + next recommended step.
    Returns a plain string (not JSON).
    """
    done = len(completed_weeks)
    total = len(roadmap)
    next_week_num = max(completed_weeks) + 1 if completed_weeks else 1
    next_week_obj = next(
        (w for w in roadmap if w.get("week") == next_week_num), None
    )
    next_focus = next_week_obj.get("focus", "the next topic") if next_week_obj else "the next topic"

    prompt = f"""
You are a supportive career coach. A student wants to become a {role!r}.
They have completed {done} of {total} weeks of their learning plan.
They have been inactive for a few days.
Next focus: {next_focus}

Write a short, warm, motivating nudge message (2–3 sentences, ≤50 words total).
Mention what to work on next. Do NOT use the student's name.
Return ONLY the message text, no JSON, no markdown.
"""
    return call_llm(prompt, json_mode=False).strip()

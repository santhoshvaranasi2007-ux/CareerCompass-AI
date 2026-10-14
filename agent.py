"""
agent.py — Plain-Python state machine for AI Career Advisor.

States (each state = the PAGE to show next):
  "profile"       — collect role / skills / deadline
  "skill_gap"     — show required vs missing skills
  "roadmap"       — show week-by-week plan
  "resources"     — show learning resources
  "resume"        — show resume tips
  "interview"     — answer interview questions
  "interview_results" — show scores
  "progress"      — show progress chart + nudge button

Transition rules:
  profile   ──[submit]──> skill_gap
  skill_gap ──[build roadmap]──> roadmap
  roadmap   ──[find resources]──> resources
  resources ──[resume tips]──> resume
  resume    ──[start interview]──> interview
  interview ──[submit answers]──> interview_results
  interview_results / progress ──[view progress]──> progress
"""

from __future__ import annotations

STATES = [
    "profile",
    "skill_gap",
    "roadmap",
    "resources",
    "resume",
    "interview",
    "interview_results",
    "progress",
]

TRANSITIONS: dict[str, str] = {
    "profile":            "skill_gap",
    "skill_gap":          "roadmap",
    "roadmap":            "resources",
    "resources":          "resume",
    "resume":             "interview",
    "interview":          "interview_results",
    "interview_results":  "progress",
    "progress":           "progress",  # terminal — stays here
}


def next_state(current: str) -> str:
    """Return the state that follows *current* in the happy path."""
    return TRANSITIONS.get(current, "profile")


def run_skill_gap(profile: dict, tools_module) -> dict:
    """Run skill_gap_tool and return the result."""
    return tools_module.skill_gap_tool(profile["role"], profile["skills"])


def run_roadmap(profile: dict, missing_skills: list[str], tools_module) -> list[dict]:
    """Run roadmap_tool and return the roadmap list."""
    return tools_module.roadmap_tool(profile["role"], missing_skills, profile["deadline"])


def run_resources(missing_skills: list[str], tools_module) -> dict:
    """Run resource_search_tool and return resources dict."""
    return tools_module.resource_search_tool(missing_skills)


def run_resume(profile: dict, missing_skills: list[str], tools_module) -> list[str]:
    """Run resume_tips_tool and return tips list."""
    return tools_module.resume_tips_tool(profile["role"], missing_skills)


def run_interview_questions(profile: dict, tools_module) -> list[str]:
    """Run mock_interview_questions_tool and return questions list."""
    return tools_module.mock_interview_questions_tool(profile["role"])


def run_score_answers(
    profile: dict,
    questions: list[str],
    answers: list[str],
    tools_module,
    db_module,
    student_id: str,
) -> list[dict]:
    """
    Score each interview answer, persist to DB, return list of score dicts.
    """
    scored = []
    for q, a in zip(questions, answers):
        result = tools_module.mock_interview_score_tool(profile["role"], q, a)
        db_module.save_interview_score(
            student_id, q, a, result["score"], result["feedback"]
        )
        scored.append({"question": q, "answer": a, **result})
    return scored


def run_nudge(profile: dict, student_id: str, tools_module, db_module) -> str:
    """
    Generate a nudge message and persist it to DB.
    """
    roadmap = db_module.load_roadmap(student_id) or []
    progress_rows = db_module.load_progress(student_id)
    prog = tools_module.progress_tool(progress_rows, roadmap)
    message = tools_module.nudge_tool(
        profile["role"], prog["completed_weeks"], roadmap
    )
    db_module.save_nudge(student_id, message)
    return message

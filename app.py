"""
app.py — AI Career Advisor — Streamlit UI.

State machine rules:
  • st.session_state["state"] holds the CURRENT PAGE to show.
  • After any action finishes, set state to the NEXT page, then st.rerun().
  • Never set the next-page state before the action completes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import streamlit as st

import db
import agent
import tools as tools_module
from llm import parse_json_response  # re-used for display helpers

# ── Bootstrap ─────────────────────────────────────────────────────────────────

db.init_db()

st.set_page_config(
    page_title="AI Career Advisor",
    page_icon="🎯",
    layout="centered",
)

# ── Session defaults ──────────────────────────────────────────────────────────

def _ss_default(key: str, value):
    if key not in st.session_state:
        st.session_state[key] = value


_ss_default("student_id",        str(uuid.uuid4()))
_ss_default("state",             "profile")
_ss_default("profile",           None)   # dict
_ss_default("skill_gap",         None)   # dict
_ss_default("roadmap",           None)   # list
_ss_default("resources",         None)   # dict
_ss_default("resume_tips",       None)   # list
_ss_default("questions",         None)   # list[str]
_ss_default("answers",           None)   # list[str]
_ss_default("scores",            None)   # list[dict]
_ss_default("nudge_message",     None)   # str
_ss_default("error",             None)   # str

# ── Helpers ───────────────────────────────────────────────────────────────────

DISCLAIMER = (
    "⚠️ **Disclaimer:** AI-generated advice may contain errors. "
    "Verify all information with official sources before making career decisions."
)

STEP_LABELS = [
    ("profile",           "1 · Profile"),
    ("skill_gap",         "2 · Skill Gap"),
    ("roadmap",           "3 · Roadmap"),
    ("resources",         "4 · Resources"),
    ("resume",            "5 · Resume Tips"),
    ("interview",         "6 · Interview"),
    ("interview_results", "7 · Results"),
    ("progress",          "8 · Progress"),
]


def _state_index(state: str) -> int:
    for i, (s, _) in enumerate(STEP_LABELS):
        if s == state:
            return i
    return 0


def _show_header():
    st.title("🎯 AI Career Advisor")
    st.caption(DISCLAIMER)
    st.divider()


def _show_progress_bar():
    idx = _state_index(st.session_state["state"])
    total = len(STEP_LABELS)
    st.progress(idx / (total - 1))
    cols = st.columns(total)
    for i, (_, label) in enumerate(STEP_LABELS):
        with cols[i]:
            if i < idx:
                st.caption(f"✅ {label}")
            elif i == idx:
                st.caption(f"**{label}**")
            else:
                st.caption(f"⬜ {label}")


def _show_error():
    if st.session_state["error"]:
        st.error(st.session_state["error"])
        if st.button("Clear error"):
            st.session_state["error"] = None
            st.rerun()


def _safe_run(fn, *args, **kwargs):
    """Run fn(*args, **kwargs), catch exceptions, store friendly error."""
    try:
        st.session_state["error"] = None
        return fn(*args, **kwargs)
    except RuntimeError as exc:
        st.session_state["error"] = f"LLM error: {exc}"
    except Exception as exc:  # noqa: BLE001
        st.session_state["error"] = f"Something went wrong: {exc}"
    return None


# ── Pages ─────────────────────────────────────────────────────────────────────

def page_profile():
    st.subheader("👤 Your Profile")
    st.write("Tell us your target role, current skills, and preparation deadline.")

    with st.form("profile_form"):
        role = st.text_input(
            "Target role",
            placeholder="e.g. Data Scientist, Backend Engineer, Product Manager",
        )
        skills_raw = st.text_area(
            "Your current skills (comma-separated)",
            placeholder="e.g. Python, SQL, Excel",
            height=80,
        )
        deadline = st.date_input(
            "Target job start / interview date",
            value=date.today() + timedelta(weeks=8),
            min_value=date.today() + timedelta(days=1),
        )
        submitted = st.form_submit_button("Analyse my skill gap →", type="primary")

    if submitted:
        role = role.strip()
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        if not role:
            st.warning("Please enter a target role.")
            return
        if len(skills) < 1:
            st.warning("Please enter at least one skill.")
            return

        profile = {
            "role":     role,
            "skills":  skills,
            "deadline": deadline.isoformat(),
        }
        db.save_profile(st.session_state["student_id"], role, skills, deadline.isoformat())
        st.session_state["profile"] = profile

        with st.spinner("Analysing your skill gap…"):
            result = _safe_run(agent.run_skill_gap, profile, tools_module)

        if result:
            st.session_state["skill_gap"] = result
            st.session_state["state"] = "skill_gap"
            st.rerun()


def page_skill_gap():
    st.subheader("🔍 Skill Gap Analysis")
    gap = st.session_state["skill_gap"]
    profile = st.session_state["profile"]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**✅ Skills you have**")
        present = gap.get("present", [])
        if present:
            for s in present:
                st.markdown(f"- {s}")
        else:
            st.caption("None matched yet — keep learning!")

    with col2:
        st.markdown("**❌ Skills to learn** *(ranked by importance)*")
        missing = gap.get("missing", [])
        if missing:
            for i, s in enumerate(missing, 1):
                st.markdown(f"{i}. {s}")
        else:
            st.success("You have all required skills!")

    st.divider()
    st.markdown(f"**Required for {profile['role']}:**")
    for r in gap.get("required", []):
        st.markdown(f"- {r}")

    st.divider()
    if st.button("Build my learning roadmap →", type="primary", disabled=not missing):
        with st.spinner("Building your personalised roadmap…"):
            roadmap = _safe_run(
                agent.run_roadmap, profile, missing, tools_module
            )
        if roadmap:
            db.save_roadmap(st.session_state["student_id"], roadmap)
            st.session_state["roadmap"] = roadmap
            st.session_state["state"] = "roadmap"
            st.rerun()

    if not missing:
        if st.button("Skip to progress tracker →"):
            st.session_state["state"] = "progress"
            st.rerun()


def page_roadmap():
    st.subheader("🗓️ Your Learning Roadmap")
    roadmap = st.session_state["roadmap"]
    profile = st.session_state["profile"]

    if not roadmap:
        st.warning("No roadmap found. Please go back and rebuild.")
        return

    for week in roadmap:
        w = week.get("week", "?")
        focus = week.get("focus", "")
        tasks = week.get("tasks", [])
        with st.expander(f"Week {w} — {focus}", expanded=(w == 1)):
            for t in tasks:
                st.markdown(f"- {t}")

    st.divider()
    if st.button("Find learning resources →", type="primary"):
        missing = st.session_state.get("skill_gap", {}).get("missing", [])
        if not missing:
            st.warning("No missing skills to search for.")
            return
        with st.spinner("Searching for real learning resources…"):
            resources = _safe_run(agent.run_resources, missing, tools_module)
        if resources is not None:
            st.session_state["resources"] = resources
            st.session_state["state"] = "resources"
            st.rerun()


def page_resources():
    st.subheader("📚 Learning Resources")
    resources = st.session_state["resources"]

    if not resources:
        st.info("No resources found. Try again or search manually.")
    else:
        for skill, links in resources.items():
            st.markdown(f"**{skill}**")
            if links:
                for link in links:
                    st.markdown(f"- [{link['title']}]({link['url']})")
            else:
                st.caption("No verified links found — search manually.")
            st.markdown("")

    st.info("ℹ️ All links are verified — they loaded successfully at the time of search.")
    st.divider()
    if st.button("Get resume tips →", type="primary"):
        profile = st.session_state["profile"]
        missing = st.session_state.get("skill_gap", {}).get("missing", [])
        with st.spinner("Generating resume tips…"):
            tips = _safe_run(agent.run_resume, profile, missing, tools_module)
        if tips:
            st.session_state["resume_tips"] = tips
            st.session_state["state"] = "resume"
            st.rerun()


def page_resume():
    st.subheader("📝 Resume Tips")
    profile = st.session_state["profile"]
    tips = st.session_state["resume_tips"] or []

    st.write(f"Role-specific tips for **{profile['role']}**:")
    for i, tip in enumerate(tips, 1):
        st.markdown(f"**{i}.** {tip}")

    st.divider()
    if st.button("Start mock interview →", type="primary"):
        with st.spinner("Generating interview questions…"):
            questions = _safe_run(agent.run_interview_questions, profile, tools_module)
        if questions:
            st.session_state["questions"] = questions
            st.session_state["answers"]   = [""] * len(questions)
            st.session_state["state"]     = "interview"
            st.rerun()


def page_interview():
    st.subheader("🎤 Mock Interview")
    profile    = st.session_state["profile"]
    questions  = st.session_state["questions"] or []

    st.write(
        f"Answer these 5 interview questions for **{profile['role']}**. "
        "Be as detailed as you would in a real interview."
    )

    answers: list[str] = []
    with st.form("interview_form"):
        for i, q in enumerate(questions):
            st.markdown(f"**Q{i+1}.** {q}")
            ans = st.text_area(
                f"Your answer to Q{i+1}",
                key=f"ans_{i}",
                height=100,
                label_visibility="collapsed",
            )
            answers.append(ans)
            st.markdown("")
        submitted = st.form_submit_button("Submit answers →", type="primary")

    if submitted:
        if any(not a.strip() for a in answers):
            st.warning("Please answer all questions before submitting.")
            return
        st.session_state["answers"] = answers

        with st.spinner("Scoring your answers…"):
            scores = _safe_run(
                agent.run_score_answers,
                profile,
                questions,
                answers,
                tools_module,
                db,
                st.session_state["student_id"],
            )
        if scores:
            st.session_state["scores"] = scores
            st.session_state["state"]  = "interview_results"
            st.rerun()


def page_interview_results():
    st.subheader("📊 Interview Results")
    scores   = st.session_state["scores"] or []
    profile  = st.session_state["profile"]

    total    = sum(s["score"] for s in scores)
    avg      = total / len(scores) if scores else 0
    max_possible = len(scores) * 5

    col1, col2, col3 = st.columns(3)
    col1.metric("Total score", f"{total} / {max_possible}")
    col2.metric("Average", f"{avg:.1f} / 5")
    grade = "🟢 Strong" if avg >= 4 else "🟡 Good" if avg >= 3 else "🔴 Needs work"
    col3.metric("Overall", grade)

    st.divider()

    for i, s in enumerate(scores, 1):
        stars = "⭐" * s["score"] + "☆" * (5 - s["score"])
        with st.expander(f"Q{i} · Score {s['score']}/5 {stars}", expanded=(s["score"] < 3)):
            st.markdown(f"**Question:** {s['question']}")
            st.markdown(f"**Your answer:** {s['answer']}")
            st.info(f"**Feedback:** {s['feedback']}")

    st.divider()
    if st.button("View my progress →", type="primary"):
        st.session_state["state"] = "progress"
        st.rerun()


def page_progress():
    st.subheader("📈 Progress Tracker")
    student_id = st.session_state["student_id"]
    profile    = st.session_state["profile"]
    roadmap    = st.session_state["roadmap"] or db.load_roadmap(student_id) or []

    progress_rows = db.load_progress(student_id)
    prog = tools_module.progress_tool(progress_rows, roadmap)

    completed = set(prog["completed_weeks"])
    total     = prog["total_weeks"]
    pct       = prog["pct"]

    st.metric("Overall progress", f"{pct}%", f"{len(completed)} of {total} weeks done")
    st.progress(pct / 100.0)

    # Week-by-week checklist
    if roadmap:
        st.markdown("### Mark completed weeks")
        for week in roadmap:
            w = week.get("week")
            focus = week.get("focus", "")
            done = w in completed
            label = f"Week {w} — {focus}"
            if st.checkbox(label, value=done, key=f"week_{w}"):
                if w not in completed:
                    db.mark_week_complete(student_id, w)
                    st.rerun()

    st.divider()

    # Interview scores summary
    scores_db = db.load_interview_scores(student_id)
    if scores_db:
        st.markdown("### 🎤 Interview history")
        avg = sum(s["score"] for s in scores_db) / len(scores_db)
        st.metric("Average interview score", f"{avg:.1f} / 5")

    st.divider()

    # Nudge section
    st.markdown("### 💬 Motivational nudge")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Get a personalised nudge"):
            with st.spinner("Generating nudge…"):
                msg = _safe_run(
                    agent.run_nudge, profile, student_id, tools_module, db
                )
            if msg:
                st.session_state["nudge_message"] = msg
                st.rerun()

    with col2:
        if st.button("⏩ Simulate 3 days of inactivity"):
            # Backdate last progress entry by inserting a fake old record
            past_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            with db._conn() as con:
                con.execute(
                    "INSERT INTO progress (student_id, week, completed, recorded_at) VALUES (?, ?, 0, ?)",
                    (student_id, 0, past_date),
                )
            st.success("Simulated 3 days of inactivity. Click 'Get a personalised nudge'.")

    if st.session_state["nudge_message"]:
        st.info(st.session_state["nudge_message"])

    # Recent nudge history
    nudges = db.load_nudges(student_id)
    if nudges:
        with st.expander("Recent nudge history"):
            for n in nudges:
                st.caption(n["sent_at"])
                st.write(n["message"])
                st.markdown("---")

    st.divider()
    # Navigation back to any section
    st.markdown("### ↩️ Revisit a section")
    dest = st.selectbox(
        "Jump to",
        options=["skill_gap", "roadmap", "resources", "resume", "interview"],
        format_func=lambda x: {
            "skill_gap":  "2 · Skill Gap",
            "roadmap":    "3 · Roadmap",
            "resources":  "4 · Resources",
            "resume":     "5 · Resume Tips",
            "interview":  "6 · Mock Interview",
        }[x],
    )
    if st.button("Go →"):
        st.session_state["state"] = dest
        st.rerun()


# ── Router ────────────────────────────────────────────────────────────────────

_PAGES = {
    "profile":            page_profile,
    "skill_gap":          page_skill_gap,
    "roadmap":            page_roadmap,
    "resources":          page_resources,
    "resume":             page_resume,
    "interview":          page_interview,
    "interview_results":  page_interview_results,
    "progress":           page_progress,
}


def main():
    _show_header()
    _show_progress_bar()
    st.divider()
    _show_error()

    state = st.session_state["state"]
    page_fn = _PAGES.get(state, page_profile)
    page_fn()


if __name__ == "__main__":
    main()

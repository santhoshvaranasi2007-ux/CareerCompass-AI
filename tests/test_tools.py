"""
tests/test_tools.py — Unit tests for AI Career Advisor.

Covers:
  1. JSON parsing (fenced, object-wrapped, bare list)
  2. Full state-machine flow in order
  3. Score and progress saving to DB
  4. Three sample inputs with expected behaviour

All LLM calls and DuckDuckGo searches are MOCKED — no real API calls are made.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

# ── Make project root importable ──────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db as db_module
from llm import parse_json_response


# ── 1. JSON parsing tests ──────────────────────────────────────────────────────

class TestParseJsonResponse(unittest.TestCase):
    """parse_json_response must handle fenced, object-wrapped, and bare lists."""

    def test_plain_object(self):
        text = '{"skills": ["Python", "SQL"]}'
        result = parse_json_response(text)
        self.assertEqual(result["skills"], ["Python", "SQL"])

    def test_fenced_json(self):
        text = '```json\n{"questions": ["Q1", "Q2"]}\n```'
        result = parse_json_response(text)
        self.assertEqual(result["questions"], ["Q1", "Q2"])

    def test_fenced_no_lang(self):
        text = "```\n{\"score\": 4, \"feedback\": \"Good answer\"}\n```"
        result = parse_json_response(text)
        self.assertEqual(result["score"], 4)

    def test_bare_array_wrapped(self):
        """A bare JSON array must be wrapped under key 'items'."""
        text = '["Python", "SQL", "Docker"]'
        result = parse_json_response(text)
        self.assertIn("items", result)
        self.assertEqual(result["items"], ["Python", "SQL", "Docker"])

    def test_object_wrapped_array(self):
        """An object containing a list should pass through unchanged."""
        text = '{"roadmap": [{"week": 1, "focus": "Python basics", "tasks": ["a", "b", "c"]}]}'
        result = parse_json_response(text)
        self.assertIsInstance(result["roadmap"], list)
        self.assertEqual(result["roadmap"][0]["week"], 1)

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_json_response("this is not json")

    def test_fenced_mixed_case(self):
        text = "```JSON\n{\"tips\": [\"Use action verbs.\"]}\n```"
        result = parse_json_response(text)
        self.assertEqual(result["tips"], ["Use action verbs."])


# ── 2. DB persistence tests ────────────────────────────────────────────────────

class TestDatabase(unittest.TestCase):
    """Test DB CRUD with a temporary SQLite file."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        db_module.DB_PATH = self.tmp.name
        db_module.init_db()
        self.sid = "test-student-001"

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_save_and_load_profile(self):
        db_module.save_profile(self.sid, "Data Scientist", ["Python", "SQL"], "2025-12-31")
        profile = db_module.load_profile(self.sid)
        self.assertIsNotNone(profile)
        self.assertEqual(profile["role"], "Data Scientist")
        self.assertIn("Python", profile["skills"])
        self.assertEqual(profile["deadline"], "2025-12-31")

    def test_save_and_load_roadmap(self):
        roadmap = [{"week": 1, "focus": "Python basics", "tasks": ["a", "b", "c"]}]
        db_module.save_roadmap(self.sid, roadmap)
        loaded = db_module.load_roadmap(self.sid)
        self.assertEqual(loaded[0]["week"], 1)
        self.assertEqual(loaded[0]["focus"], "Python basics")

    def test_mark_and_load_progress(self):
        db_module.mark_week_complete(self.sid, 1)
        db_module.mark_week_complete(self.sid, 2)
        rows = db_module.load_progress(self.sid)
        weeks_done = [r["week"] for r in rows if r["completed"]]
        self.assertIn(1, weeks_done)
        self.assertIn(2, weeks_done)

    def test_save_and_load_interview_score(self):
        db_module.save_interview_score(
            self.sid, "What is a decorator?", "A function that wraps another.", 4, "Good."
        )
        scores = db_module.load_interview_scores(self.sid)
        self.assertEqual(len(scores), 1)
        self.assertEqual(scores[0]["score"], 4)
        self.assertEqual(scores[0]["feedback"], "Good.")

    def test_save_and_load_nudge(self):
        db_module.save_nudge(self.sid, "Keep going! Focus on Docker next.")
        nudges = db_module.load_nudges(self.sid)
        self.assertEqual(nudges[0]["message"], "Keep going! Focus on Docker next.")

    def test_profile_upsert(self):
        """Saving the same student_id twice should update, not duplicate."""
        db_module.save_profile(self.sid, "Engineer", ["Python"], "2025-06-01")
        db_module.save_profile(self.sid, "Architect", ["Python", "AWS"], "2025-12-31")
        profile = db_module.load_profile(self.sid)
        self.assertEqual(profile["role"], "Architect")
        self.assertIn("AWS", profile["skills"])


# ── 3. Tools with mocked LLM ──────────────────────────────────────────────────

class TestSkillGapTool(unittest.TestCase):

    @patch("tools.call_llm")
    def test_skill_gap_returns_correct_keys(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "required": ["Python", "SQL", "Machine Learning", "Docker", "Git",
                         "Statistics", "Pandas", "Scikit-learn", "Tableau", "Communication"],
            "missing":  ["Machine Learning", "Docker", "Statistics", "Scikit-learn"],
            "present":  ["Python", "SQL", "Git", "Pandas"],
        })
        import tools
        result = tools.skill_gap_tool("Data Scientist", ["Python", "SQL", "Git", "Pandas"])
        self.assertIn("required", result)
        self.assertIn("missing", result)
        self.assertIn("present", result)
        self.assertIn("Machine Learning", result["missing"])
        self.assertIn("Python", result["present"])

    @patch("tools.call_llm")
    def test_skill_gap_handles_fenced_response(self, mock_llm):
        """The tool must handle a fenced JSON response from the LLM."""
        mock_llm.return_value = (
            "```json\n"
            '{"required": ["Python"], "missing": ["Python"], "present": []}\n'
            "```"
        )
        import tools
        result = tools.skill_gap_tool("Engineer", [])
        self.assertEqual(result["missing"], ["Python"])


class TestRoadmapTool(unittest.TestCase):

    @patch("tools.call_llm")
    def test_roadmap_returns_list(self, mock_llm):
        roadmap_data = [
            {"week": i, "focus": f"Topic {i}", "tasks": ["task a", "task b", "task c"]}
            for i in range(1, 5)
        ]
        mock_llm.return_value = json.dumps({"roadmap": roadmap_data})
        import tools
        deadline = (date.today() + timedelta(weeks=4)).isoformat()
        result = tools.roadmap_tool("Data Scientist", ["ML", "Docker"], deadline)
        self.assertIsInstance(result, list)
        self.assertEqual(result[0]["week"], 1)
        self.assertEqual(len(result[0]["tasks"]), 3)

    @patch("tools.call_llm")
    def test_roadmap_bare_array_response(self, mock_llm):
        """roadmap_tool must handle a response where LLM returns bare array wrapped in 'items'."""
        roadmap_data = [
            {"week": 1, "focus": "Python", "tasks": ["a", "b", "c"]}
        ]
        # parse_json_response wraps bare arrays under "items"
        mock_llm.return_value = json.dumps({"items": roadmap_data})
        import tools
        deadline = (date.today() + timedelta(weeks=4)).isoformat()
        result = tools.roadmap_tool("Engineer", ["Python"], deadline)
        self.assertEqual(result[0]["focus"], "Python")


class TestResumeTipsTool(unittest.TestCase):

    @patch("tools.call_llm")
    def test_resume_tips_returns_5(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "tips": [
                "Quantify achievements with numbers.",
                "Use action verbs at the start.",
                "Tailor your resume to each job.",
                "List relevant projects with outcomes.",
                "Keep to one page for junior roles.",
            ]
        })
        import tools
        tips = tools.resume_tips_tool("Data Scientist", ["ML", "Docker"])
        self.assertEqual(len(tips), 5)
        self.assertIn("Quantify achievements with numbers.", tips)

    @patch("tools.call_llm")
    def test_resume_tips_truncates_to_5(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "tips": [f"Tip {i}" for i in range(10)]
        })
        import tools
        tips = tools.resume_tips_tool("Engineer", [])
        self.assertLessEqual(len(tips), 5)


class TestMockInterviewTool(unittest.TestCase):

    @patch("tools.call_llm")
    def test_questions_returns_5(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "questions": [
                "Explain a REST API.",
                "What is a primary key?",
                "Describe your biggest project.",
                "How do you handle deadlines?",
                "What is Docker used for?",
            ]
        })
        import tools
        qs = tools.mock_interview_questions_tool("Backend Engineer")
        self.assertEqual(len(qs), 5)

    @patch("tools.call_llm")
    def test_score_clamps_to_1_5(self, mock_llm):
        """Score must be clamped to [1, 5] even if LLM returns out-of-range value."""
        mock_llm.return_value = json.dumps({"score": 7, "feedback": "Too high."})
        import tools
        result = tools.mock_interview_score_tool("Engineer", "Q?", "My answer.")
        self.assertEqual(result["score"], 5)

    @patch("tools.call_llm")
    def test_score_low_clamp(self, mock_llm):
        mock_llm.return_value = json.dumps({"score": -1, "feedback": "Too low."})
        import tools
        result = tools.mock_interview_score_tool("Engineer", "Q?", "My answer.")
        self.assertEqual(result["score"], 1)


# ── 4. State machine flow tests ────────────────────────────────────────────────

class TestStateMachine(unittest.TestCase):
    """Verify the happy-path transition order of the state machine."""

    def test_full_state_order(self):
        import agent
        order = [
            "profile",
            "skill_gap",
            "roadmap",
            "resources",
            "resume",
            "interview",
            "interview_results",
            "progress",
        ]
        for i in range(len(order) - 1):
            expected_next = order[i + 1]
            actual_next = agent.next_state(order[i])
            self.assertEqual(
                actual_next,
                expected_next,
                f"next_state('{order[i]}') should be '{expected_next}', got '{actual_next}'",
            )

    def test_terminal_state_stays(self):
        import agent
        self.assertEqual(agent.next_state("progress"), "progress")

    def test_unknown_state_returns_profile(self):
        import agent
        self.assertEqual(agent.next_state("nonexistent"), "profile")

    @patch("tools.call_llm")
    def test_run_skill_gap_integration(self, mock_llm):
        """Agent.run_skill_gap should call tool and return expected structure."""
        mock_llm.return_value = json.dumps({
            "required": ["Python", "ML"],
            "missing":  ["ML"],
            "present":  ["Python"],
        })
        import agent, tools
        profile = {"role": "Data Scientist", "skills": ["Python"], "deadline": "2025-12-31"}
        result = agent.run_skill_gap(profile, tools)
        self.assertIn("missing", result)
        self.assertEqual(result["missing"], ["ML"])

    @patch("tools.call_llm")
    def test_run_score_answers_persists(self, mock_llm):
        """run_score_answers should persist scores to DB."""
        mock_llm.return_value = json.dumps({"score": 4, "feedback": "Well done."})
        import agent, tools

        # Use a fresh temp DB
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        db_module.DB_PATH = tmp.name
        db_module.init_db()

        try:
            profile = {"role": "Engineer", "skills": [], "deadline": "2025-12-31"}
            scores = agent.run_score_answers(
                profile,
                ["What is REST?"],
                ["Representational State Transfer."],
                tools,
                db_module,
                "student-abc",
            )
            self.assertEqual(len(scores), 1)
            self.assertEqual(scores[0]["score"], 4)

            # Verify it was actually persisted
            saved = db_module.load_interview_scores("student-abc")
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["score"], 4)
        finally:
            os.unlink(tmp.name)


# ── 5. Progress tool tests ─────────────────────────────────────────────────────

class TestProgressTool(unittest.TestCase):

    def test_progress_empty(self):
        import tools
        result = tools.progress_tool([], [{"week": 1}, {"week": 2}])
        self.assertEqual(result["pct"], 0.0)
        self.assertEqual(result["total_weeks"], 2)
        self.assertEqual(result["completed_weeks"], [])

    def test_progress_partial(self):
        import tools
        rows = [{"week": 1, "completed": 1}, {"week": 2, "completed": 1}]
        roadmap = [{"week": i} for i in range(1, 5)]
        result = tools.progress_tool(rows, roadmap)
        self.assertEqual(result["pct"], 50.0)
        self.assertIn(1, result["completed_weeks"])

    def test_progress_complete(self):
        import tools
        rows = [{"week": i, "completed": 1} for i in range(1, 5)]
        roadmap = [{"week": i} for i in range(1, 5)]
        result = tools.progress_tool(rows, roadmap)
        self.assertEqual(result["pct"], 100.0)


# ── 6. Sample inputs with expected behaviour ──────────────────────────────────

class TestSampleInputs(unittest.TestCase):
    """
    Three representative scenarios:
      A) Junior Python dev → Data Scientist
      B) Complete beginner → Frontend Engineer
      C) Experienced dev → DevOps Engineer (all skills present)
    """

    @patch("tools.call_llm")
    def test_scenario_A_junior_to_data_scientist(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "required": ["Python", "SQL", "ML", "Statistics", "Pandas",
                         "Scikit-learn", "Docker", "Git", "Tableau", "Communication"],
            "missing": ["ML", "Statistics", "Scikit-learn", "Docker", "Tableau"],
            "present": ["Python", "SQL", "Pandas", "Git", "Communication"],
        })
        import tools
        result = tools.skill_gap_tool("Data Scientist", ["Python", "SQL", "Pandas", "Git", "Communication"])
        self.assertEqual(len(result["present"]), 5)
        self.assertIn("ML", result["missing"])
        # Missing skills are ranked — ML should be first
        self.assertEqual(result["missing"][0], "ML")

    @patch("tools.call_llm")
    def test_scenario_B_beginner_frontend(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "required": ["HTML", "CSS", "JavaScript", "React", "TypeScript",
                         "Git", "REST APIs", "Testing", "Accessibility", "Performance"],
            "missing": ["HTML", "CSS", "JavaScript", "React", "TypeScript",
                        "Git", "REST APIs", "Testing", "Accessibility", "Performance"],
            "present": [],
        })
        import tools
        result = tools.skill_gap_tool("Frontend Engineer", [])
        self.assertEqual(len(result["present"]), 0)
        self.assertEqual(len(result["missing"]), 10)

    @patch("tools.call_llm")
    def test_scenario_C_experienced_devops(self, mock_llm):
        mock_llm.return_value = json.dumps({
            "required": ["Docker", "Kubernetes", "CI/CD", "Terraform", "AWS",
                         "Linux", "Python", "Monitoring", "Security", "Git"],
            "missing": [],
            "present": ["Docker", "Kubernetes", "CI/CD", "Terraform", "AWS",
                        "Linux", "Python", "Monitoring", "Security", "Git"],
        })
        import tools
        all_skills = ["Docker", "Kubernetes", "CI/CD", "Terraform", "AWS",
                      "Linux", "Python", "Monitoring", "Security", "Git"]
        result = tools.skill_gap_tool("DevOps Engineer", all_skills)
        self.assertEqual(result["missing"], [])
        self.assertEqual(len(result["present"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)

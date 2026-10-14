# 🎯 AI Career Advisor

A demo-ready, AI-powered career coaching app built with Python, Streamlit, SQLite, and Groq (or Gemini).

> ⚠️ **Disclaimer:** AI-generated advice may contain errors. Verify all information with official sources before making career decisions.

---

## Features

| Stage | What it does |
|---|---|
| **Profile** | Collect target role, current skills, and deadline |
| **Skill Gap** | LLM ranks the most important missing skills |
| **Roadmap** | Week-by-week learning plan up to your deadline |
| **Resources** | Real, verified links from DuckDuckGo (no invented URLs) |
| **Resume Tips** | 5 role-specific, actionable tips |
| **Mock Interview** | 5 questions, scored 1–5 with feedback |
| **Progress** | SQLite-backed tracker + motivational nudge |

---

## Quick Start (Windows PowerShell)

### 1. Install dependencies

```powershell
pip install -r requirements.txt
```

### 2. Configure your API key

```powershell
Copy-Item .env.example .env
notepad .env   # fill in GROQ_API_KEY (or GEMINI_API_KEY)
```

### 3. Run the app

```powershell
python -m streamlit run app.py
```

The app opens at **http://localhost:8501** in your browser.

---

## Environment Variables (`.env`)

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | No | `groq` | `groq` or `gemini` |
| `GROQ_API_KEY` | If using Groq | — | From https://console.groq.com/keys |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Model name (see below) |
| `GEMINI_API_KEY` | If using Gemini | — | From https://aistudio.google.com/app/apikey |
| `GEMINI_MODEL` | No | `gemini-1.5-flash` | Model name (see below) |
| `DB_PATH` | No | `career_advisor.db` | SQLite file path |

---

## How to list available models for your API key

### Groq

```powershell
python -c "
from groq import Groq; import os; from dotenv import load_dotenv
load_dotenv()
c = Groq(api_key=os.environ['GROQ_API_KEY'])
for m in sorted(c.models.list().data, key=lambda x: x.id):
    print(m.id)
"
```

Copy the model ID you want and paste it as `GROQ_MODEL=<id>` in `.env`.

### Gemini

```powershell
python -c "
import google.generativeai as g; import os; from dotenv import load_dotenv
load_dotenv()
g.configure(api_key=os.environ['GEMINI_API_KEY'])
for m in g.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)
"
```

Copy the model name (e.g. `models/gemini-1.5-pro`) and paste it as `GEMINI_MODEL=<name>` in `.env`.

---

## Run Tests

```powershell
python -m pytest tests/ -v
```

All tests mock the LLM and DuckDuckGo — no API keys needed to run tests.

### Test coverage

| Suite | What is tested |
|---|---|
| `TestParseJsonResponse` | JSON parsing: plain object, fenced, bare array, invalid |
| `TestDatabase` | All DB CRUD operations with a temp SQLite file |
| `TestSkillGapTool` | Skill gap logic, fenced response handling |
| `TestRoadmapTool` | Roadmap list output, bare-array response |
| `TestResumeTipsTool` | 5 tips returned, truncation to 5 |
| `TestMockInterviewTool` | 5 questions, score clamping (1–5) |
| `TestStateMachine` | Full 8-step transition order, terminal state, unknown state |
| `TestProgressTool` | Empty / partial / complete progress |
| `TestSampleInputs` | 3 scenarios: junior dev, beginner, experienced dev |

---

## Architecture

```
app.py          Streamlit UI — one page per state
agent.py        State machine — transitions + orchestration calls
tools.py        8 tools: skill_gap, roadmap, resources, resume, interview ×2, progress, nudge
llm.py          Single call_llm() function; provider/model from .env; retry ×2
db.py           SQLite persistence — profiles, roadmaps, progress, scores, nudges
```

### State machine

```
profile ──> skill_gap ──> roadmap ──> resources ──> resume ──> interview ──> interview_results ──> progress
```

Each `st.session_state["state"]` value is the **current page to show**. After an action completes the state is set to the next page, then `st.rerun()` is called — this prevents double-execution on Streamlit reruns.

### LLM contract

- All JSON responses are **objects** (never bare arrays).
- The parser strips markdown fences before parsing.
- Bare arrays from the LLM are wrapped under `{"items": [...]}`.
- Max output tokens: **8192**.
- Retries: **2**, with a 2-second delay between attempts.

### Privacy

- No personal data is ever sent to the LLM.
- Users are identified by an anonymous UUID in `st.session_state`.

---

## File layout

```
.
├── app.py
├── agent.py
├── tools.py
├── llm.py
├── db.py
├── requirements.txt
├── .env.example
├── README.md
└── tests/
    ├── __init__.py
    └── test_tools.py
```

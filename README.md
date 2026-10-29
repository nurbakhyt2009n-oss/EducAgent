# EducaAgent

A local AI tutor that prepares NIS students for summative assessments (SAU for a unit,
SAT for a term). It builds a knowledge base from your own slides, textbooks and
learning objectives (LO), teaches through Socratic dialogue, grades answers against
assessment descriptors and remembers your mistakes, so every next session starts with
your weakest topics. Runs for free on your own computer via [Ollama](https://ollama.com).

Full architecture (in Russian): [docs/architecture.md](docs/architecture.md).

## How it works

```text
Materials (PPTX, PDF, LO) ──► Ingestion ──► knowledge base (SQLite + ChromaDB)
                                                   │
             ┌─────────────────────────────────────┘
             ▼
   Knowledge Gap Graph ──► session plan ──► Tutor Engine (dialogue, tasks, hints)
             ▲                                     │
             └──── Evaluation Loop: grading ◄──────┘
                   → error diagnosis → memory
```

Four layers: **Ingestion** builds the knowledge base, **Memory** stores mistakes and
the learner model, **Tutor Engine** runs the dialogue, **Evaluation Loop** grades
answers and updates memory. Numbers and formulas are checked by code (SymPy), not by
the language model.

## Status

| Stage | What it adds | Status |
| --- | --- | --- |
| 0. Skeleton | config, domain, SQLite + Alembic, LLM clients (Ollama and Claude), CLI | ✅ done |
| 1. Ingestion | PPTX, PDF and LO loaders; chunking; linking chunks to LO | 🚧 in progress |
| 2. Evaluation | graders, error diagnosis, mistake log | ⏳ |
| 3. Tutor Engine | LangGraph flow, explanations, hints, task generation | ⏳ |
| 4. Self-Evolution | learner model, Knowledge Gap Graph, session planner | ⏳ |
| 5. Exam and dashboard | SAT simulation, Streamlit dashboard | ⏳ |
| 6. Calibration | tuning task difficulty from real attempts | ⏳ |

## Installation (Windows)

You need Python 3.12+ and Git. On Windows, run Python with the `py` command.

```powershell
git clone https://github.com/nurbakhyt2009n-oss/EducAgent.git
cd EducAgent
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[ingestion,dev]"
```

If PowerShell refuses to run `Activate.ps1`, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Packages for later stages (ChromaDB, torch, LangGraph and others) are installed later:
`python -m pip install -e ".[all,dev]"`.

## Language model: free or Claude

The provider is a single line, `llm.provider`, in [config/settings.yaml](config/settings.yaml).

| `provider` | Cost | What you need |
| --- | --- | --- |
| `ollama` (default) | free, works offline | install [Ollama](https://ollama.com/download) and pull a model |
| `anthropic` | paid, per token | an API key in `.env` |

For Ollama, pull the model after installing (about 2.5 GB):

```powershell
ollama pull qwen3:4b
```

`qwen3:4b` fits entirely into 4 GB of video memory. With 8 GB or more, try `qwen3:8b`,
which is smarter. Change the model in `llm.ollama.tutor_model`.

For Claude, copy `.env.example` to `.env` and put your key there (it starts with
`sk-ant-`). `.env` is never committed. Never put a key into `.env.example`.

## First run

```powershell
educa init                  # creates data/ and the database
educa doctor                # checks that everything is set up
```

Then put your materials into `data/raw/`:

| Folder | What goes there |
| --- | --- |
| `presentations/` | teacher's slides, `*.pptx` |
| `textbooks/` | textbooks, `*.pdf` |
| `web/` | saved web pages with theory, `*.html` (any folder name works) |
| `objectives/` | learning objective lists: `*.xlsx`, `*.csv`, `*.docx`, `*.pdf`, `*.html` |
| `past_papers/` | sample SAU/SAT papers (optional) |

Then load them, for example for Grade 12 Computer Science:

```powershell
educa ingest -s computer_science_12
```

### Materials from bzfar.org

[bzfar.org](https://www.bzfar.org) has NIS Computer Science lessons with learning
objectives. Open a page in your browser, press **Ctrl+S**, choose
**"Web page, HTML only"** and save it:

- the course page (for example *CS. Grade 12*) → `data/raw/objectives/`;
- lesson pages (*Theory & Exercises*) → `data/raw/web/`.

Lesson pages start with their learning objective codes, so each lesson is linked to its
objectives automatically.

The dialogue language and SAT dates are set in the subject file, for example
[config/subjects/physics_10.yaml](config/subjects/physics_10.yaml).

## Commands

| Command | What it does |
| --- | --- |
| `educa init` | Creates the `data/` folders and applies database migrations |
| `educa doctor` | Checks the environment and settings, changes nothing |
| `educa config` | Shows the main settings |
| `educa ingest -s computer_science_12` | Loads materials into the knowledge base; unchanged files are skipped |
| `educa ingest -s computer_science_12 --force` | Re-processes every file (after a loader update) |
| `educa plan --subject physics_10` | Builds a session plan (stage 4) |
| `educa study` | Study session with the tutor (stage 3) |
| `educa exam --kind soch --quarter 2` | Mock SAT (stage 5) |
| `educa report` | Progress report (stage 4) |

## Development

```powershell
pytest                      # tests
ruff check src tests        # linter
mypy src                    # type checking
```

The database schema changes only through migrations:

```powershell
alembic revision --autogenerate -m "what changed"
alembic upgrade head
```

## Project layout

```text
config/            settings: models and thresholds, NIS rules, error taxonomy, subjects, prompts
docs/              system architecture
src/educa_agent/
  domain/          domain models (Pydantic), no I/O
  llm/             common LLM interface, Ollama and Claude clients, prompts
  memory/db/       SQLite tables, repositories, Alembic migrations
  interfaces/      the educa command (CLI)
  utils/           ids, logging, text normalization
tests/             tests
data/              your materials and database, never committed
```

## Privacy

Materials, the database with the student's answers and mistakes, and API keys stay on
your computer only: `data/` and `.env` are excluded from git. With `provider: ollama`,
no request leaves your machine.

# EducaAgent

> A local AI tutor that prepares NIS students for summative assessments (SAU / SAT).
> It builds a knowledge base from your own slides, textbooks and learning objectives,
> teaches through Socratic dialogue, grades answers against descriptors and remembers
> your mistakes, so every next session starts with your weakest topics.
> Runs for free on your own computer via [Ollama](https://ollama.com).

Локальный ИИ-тьютор для подготовки к СОР и СОЧ в НИШ. Строит базу знаний из твоих
презентаций, учебников и списков целей обучения (LO), ведёт сократовский диалог,
проверяет ответы по дескрипторам и запоминает ошибки, чтобы следующая сессия
начиналась с самых слабых мест. Работает бесплатно, на своём компьютере.

Полная архитектура: [docs/architecture.md](docs/architecture.md).

## Как это работает

```text
Материалы (PPTX, PDF, LO) ──► Ingestion ──► база знаний (SQLite + ChromaDB)
                                                   │
             ┌─────────────────────────────────────┘
             ▼
   Knowledge Gap Graph ──► план сессии ──► Tutor Engine (диалог, задачи, подсказки)
             ▲                                     │
             └──── Evaluation Loop: оценка ◄───────┘
                   → диагноз ошибки → память
```

Четыре слоя: **Ingestion** строит базу знаний, **Memory** хранит ошибки и модель
ученика, **Tutor Engine** ведёт диалог, **Evaluation Loop** проверяет ответы и
обновляет память. Числа и формулы проверяет код (SymPy), а не нейросеть.

## Статус

| Этап | Что появляется | Статус |
| --- | --- | --- |
| 0. Каркас | config, domain, SQLite + Alembic, LLM-клиенты (Ollama и Claude), CLI | ✅ готово |
| 1. Ingestion | загрузка PPTX, PDF, LO; чанкинг; привязка к LO | ⏳ |
| 2. Evaluation | оценщики, диагноз ошибок, журнал ошибок | ⏳ |
| 3. Tutor Engine | граф LangGraph, объяснения, подсказки, задачи | ⏳ |
| 4. Self-Evolution | модель ученика, Knowledge Gap Graph, планировщик | ⏳ |
| 5. Экзамен и дашборд | симуляция СОЧ, Streamlit | ⏳ |
| 6. Калибровка | уточнение сложности задач | ⏳ |

## Установка (Windows)

Нужны Python 3.12+ и Git. На Windows Python запускается командой `py`.

```powershell
git clone <ссылка-на-репозиторий>
cd EducaAgent
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Если PowerShell не даёт запустить `Activate.ps1`, выполни один раз
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Пакеты следующих этапов (ChromaDB, torch, LangGraph и другие) ставятся позже:
`python -m pip install -e ".[all,dev]"`.

## Языковая модель: бесплатно или Claude

Поставщик выбирается одной строкой `llm.provider` в [config/settings.yaml](config/settings.yaml).

| `provider` | Цена | Что нужно |
| --- | --- | --- |
| `ollama` (по умолчанию) | бесплатно, работает без интернета | установить [Ollama](https://ollama.com/download) и скачать модель |
| `anthropic` | платно, по токенам | ключ API в `.env` |

Для Ollama после установки скачай модель (около 2,5 ГБ):

```powershell
ollama pull qwen3:4b
```

`qwen3:4b` целиком помещается в 4 ГБ видеопамяти. На видеокарте с 8 ГБ и больше
попробуй `qwen3:8b` — она умнее. Модель меняется в `llm.ollama.tutor_model`.

Для Claude скопируй `.env.example` в `.env` и впиши ключ (начинается с `sk-ant-`).
Файл `.env` в git не попадает — никогда не вписывай ключ в `.env.example`.

## Первый запуск

```powershell
educa init                  # создаёт data/ и базу данных
educa doctor                # проверяет, что всё настроено
```

Потом положи материалы в `data/raw/`:

| Папка | Что класть |
| --- | --- |
| `presentations/` | презентации учителя, `*.pptx` |
| `textbooks/` | учебники, `*.pdf` |
| `objectives/` | списки целей обучения: `*.xlsx`, `*.csv`, `*.docx`, `*.pdf` |
| `past_papers/` | образцы СОР/СОЧ (необязательно) |

Язык диалога и даты СОЧ задаются в файле предмета, например
[config/subjects/physics_10.yaml](config/subjects/physics_10.yaml).

## Команды

| Команда | Что делает |
| --- | --- |
| `educa init` | Создаёт папки `data/` и применяет миграции базы |
| `educa doctor` | Проверяет окружение и настройки, ничего не меняет |
| `educa config` | Показывает основные настройки |
| `educa ingest data/raw` | Загружает материалы (этап 1) |
| `educa plan --subject physics_10` | План сессии (этап 4) |
| `educa study` | Учебная сессия (этап 3) |
| `educa exam --kind soch --quarter 2` | Пробный СОЧ (этап 5) |
| `educa report` | Отчёт о прогрессе (этап 4) |

## Разработка

```powershell
pytest                      # тесты
ruff check src tests        # линтер
mypy src                    # проверка типов
```

Схема базы меняется только через миграции:

```powershell
alembic revision --autogenerate -m "что изменилось"
alembic upgrade head
```

## Где что лежит

```text
config/            настройки: модели и пороги, правила НИШ, таксономия ошибок, предметы, промпты
docs/              архитектура системы
src/educa_agent/
  domain/          модели предметной области (Pydantic), без I/O
  llm/             общий интерфейс LLM, клиенты Ollama и Claude, промпты
  memory/db/       таблицы SQLite, репозитории, миграции Alembic
  interfaces/      команда educa (CLI)
  utils/           id, логирование, нормализация текста
tests/             тесты
data/              твои материалы и база — в git не попадает
```

## Приватность

Материалы, база с ответами и ошибками ученика, ключи API — всё хранится только
локально: `data/` и `.env` исключены из git. С `provider: ollama` ни один запрос
не уходит в интернет.

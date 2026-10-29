# EducaAgent — архитектура системы

Живая версия с диаграммами: https://claude.ai/artifact/6KrUJEXsE4ttJAWY2uRykp

Oct 29, 2026 · @nurbakyt

## Обзор и ключевые решения

EducaAgent — локальный Python-агент из четырёх слоёв: Ingestion строит базу знаний из PPTX, PDF и списков LO; Memory хранит ошибки и модель ученика; Tutor Engine ведёт сократовский диалог; Evaluation Loop проверяет ответы и обновляет память. Перед каждой сессией агент пересчитывает Knowledge Gap Graph и по нему выбирает, какие LO разбирать и какой сложности давать задачи.

| Решение | Выбор | Почему |
| --- | --- | --- |
| Оркестрация диалога | LangGraph StateGraph + SQLite-checkpointer | Явные состояния вместо одного длинного промпта; сессию можно прервать и продолжить |
| LLM | Claude через Anthropic SDK: `claude-sonnet-5-5` для тьютора, `claude-haiku-5-5` для разметки и классификации | Сильная модель там, где важно качество объяснений; дешёвая — на массовых операциях |
| Векторная память | ChromaDB (PersistentClient), 5 коллекций | Поиск похожих ошибок, контента по LO и задач из банка |
| Источник истины | SQLite + SQLAlchemy | Баллы и попытки — строгие данные; Chroma служит индексом смысла, а не журналом |
| Эмбеддинги | BAAI/bge-m3 локально через sentence-transformers | Русский, казахский и английский в одном пространстве — под трёхъязычие НИШ |
| Модель ученика | Способность θ по каждому LO (Elo / 1PL IRT) + FSRS для забывания | θ задаёт сложность задачи, FSRS — когда повторять |
| Граф слабых мест | NetworkX DiGraph | Пререквизиты, ошибки и приоритеты в одной структуре |
| Интерфейс | CLI (Typer + Rich), дашборд Streamlit | MVP без фронтенда; граф и прогресс видно в браузере |

Принципы, которые держат всю систему:

- **Двойная запись.** Каждая ошибка пишется в SQLite (факт: балл, время, LO) и в ChromaDB (смысл: текст ошибки и диагноз). Граф всегда можно пересобрать из SQLite с нуля.
- **Grounding.** Теория берётся только из загруженных материалов, со ссылкой на слайд или страницу. Если LO не покрыт материалами, агент говорит об этом прямо.
- **Жёсткий режим.** Ответ не раскрывается до попытки ученика, подсказки идут по лестнице из трёх ступеней. В режиме симуляции СОЧ подсказок нет, есть таймер.
- **Детерминированное — без LLM.** Тесты, числа и формулы проверяются кодом (SymPy); LLM оценивает только развёрнутые ответы по дескрипторам.
- **Самоэволюция в два контура.** Быстрый — θ и FSRS обновляются после каждой попытки. Медленный — перед сессией ошибки кластеризуются в устойчивые misconceptions, граф пересчитывается, а рефлексия прошлой сессии корректирует стиль объяснений.

## Файловое дерево проекта

Пакет `educa_agent` разбит по слоям: `domain` не зависит ни от чего, `memory` и `llm` — инфраструктура, `ingestion`, `tutor`, `evaluation` и `planner` — сценарии. Промпты вынесены в Jinja2-шаблоны, правила НИШ — в YAML, чтобы менять их без правки кода.

```text
educa-agent/
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── .env.example                  # ANTHROPIC_API_KEY, пути к данным
├── Makefile                      # ingest / graph / tutor / eval / test
├── README.md
│
├── config/
│   ├── settings.yaml             # модели, пороги, веса формулы приоритета
│   ├── nis_assessment.yaml       # уровни мыслительных навыков, форматы СОР/СОЧ
│   ├── error_taxonomy.yaml       # типы ошибок и их веса
│   ├── subjects/                 # по предмету: язык, дата СОЧ, веса разделов
│   │   └── physics_10.yaml
│   └── prompts/                  # Jinja2-шаблоны
│       ├── tutor_system.j2
│       ├── explain.j2
│       ├── socratic_probe.j2
│       ├── remediate.j2
│       ├── hint_ladder.j2
│       ├── item_generate_sor.j2
│       ├── item_generate_soch.j2
│       ├── item_validate.j2
│       ├── grade_rubric.j2
│       ├── diagnose_error.j2
│       ├── lo_tagging.j2
│       ├── prerequisite_infer.j2
│       └── session_reflection.j2
│
├── data/                         # в .gitignore
│   ├── raw/
│   │   ├── presentations/        # *.pptx
│   │   ├── textbooks/            # *.pdf
│   │   ├── objectives/           # LO: *.xlsx / *.csv / *.docx / *.pdf
│   │   └── past_papers/          # образцы СОР/СОЧ (необязательно)
│   ├── processed/                # markdown + JSON чанков, манифест
│   ├── chroma/                   # persist-директория ChromaDB
│   ├── educa.db                  # SQLite: LO, попытки, мастерство
│   ├── checkpoints.db            # LangGraph checkpointer
│   └── reports/                  # отчёты сессий, снимки графа
│
├── src/educa_agent/
│   ├── __init__.py
│   ├── __main__.py               # python -m educa_agent → CLI
│   ├── config.py                 # pydantic-settings + загрузка YAML
│   ├── container.py              # сборка зависимостей (DI)
│   │
│   ├── domain/                   # чистые модели, без I/O
│   │   ├── models.py             # LO, Chunk, Item, Attempt, Mistake, Misconception
│   │   ├── enums.py              # ThinkingLevel, ErrorType, AssessmentKind
│   │   └── events.py             # AttemptGraded, MistakeLogged, SessionClosed
│   │
│   ├── llm/
│   │   ├── client.py             # Anthropic: ретраи, prompt caching, бюджет
│   │   ├── structured.py         # ответ строго по Pydantic-схеме
│   │   └── prompts.py            # рендер Jinja2
│   │
│   ├── ingestion/
│   │   ├── pipeline.py           # оркестратор: файл → чанки → индекс
│   │   ├── manifest.py           # хеши файлов, инкрементальный реиндекс
│   │   ├── loaders/
│   │   │   ├── base.py           # интерфейс DocumentLoader
│   │   │   ├── pptx_loader.py    # слайды, заметки, таблицы
│   │   │   ├── pdf_loader.py     # текст, страницы, оглавление
│   │   │   ├── vision.py         # OCR / Claude vision для сканов и схем
│   │   │   └── lo_loader.py      # парсинг кодов вида 10.2.1.3
│   │   ├── normalize.py          # чистка, формулы, определение языка
│   │   ├── chunker.py            # по структуре: слайд, раздел, абзац
│   │   ├── lo_tagger.py          # чанк ↔ LO: эмбеддинги + LLM-подтверждение
│   │   ├── prereq_builder.py     # рёбра «LO A нужен для LO B»
│   │   └── past_papers.py        # разбор образцов СОР/СОЧ в эталоны стиля
│   │
│   ├── memory/
│   │   ├── embeddings.py         # bge-m3, батчи, кеш
│   │   ├── vector_store.py       # ChromaDB: 5 коллекций
│   │   ├── db/
│   │   │   ├── tables.py         # SQLAlchemy-модели
│   │   │   ├── repositories.py   # LORepo, AttemptRepo, MasteryRepo …
│   │   │   └── migrations/       # Alembic
│   │   ├── mistake_log.py        # двойная запись ошибки
│   │   ├── misconceptions.py     # кластеризация ошибок
│   │   ├── learner_model.py      # θ по LO (Elo) + FSRS-карточки
│   │   ├── gap_graph.py          # Knowledge Gap Graph: сборка и пересчёт
│   │   └── profile.py            # профиль ученика + инсайты тьютора
│   │
│   ├── planner/
│   │   ├── session_planner.py    # граф → план сессии
│   │   └── difficulty.py         # θ → целевая сложность и уровень
│   │
│   ├── items/
│   │   ├── formats.py            # шаблоны СОР/СОЧ, дескрипторы, баллы
│   │   ├── generator.py          # генерация задачи под LO и сложность
│   │   ├── validator.py          # самопроверка, решение SymPy
│   │   └── bank.py               # банк задач, калибровка сложности
│   │
│   ├── tutor/
│   │   ├── state.py              # TutorState (TypedDict)
│   │   ├── graph.py              # LangGraph StateGraph
│   │   ├── retrieval.py          # RAG: теория по LO + похожие ошибки
│   │   ├── policies.py           # «не выдавать ответ», лестница подсказок
│   │   ├── exam_mode.py          # симуляция СОЧ: таймер, без подсказок
│   │   └── nodes/
│   │       ├── load_context.py
│   │       ├── activate_prior.py
│   │       ├── explain.py
│   │       ├── socratic_probe.py
│   │       ├── remediate.py
│   │       ├── practice.py
│   │       ├── hint.py
│   │       ├── decide_next.py
│   │       └── wrap_up.py
│   │
│   ├── evaluation/
│   │   ├── loop.py               # оценка → диагноз → запись → обратная связь
│   │   ├── graders/
│   │   │   ├── deterministic.py  # тест, число с допуском
│   │   │   ├── symbolic.py       # эквивалентность выражений (SymPy)
│   │   │   └── rubric_llm.py     # развёрнутый ответ по дескрипторам
│   │   ├── diagnosis.py          # тип ошибки + misconception
│   │   └── feedback.py           # сократовская обратная связь
│   │
│   ├── interfaces/
│   │   ├── cli.py                # Typer: ingest, plan, study, exam, report
│   │   └── dashboard/
│   │       ├── app.py            # Streamlit
│   │       └── graph_view.py     # визуализация графа (pyvis)
│   │
│   └── utils/
│       ├── logging.py
│       ├── ids.py
│       └── text.py
│
├── evals/                        # качество самого агента
│   ├── datasets/
│   │   ├── grading_golden.jsonl  # ответы с эталонными баллами
│   │   ├── lo_tagging_golden.jsonl
│   │   └── diagnosis_golden.jsonl
│   ├── run_grader_eval.py
│   ├── run_tagging_eval.py
│   └── simulated_student.py      # LLM-ученик с заданными пробелами
│
└── tests/
    ├── conftest.py               # временные Chroma и SQLite
    ├── fixtures/                 # маленькие pptx/pdf/xlsx
    ├── unit/
    │   ├── test_lo_loader.py
    │   ├── test_chunker.py
    │   ├── test_learner_model.py
    │   ├── test_gap_graph.py
    │   └── test_graders.py
    └── integration/
        ├── test_ingestion_pipeline.py
        └── test_tutor_session.py
```

Команды CLI: `educa ingest data/raw`, `educa plan --subject physics_10`, `educa study`, `educa exam --kind soch --quarter 2`, `educa report`.

## requirements.txt

Версии сверены с PyPI на 29 октября 2026; нижняя граница — проверенная версия, верхняя защищает от ломающего мажорного релиза. Python 3.12+.

```text
# ---------- LLM и оркестрация ----------
anthropic>=2.3,<3
langgraph>=1.2,<2
langgraph-checkpoint-sqlite>=3.1,<4

# ---------- Векторная память и эмбеддинги ----------
chromadb>=1.5,<2
sentence-transformers>=6.2,<7    # модель BAAI/bge-m3
torch>=2.15                      # хватит CPU-сборки
rank-bm25>=0.2.2                 # гибридный поиск по терминам и кодам LO

# ---------- Ingestion ----------
python-pptx>=1.0.2,<2
pymupdf>=2.0,<3                  # лицензия AGPL-3.0
pymupdf4llm>=2.0,<3              # PDF → markdown постранично
pytesseract>=0.3.13              # + системный tesseract: rus, kaz, eng
pillow>=13.0
openpyxl>=3.1.5                  # LO из Excel
python-docx>=1.2                 # LO из Word
pandas>=3.1,<4
lingua-language-detector>=2.2    # язык чанка: ru / kk / en
rapidfuzz>=3.14                  # дедупликация чанков и LO

# ---------- Модель ученика, граф, математика ----------
networkx>=3.7,<4
numpy>=2.5,<3
scikit-learn>=1.9,<2             # HDBSCAN для кластеров ошибок
fsrs>=6.3,<7                     # интервальные повторения
sympy>=1.14                      # проверка формул и чисел

# ---------- Данные и конфигурация ----------
pydantic>=2.14,<3
pydantic-settings>=2.16,<3
sqlalchemy>=2.1,<3
alembic>=1.20
pyyaml>=6.0.3
jinja2>=3.1.6
python-dotenv>=1.2
orjson>=3.13

# ---------- Интерфейсы ----------
typer>=0.27
rich>=15.0
streamlit>=1.66
pyvis>=0.3.2                     # интерактивный граф слабых мест
plotly>=7.1                      # графики прогресса

# ---------- Надёжность и логи ----------
tenacity>=9.2
loguru>=0.7.3
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest>=9.2
pytest-asyncio>=1.4
pytest-cov>=7.1
hypothesis>=6.170
ruff>=0.17
mypy>=2.4
```

Системные зависимости: `tesseract-ocr` с языковыми пакетами `rus`, `kaz`, `eng`. Если в учебниках много таблиц и формул, `pymupdf4llm` можно заменить на `docling>=2.144` — он точнее, но тяжелее. Если AGPL у PyMuPDF мешает (например, при публикации как сервиса), та же замена снимает вопрос.

## Схема взаимодействия компонентов

Данные текут сверху вниз один раз при загрузке материалов и по кругу — в каждой учебной сессии. Центр круга — Knowledge Gap Graph: он читает обе базы и решает, чему учить дальше.

&#91;embedded content: архитектура EducaAgent · 4 слоя, 2 контура обратной связи\]

Ошибка из Evaluation Loop пишется дважды: факт — в SQLite, текст с диагнозом — в ChromaDB. Перед следующей сессией граф пересобирается из обеих баз, и планировщик выбирает LO заново.

Жизненный цикл по времени:

1. **Офлайн, при добавлении файлов.** Ingestion наполняет SQLite и ChromaDB и строит рёбра пререквизитов.
2. **Перед сессией.** `gap_graph.rebuild` переигрывает журнал попыток, кластеризует ошибки, считает `priority`; `session_planner` собирает план из 3–5 блоков по LO.
3. **Во время сессии.** Tutor Engine берёт блок плана, подтягивает теорию и похожие прошлые ошибки, ведёт диалог и выдаёт задачи. Каждый ответ уходит в Evaluation Loop, а новая θ сразу меняет сложность следующей задачи.
4. **После сессии.** Узел `wrap_up` пишет рефлексию в `tutor_insights` и отчёт в `data/reports/`: какие LO выросли, какие misconceptions закрыты, что повторить по FSRS.

## Ingestion: из файлов в базу знаний

Ingestion работает офлайн и инкрементально: на выходе каждый кусок теории привязан к конкретным LO, а между LO построены рёбра пререквизитов. Пайплайн идёт строго по шагам:

1. **Манифест.** `manifest.py` считает SHA-256 каждого файла в `data/raw`. Неизменённые файлы пропускаются; у изменённых старые чанки удаляются по `source_id` из ChromaDB и SQLite, затем файл индексируется заново.
2. **Загрузка.**
   - **PPTX** (`python-pptx`): по каждому слайду — заголовок, текст фигур в порядке чтения, таблицы в markdown и заметки докладчика. В заметках учителя часто лежит самое ценное объяснение. Встроенные картинки со схемами уходят в `vision.py` и возвращаются текстовым описанием.
   - **PDF** (`pymupdf4llm`): постраничный markdown, оглавление `get_toc()` даёт путь раздела («Глава 3 › §12»). Страница с текстом короче 50 символов считается сканом и идёт в OCR (tesseract `rus+kaz+eng`) или в Claude vision, если на ней формулы.
   - **Списки LO** (`lo_loader.py`): xlsx, csv, таблицы docx или PDF учебной программы. Код цели ищется регуляркой вида `\d{1,2}\.\d{1,2}\.\d{1,2}\.\d{1,2}` (класс.раздел.подраздел.номер); формат настраивается в `nis_assessment.yaml`.
3. **Нормализация.** Удаляются повторяющиеся колонтитулы (строки, встречающиеся на большинстве страниц), склеиваются переносы, текст приводится к NFC с сохранением казахских букв. Язык каждого блока определяет `lingua`.
4. **Чанкинг по структуре.** Слайд — один чанк, мелкие соседние слайды с одним заголовком склеиваются. PDF режется по заголовкам, затем по абзацам до 350–700 токенов с перекрытием в один абзац. Таблица, формула и разобранный пример («Пример», «Решение») никогда не режутся пополам.
5. **Тип чанка.** `claude-haiku-5-5` помечает чанк как `definition`, `law`, `worked_example`, `exercise`, `figure` или `summary`. Tutor Engine берёт определения для объяснения, разобранные примеры — для исправления ошибок, упражнения — как основу для генерации задач.
6. **Эмбеддинги.** `bge-m3` батчами по 32, результат — в коллекцию `content_chunks`.
7. **Привязка к LO.** Для каждого чанка ищутся 5 ближайших LO того же предмета и класса. Косинус ≥ 0,75 — привязка автоматическая; 0,55–0,75 — решает Haiku со структурированным ответом; ниже — привязки нет. Пороги стартовые, их калибрует `evals/run_tagging_eval.py`.
8. **Пререквизиты.** Кандидаты в пары — LO одного предмета, где A стоит раньше B по коду или классу и они семантически близки. `claude-sonnet-5-5` отвечает на вопрос «нужно ли знать A, чтобы освоить B?» с уверенностью; рёбра с уверенностью ≥ 0,7 сохраняются. Результат дублируется в `data/processed/prereqs.yaml`, чтобы ученик или учитель могли поправить граф руками.
9. **Образцы СОР/СОЧ** (необязательно). `past_papers.py` вытаскивает из них задания с баллами и дескрипторами. Они попадают в банк задач с пометкой `source=past_paper` и служат эталоном стиля для генератора.
10. **Отчёт о покрытии.** Пайплайн печатает LO, к которым не привязан ни один чанк. По таким LO тьютор честно скажет, что материала нет, и не будет выдумывать теорию.

Куда что записывается:

| Что | SQLite (`educa.db`) | ChromaDB |
| --- | --- | --- |
| Документ | `documents`: путь, хеш, тип, предмет | — |
| Чанк | `chunks`: страница или слайд, путь раздела, тип | `content_chunks`: текст + эмбеддинг, метаданные `source_id`, `subject`, `grade`, `lo_primary`, `chunk_type`, `lang` |
| Цель обучения | `learning_objectives`: код, текст, раздел, четверть, вес в СОЧ | `learning_objectives`: текст LO + эмбеддинг |
| Чанк ↔ LO | `chunk_lo`: многие-ко-многим со score | только `lo_primary` для быстрых фильтров |
| Пререквизит | `lo_prerequisites`: from, to, уверенность, источник (llm / manual) | — |
| Задача из образца | `items` | `item_bank` |

## Memory: журнал ошибок, модель ученика и Knowledge Gap Graph

Память устроена в три уровня: журнал фактов в SQLite, семантический индекс ошибок в ChromaDB и Knowledge Gap Graph, который перед каждой сессией пересобирается из первых двух. Граф — производная величина: его можно удалить и восстановить без потерь.

### Коллекции ChromaDB

| Коллекция | Документ | Ключевые метаданные | Кто читает |
| --- | --- | --- | --- |
| `content_chunks` | Текст чанка | `source_id`, `subject`, `grade`, `lo_primary`, `chunk_type`, `lang`, `page` | `tutor/retrieval` |
| `learning_objectives` | Формулировка LO | `code`, `subject`, `grade`, `section`, `quarter` | `lo_tagger`, `prereq_builder` |
| `mistakes` | «LO · задача · ответ ученика · диагноз» | `attempt_id`, `lo_code`, `error_type`, `severity`, `misconception_id`, `ts`, `resolved` | `gap_graph`, `misconceptions`, `retrieval` |
| `item_bank` | Условие задачи | `lo_code`, `thinking_level`, `difficulty_b`, `kind` (sor / soch / practice), `source`, `times_used` | `items/bank` |
| `tutor_insights` | Вывод рефлексии о том, какое объяснение сработало | `lo_code`, `strategy`, `effect`, `ts` | `tutor/explain` |

Запись об ошибке в `mistakes` (пример):

```json
{
  "id": "mst_01JB7K…",
  "document": "LO 10.2.1.3 · Задача: тело брошено под углом 30° к горизонту… · Ответ ученика: t = 2v₀/g · Диагноз: взята полная скорость вместо вертикальной составляющей v₀·sin α",
  "metadata": {
    "attempt_id": "att_01JB7J…",
    "session_id": "ses_01JB7H…",
    "lo_code": "10.2.1.3",
    "error_type": "conceptual",
    "severity": 0.8,
    "thinking_level": "application",
    "misconception_id": "mc_017",
    "ts": 1793232000,
    "resolved": false
  }
}
```

Эмбеддинг строится по полю `document`, поэтому похожие ошибки находятся даже в разных задачах и на разных языках.

### Таксономия ошибок

Тип ошибки задаёт её вес в формуле слабости. Веса стартовые, лежат в `error_taxonomy.yaml`.

| Тип | Признак | Вес w |
| --- | --- | --- |
| `conceptual` | Неверно понят закон, определение или идея | 1,0 |
| `procedural` | Идея верна, нарушен алгоритм решения | 0,8 |
| `incomplete_justification` | Ответ верный, но нет шагов, которых требуют дескрипторы | 0,6 |
| `terminology` | Неверный термин или формулировка, в том числе на казахском или английском | 0,5 |
| `units_notation` | Единицы измерения, обозначения, оформление | 0,4 |
| `misreading` | Невнимательно прочитано условие | 0,4 |
| `computational` | Арифметика и вычисления | 0,3 |

`incomplete_justification` выделен отдельно: на СОЧ баллы теряются именно здесь, когда ответ верный, а дескриптор «записывает обоснование» не выполнен.

### Модель ученика (`learner_model.py`)

У каждого LO своя способность θ, у каждой задачи — сложность b. После попытки θ и b обновляются по Elo с частичным баллом s = балл / максимум. Каждая использованная подсказка снижает засчитанный балл на 25%.

```latex
P(\text{верно}) = \sigma(\theta_{LO} - b_{item}), \qquad s_{eff} = s \cdot (1 - 0{,}25 \cdot h)
```

```latex
\theta_{LO} \leftarrow \theta_{LO} + K\,(s_{eff} - P), \qquad b_{item} \leftarrow b_{item} - K_{item}\,(s_{eff} - P)
```

K = 0,4 на первых 10 попытках по LO, затем 0,15 — так модель быстро находит уровень, а потом не скачет. Параллельно по каждому LO живёт FSRS-карточка: s < 0,5 → Again, < 0,75 → Hard, < 0,95 → Good, иначе Easy. FSRS даёт вероятность вспомнить R(t), которая падает, если LO давно не повторяли.

### Кластеры ошибок → misconceptions

Одна ошибка — случайность, повторяющаяся — устойчивое заблуждение. `misconceptions.py` работает в два режима:

- **Онлайн.** Новая ошибка сравнивается с центроидами известных misconceptions того же LO; при косинусе ≥ 0,8 она привязывается к существующему кластеру.
- **Перед сессией.** Нерешённые ошибки за последние 30 дней кластеризуются HDBSCAN (`min_cluster_size=2`). Новый кластер становится misconception, `claude-haiku-5-5` называет его одной строкой, например «путает массу и вес».

Misconception закрывается после трёх верных ответов подряд на задачи, которые целятся именно в неё. Тогда все её ошибки получают `resolved=true` и перестают давить на граф.

### Структура графа

- **Узлы LO**: `theta`, `mastery`, `retrievability`, `error_load`, `gap`, `blame`, `priority`, `coverage`, `next_assessment`.
- **Узлы misconception**: `label`, `occurrences`, `last_seen`.
- **Рёбра** `prerequisite_of` (LO A → LO B), `affects` (misconception → LO) и, по желанию, `similar` (LO ↔ LO по эмбеддингам) для переноса навыка.

### Пересчёт перед сессией (`gap_graph.rebuild`)

1. Загрузить LO и рёбра пререквизитов из SQLite.
2. Переиграть журнал попыток: θ и FSRS получаются из лога детерминированно, рассинхрона не бывает.
3. Обновить кластеры misconceptions и добавить их узлы и рёбра `affects`.
4. Посчитать для каждого LO освоенность m, вероятность вспомнить R и нагрузку ошибок E — по формулам ниже.
5. Пустить вину вверх по пререквизитам: personalized PageRank на обращённом графе (B → A, если A нужен для B) с вектором персонализации gap и затуханием 0,85. Если слабы несколько LO, которые опираются на одно и то же A, у A вырастает `blame` — это корень проблемы.
6. Посчитать `priority` и применить фильтр фундамента: если у LO есть пререквизит с gap > 0,6, сначала в план идёт пререквизит.
7. Сохранить снимок в `data/reports/graph_YYYY-MM-DD.json` и diff с прошлым: какие LO окрепли, какие просели, какие misconceptions закрылись. Этот diff — видимый результат самообучения.

```latex
m_i = \sigma(\theta_i - b_{ref}), \qquad E_i = \sum_{k \in \text{нерешённые}} w_{type(k)} \cdot severity_k \cdot e^{-\Delta t_k / \tau}
```

```latex
gap_i = (1 - \alpha)\,(1 - m_i R_i) + \alpha\,(1 - e^{-E_i})
```

```latex
priority_i = gap_i \cdot (1 + \beta \cdot blame_i) \cdot w^{exam}_i \cdot \left(1 + \gamma\, e^{-d_i / 7}\right)
```

Здесь b\_ref — сложность типичной задачи СОЧ, w^exam — вес LO в ближайшем оценивании (текущая четверть 1,0, прошлые 0,5, вне программы СОЧ 0,2), d — дней до ближайшего СОР или СОЧ, который покрывает этот LO. Стартовые параметры в `settings.yaml`: α = 0,3, β = 0,5, γ = 1,0, τ = 14 дней, b\_ref = 0,5. LO без единой попытки получает θ = 0 и бонус исследования, чтобы граф не застревал на уже известных слабостях.

### Профиль и инсайты тьютора (`profile.py`)

Второй контур самообучения меняет не оценку ученика, а поведение тьютора. После сессии `session_reflection.j2` получает сжатый транскрипт и метрики и записывает 1–3 инсайта в `tutor_insights`: какая стратегия объяснения по какому LO сработала (аналогия, разобранный пример, контрпример, формальное определение). У инсайта есть `effect` — изменение θ на следующих попытках после объяснения в этом стиле. Инсайты с отрицательным эффектом затухают, с положительным — подмешиваются в промпт `explain.j2` в следующий раз.

## Tutor Engine: сократовский диалог

Tutor Engine — это `StateGraph` из LangGraph, который проходит один и тот же путь на каждый блок плана: активация, объяснение, вопросы на понимание, задачи. Каждый неверный ответ возвращает ученика на шаг назад — к новому вопросу или подсказке, а не к готовому решению. Ожидание ответа — `interrupt()`, состояние сохраняет SQLite-checkpointer, поэтому сессию можно закрыть и продолжить на том же месте.

&#91;embedded content: граф состояний Tutor Engine · 10 узлов, 2 сократовские петли\]

Решение в ромбах принимает код по структурированному вердикту LLM или по баллу из Evaluation Loop, а не сама модель свободным текстом: так петли предсказуемы и тестируемы.

### Что делает каждый узел

| Узел | Что делает | Модель |
| --- | --- | --- |
| `load_context` | Берёт блок плана; из `content_chunks` — до 6 чанков по LO (сначала определения и законы), из `mistakes` — 3 похожие нерешённые ошибки, из `tutor_insights` — что раньше сработало | — |
| `activate_prior` | 1–2 вопроса о том, что ученик уже знает. Уверенный верный ответ при высокой θ сокращает объяснение до краткого напоминания | Sonnet |
| `explain` | Теория порциями по 3–5 предложений, каждая со ссылкой на слайд или страницу. Известные misconceptions по этому LO разбираются явно | Sonnet |
| `socratic_probe` | Один вопрос на понимание, не на память: «что изменится, если…», «почему здесь нельзя…». Вердикт: `understood` / `partial` / `misconception` | Sonnet |
| `remediate` | Контрпример или разобранный пример из материалов против найденного заблуждения. После 2 неудач подряд — возврат в `explain` с другой стратегией объяснения | Sonnet |
| `practice` | Задача из банка или сгенерированная под целевую сложность и уровень мыслительных навыков, с баллами и дескрипторами как на СОР/СОЧ | Sonnet (генерация) |
| `hint` | Лестница из трёх ступеней: намёк на нужный закон → наводящий вопрос к ошибочному шагу → первый шаг решения. После третьей — полный разбор и переход дальше | Sonnet |
| `decide_next` | Задача повторяется, пока mastery по LO ниже 0,8 и в блоке меньше 6 задач. Иначе — следующий блок или `wrap_up` | код |
| `wrap_up` | Краткий итог ученику, рефлексия в `tutor_insights`, отчёт в `data/reports/` | Sonnet |

### Сложность под ученика (`planner/difficulty.py`)

Целевая сложность задачи подбирается так, чтобы ученик решал её примерно в 75% случаев: задача тянет вверх, но не ломает. За 3 дня до СОР или СОЧ цель смещается к 60% — идёт натаскивание на задачах тяжелее среднего экзаменационного уровня.

```latex
b_{target} = \theta_{LO} - \ln\frac{p^*}{1 - p^*}, \qquad p^* = 0{,}75 \;(0{,}6 \text{ перед экзаменом})
```

| Целевая сложность b | Уровень мыслительных навыков | Типичная задача |
| --- | --- | --- |
| ниже −0,5 | Знание и понимание | Определение, выбор ответа, формула в одно действие |
| от −0,5 до 0,8 | Применение | Расчётная задача в 2–4 шага, работа с графиком или таблицей |
| выше 0,8 | Навыки высокого порядка | Анализ, обоснование, нестандартная ситуация, связь нескольких LO |

Если у блока есть открытая misconception, генератор строит задачу-ловушку: её невозможно решить верно, не преодолев именно это заблуждение (`targets_misconception` в модели `Item`).

### Режим симуляции СОЧ (`exam_mode.py`)

В режиме `educa exam` граф идёт коротким путём: `load_context → practice → Evaluation Loop`, без объяснений, вопросов и подсказок. Вариант собирается по спецификации из `nis_assessment.yaml`: LO четверти, доля заданий каждого уровня, сумма баллов и время. Таймер идёт на всю работу, ответы оцениваются в конце, результат приходит бланком «критерий · дескриптор · балл». Ошибки пишутся в память с флагом `exam=true` и весят в графе в 1,5 раза больше: они сделаны без подсказок и под давлением времени.

### Правила тьютора (`policies.py` + `tutor_system.j2`)

- Не называть ответ и не решать задачу за ученика до его попытки. Проверяется кодом: если в реплике тьютора встречается `reference_answer`, реплика перегенерируется.
- Одна реплика — один вопрос ученику.
- Теория — только из найденных чанков, со ссылкой «(слайд 12)» или «(с. 87)».
- Язык диалога берётся из настроек предмета (ru / kk / en), термины дублируются на языке оценивания, если он другой.
- Системный промпт и контекст LO кешируются (prompt caching): они одинаковы во всех репликах блока.

## Evaluation Loop: оценка, диагноз, запись

Каждый ответ проходит один и тот же конвейер из семи шагов. Сначала работают детерминированные проверки, LLM подключается только к развёрнутым ответам. Итог одной попытки — обновлённые θ и FSRS, запись в журнал ошибок и сократовская обратная связь.

1. **Приём ответа.** Текст, формула или фото решения от руки. Фото расшифровывает Claude vision, и агент спрашивает: «Я прочитал так: … Верно?» — оценивается только подтверждённая расшифровка.
2. **Маршрутизация по типу ответа** (таблица ниже).
3. **Оценка по дескрипторам** (`rubric_llm.py`, `claude-sonnet-5-5`, temperature 0). По каждому дескриптору модель возвращает структурированный вердикт: выполнен ли, сколько баллов, цитата-доказательство из ответа, чего не хватает. В промпте — эталонное решение, дескрипторы и правила из `nis_assessment.yaml`. Задачи на 3 балла и больше проверяются дважды с разным порядком дескрипторов; при расхождении решает третий проход. История ученика оценщику не показывается, чтобы не было предвзятости.
4. **Диагноз** (`diagnosis.py`), если балл неполный. `claude-haiku-5-5` определяет тип ошибки по таксономии, severity и формулирует заблуждение одним предложением. Рядом подтягиваются 3 похожие ошибки того же LO из `mistakes`, чтобы привязать новую к уже известной misconception. Если уверенность ниже 0,6, диагноз переделывает Sonnet.
5. **Запись** (`mistake_log.py`). В одной транзакции SQLite: строка `attempts`, обновление θ, b и FSRS, строка `mistakes`. Затем upsert в ChromaDB с тем же id. Если запись в Chroma упала, строка помечается `pending_index` и дописывается при следующем запуске (outbox) — память не теряет ошибок.
6. **Обратная связь** (`feedback.py`). В режиме практики — баллы по дескрипторам и вопрос, ведущий к ошибке, без готового ответа: «Какая составляющая скорости определяет время подъёма?». Полное решение со ссылкой на слайд или страницу открывается после трёх подсказок или после второй неудачной попытки. В режиме СОЧ обратная связь откладывается до конца работы и выдаётся бланком «критерий · дескриптор · балл».
7. **Событие `AttemptGraded`.** Его читает узел `decide_next` в Tutor Engine: новая θ сразу меняет сложность следующей задачи.

| Тип ответа | Проверка | LLM |
| --- | --- | --- |
| Выбор, соответствие, верно / неверно | `deterministic.py`: точное совпадение | нет |
| Число | Значение с допуском (по умолчанию 1%) и единицы отдельно через `sympy.physics.units` | нет |
| Выражение, уравнение | `symbolic.py`: `simplify(a − b) == 0`, запасной вариант — сравнение в случайных точках | нет |
| Короткий ответ | `rubric_llm.py`, один проход | Haiku |
| Развёрнутое решение, обоснование, доказательство | `rubric_llm.py` по дескрипторам, двойная проверка от 3 баллов | Sonnet |

Кнопка «Оспорить оценку» помечает попытку: она исключается из θ до ручной проверки, а сама задача уходит в `evals/datasets/grading_golden.jsonl`. Так оценщик учится на собственных ошибках так же, как ученик.

Качество самого Evaluation Loop проверяется в `evals/`:

- **Оценщик.** На 50+ ответах с баллами, выставленными учителем, совпадение по дескрипторам должно быть ≥ 90%, средняя ошибка по баллам ≤ 0,3. Прогон — после каждой правки промптов `grade_rubric.j2` и `diagnose_error.j2`.
- **Петля целиком.** `simulated_student.py` — LLM-ученик с заранее заложенными заблуждениями. Через 20 задач Knowledge Gap Graph должен поставить в топ-5 приоритетов не меньше 80% заложенных пробелов.

## Модели данных и интерфейсы

Все компоненты обмениваются Pydantic-моделями из `domain/`; ответы LLM валидируются по тем же моделям, поэтому невалидный JSON до бизнес-логики не доходит. Значения уровней мыслительных навыков и формат СОР/СОЧ заданы по критериальному оцениванию и вынесены в `nis_assessment.yaml` — сверь их со спецификацией СОЧ своей школы.

```python
# domain/enums.py
from enum import StrEnum

class ThinkingLevel(StrEnum):
    KNOWLEDGE = "knowledge_understanding"   # Знание и понимание
    APPLICATION = "application"             # Применение
    HIGHER_ORDER = "higher_order"           # Навыки высокого порядка

class AssessmentKind(StrEnum):
    PRACTICE = "practice"
    SOR = "sor"      # суммативное оценивание за раздел
    SOCH = "soch"    # суммативное оценивание за четверть

class ErrorType(StrEnum):
    CONCEPTUAL = "conceptual"
    PROCEDURAL = "procedural"
    INCOMPLETE_JUSTIFICATION = "incomplete_justification"
    TERMINOLOGY = "terminology"
    UNITS_NOTATION = "units_notation"
    MISREADING = "misreading"
    COMPUTATIONAL = "computational"
```

```python
# domain/models.py
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class LearningObjective(BaseModel):
    code: str                        # "10.2.1.3"
    subject: str
    grade: int
    section: str
    quarter: int | None = None
    text: str
    lang: Literal["ru", "kk", "en"] = "ru"
    exam_weight: float = 1.0

class Chunk(BaseModel):
    id: str
    source_id: str
    text: str
    chunk_type: Literal["definition", "law", "worked_example",
                        "exercise", "figure", "summary"]
    location: str                    # "слайд 12" | "с. 87"
    section_path: list[str] = []
    lo_codes: list[str] = []

class Descriptor(BaseModel):
    id: str
    text: str                        # «записывает формулу времени подъёма»
    points: int

class Item(BaseModel):
    id: str
    lo_codes: list[str]
    kind: AssessmentKind
    thinking_level: ThinkingLevel
    difficulty_b: float = 0.0
    stem: str
    answer_type: Literal["mcq", "numeric", "expression", "short", "extended"]
    options: list[str] | None = None
    reference_answer: str
    reference_solution: str
    descriptors: list[Descriptor]
    max_points: int
    targets_misconception: str | None = None
    source: Literal["generated", "past_paper", "manual"] = "generated"
    grounding_chunk_ids: list[str] = []

class DescriptorVerdict(BaseModel):
    descriptor_id: str
    met: bool
    points: int
    evidence: str                    # цитата из ответа ученика
    missing: str | None = None

class GradeResult(BaseModel):
    points: float
    max_points: int
    verdicts: list[DescriptorVerdict]
    grader: Literal["deterministic", "symbolic", "rubric_llm"]
    agreement: float = 1.0           # согласие двух проходов оценщика

class Diagnosis(BaseModel):
    error_type: ErrorType
    severity: float = Field(ge=0, le=1)
    misconception_text: str
    misconception_id: str | None = None
    confidence: float = Field(ge=0, le=1)

class Attempt(BaseModel):
    id: str
    session_id: str
    item_id: str
    lo_code: str
    answer: str
    hints_used: int = 0
    latency_s: float
    grade: GradeResult | None = None
    diagnosis: Diagnosis | None = None
    disputed: bool = False
    created_at: datetime

class LONodeState(BaseModel):
    code: str
    theta: float
    mastery: float
    retrievability: float
    error_load: float
    gap: float
    blame: float
    priority: float
    next_assessment: datetime | None = None

class PlannedBlock(BaseModel):
    lo_code: str
    reason: Literal["root_cause", "weak", "decay_review", "new", "exam_focus"]
    target_level: ThinkingLevel
    target_b: float
    misconception_ids: list[str] = []
    minutes: int

class SessionPlan(BaseModel):
    session_id: str
    mode: Literal["study", "exam_sim"]
    blocks: list[PlannedBlock]
```

```python
# tutor/state.py
from typing import Annotated, Literal, TypedDict
from langgraph.graph.message import add_messages

class TutorState(TypedDict):
    plan: SessionPlan
    block_idx: int
    lo: LearningObjective
    context_chunks: list[Chunk]
    past_mistakes: list[str]         # тексты похожих ошибок из Chroma
    insights: list[str]              # что раньше сработало в объяснениях
    messages: Annotated[list, add_messages]
    phase: Literal["activate", "explain", "probe", "remediate",
                   "practice", "hint", "wrap"]
    current_item: Item | None
    hints_given: int
    probe_failures: int
    block_attempts: int
```

```python
# контракты между слоями (typing.Protocol)
class DocumentLoader(Protocol):
    def supports(self, path: Path) -> bool: ...
    def load(self, path: Path) -> list[RawBlock]: ...

class Grader(Protocol):
    def can_grade(self, item: Item) -> bool: ...
    def grade(self, item: Item, answer: str) -> GradeResult: ...

class ItemSource(Protocol):
    def get(self, lo_code: str, level: ThinkingLevel, target_b: float,
            exclude_ids: set[str]) -> Item: ...

class GapGraph(Protocol):
    def rebuild(self, subject: str, now: datetime) -> list[LONodeState]: ...
    def snapshot(self, path: Path) -> None: ...
```

`ItemSource` сначала ищет подходящую задачу в банке (тот же LO, уровень, |b − target\_b| < 0,3, не встречалась за 14 дней) и только при промахе вызывает генератор. Банк растёт сам, а стоимость API со временем падает.

## План реализации и риски

Строить стоит снизу вверх: сначала оценка ответов и журнал ошибок, потом тьютор. Без надёжного Evaluation Loop граф слабых мест будет учиться на шуме.

| Этап | Что появляется | Готово, когда |
| --- | --- | --- |
| 0. Каркас | `config`, `domain`, SQLite + Alembic, `llm/client.py`, CLI | `educa --help` работает, unit-тесты зелёные |
| 1. Ingestion | Загрузчики PPTX, PDF, LO; чанкинг; привязка к LO; отчёт покрытия | Один предмет загружен, ≥ 90% LO покрыты, точность привязки ≥ 0,85 на golden-наборе |
| 2. Evaluation | Три оценщика, диагноз, журнал ошибок с outbox | Совпадение с оценками учителя ≥ 90% по дескрипторам на 50 ответах |
| 3. Tutor Engine | Граф LangGraph, объяснение, сократовские вопросы, лестница подсказок, генератор и валидатор задач | Полная сессия по одному LO проходит без ручного вмешательства |
| 4. Self-Evolution | `learner_model`, кластеры misconceptions, Knowledge Gap Graph, планировщик, рефлексия | Симулированный ученик: ≥ 80% заложенных пробелов в топ-5 за 20 задач |
| 5. Экзамен и дашборд | Симуляция СОЧ с таймером и бланком баллов, Streamlit с графом | Пробный СОЧ проходит от начала до бланка результатов |
| 6. Калибровка | Уточнение b задач по реальным попыткам, сравнение стратегий объяснения | Предсказанная вероятность верного ответа сходится с фактической в пределах 10% |

| Риск | Чем закрыт |
| --- | --- |
| Тьютор выдумывает теорию | Объяснение только по найденным чанкам со ссылкой на слайд или страницу; нет чанков — «в твоих материалах этого нет» |
| Ошибка в эталонном ответе задачи | `validator.py`: Sonnet решает задачу заново, не видя эталона; числа и формулы сверяет SymPy; расхождение — задача отбрасывается |
| Неточная LLM-оценка | Двойная проверка от 3 баллов, golden-набор, кнопка «Оспорить оценку» |
| Формат не совпадает с реальными СОР/СОЧ | Образцы из `past_papers/` как эталоны стиля, правила в редактируемом `nis_assessment.yaml` |
| Холодный старт: граф пуст | Входная диагностика: по одной короткой задаче на каждый LO текущей четверти |
| Слабое качество на казахском | Мультиязычный bge-m3, отдельный казахский поднабор в golden-наборе привязки |
| Стоимость API | Haiku на массовых операциях, prompt caching для системного промпта и контекста LO, повторное использование банка задач |

Открытый вопрос: какие предметы и классы идут первыми — от этого зависят файлы в `config/subjects/` и порядок наполнения golden-наборов.

# EducaAgent

Локальный ИИ-тьютор для подготовки к СОР и СОЧ в НИШ. Строит базу знаний из твоих
презентаций, учебников и списков целей обучения (LO), ведёт сократовский диалог,
проверяет ответы по дескрипторам и запоминает ошибки, чтобы следующая сессия
начиналась с самых слабых мест.

Полная архитектура: [docs/architecture.md](docs/architecture.md).

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

Нужен Python 3.12 или новее. На Windows запускай его командой `py`.

```powershell
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

## Первый запуск

```powershell
educa init                  # создаёт data/ и базу данных
educa doctor                # проверяет, что всё настроено
```

Если выбран `provider: anthropic`, перед этим скопируй `.env.example` в `.env` и впиши `ANTHROPIC_API_KEY`.

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

- `config/` — настройки: модели и пороги (`settings.yaml`), правила НИШ, таксономия ошибок, предметы, промпты.
- `src/educa_agent/` — код, разбитый по слоям (см. архитектуру).
- `data/` — твои материалы и база. Папка не попадает в git.
- `tests/` — тесты.

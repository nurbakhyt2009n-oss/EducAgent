# На Windows make не установлен по умолчанию — те же команды есть в README.
.PHONY: install install-all init doctor test lint typecheck ingest plan study exam report

install:
	pip install -e ".[dev]"

install-all:
	pip install -e ".[all,dev]"

init:
	educa init

doctor:
	educa doctor

test:
	pytest

lint:
	ruff check src tests
	ruff format --check src tests

typecheck:
	mypy src

ingest:
	educa ingest data/raw

plan:
	educa plan --subject physics_10

study:
	educa study

exam:
	educa exam --kind soch --quarter 2

report:
	educa report

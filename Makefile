.PHONY: install dev test lint format type run benchmark docker

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements-dev.txt

test:
	PYTHONPATH=. pytest -q --cov=app --cov-report=term-missing

lint:
	ruff check app tests

format:
	ruff format app tests

type:
	mypy app

run:
	uvicorn app.main:app --reload

benchmark:
	PYTHONPATH=. python scripts/benchmark.py

docker:
	docker build -t fitness-rs-api .

.PHONY: install lint format type test cov bench all

install:
	pip install -e ".[dev,docker]"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

type:
	mypy

test:
	pytest

cov:
	pytest --cov --cov-report=term-missing

# Single-collection performance gate (asserts a ceiling; see test_snapshot.py).
# Override the ceiling with SYSDOCK_BENCH_CEILING_MS.
bench:
	pytest tests/unit/test_snapshot.py::test_single_collection_under_ceiling -v

all: lint type test

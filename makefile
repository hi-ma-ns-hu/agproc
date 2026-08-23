.PHONY: install dev lint lint-fix format

# install dependencies
install:
	pip install -r requirements.txt

# run the API locally with autoreload
dev:
	uvicorn app:app --port 7000 --reload

# check for lint errors
lint:
	ruff check .

# fix lint errors
lint-fix:
	ruff check . --fix

# auto-format the codebase
format:
	ruff format .

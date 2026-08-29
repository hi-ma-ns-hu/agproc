.PHONY: install dev lint lint-fix format test

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

# make test
# make test file=file_path
# make test file=file_path func=func_name
test:
ifdef func
ifndef file
	$(error set file=<path> when using func=<name>)
endif
	pytest "$(file)::$(func)"
else
	pytest $(file)
endif

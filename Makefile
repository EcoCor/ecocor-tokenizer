PYTHON ?= python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

.PHONY: install test clean lint

install: $(VENV)/pyvenv.cfg

$(VENV)/pyvenv.cfg: requirements.txt pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo
	@echo "env ready. activate with:  source $(VENV)/bin/activate"
	@echo "run CLI with:              ecocor-tokenize --help"

test:
	$(PY) -m pytest tests/ -v

clean:
	rm -rf $(VENV) *.egg-info build dist .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +

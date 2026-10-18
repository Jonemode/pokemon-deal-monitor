
.PHONY: help test catalog clean

PYTHON ?= python3

help:
	@echo "Available commands:"
	@echo "  make test    - Run all unit tests"
	@echo "  make catalog - Regenerate data/cards.json from source data"
	@echo "  make clean   - Remove Python cache files"

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

catalog:
	$(PYTHON) scripts/build_catalog.py

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete



.PHONY: help test catalog pricecharting-ids poll run clean

PYTHON ?= python3

help:
	@echo "Available commands:"
	@echo "  make test    - Run all unit tests"
	@echo "  make catalog - Regenerate data/cards.json from source data"
	@echo "  make pricecharting-ids - Map catalog cards to PriceCharting products"
	@echo "  make poll    - Search eBay once and report candidates"
	@echo "  make run     - Poll eBay continuously"
	@echo "  make clean   - Remove Python cache files"

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -t . -v

catalog:
	$(PYTHON) scripts/build_catalog.py

pricecharting-ids:
	PYTHONPATH=src $(PYTHON) scripts/map_pricecharting.py

poll:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor poll

run:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor run

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete



.PHONY: help test catalog pricecharting-ids telegram-chat-id test-alert poll run deploy logs clean

PYTHON ?= python3
# The server, as named in ~/.ssh/config; see deploy/README.md.
DEPLOY_HOST ?= pokemon-monitor
DEPLOY_DIR = /opt/pokemon-deal-monitor

help:
	@echo "Available commands:"
	@echo "  make test    - Run all unit tests"
	@echo "  make catalog - Regenerate data/cards.json from source data"
	@echo "  make pricecharting-ids - Map catalog cards to PriceCharting products"
	@echo "  make telegram-chat-id - Show the chat ID to send alerts to"
	@echo "  make test-alert - Send a sample alert to Telegram"
	@echo "  make poll    - Search eBay once, report candidates, send alerts"
	@echo "  make run     - Poll eBay continuously"
	@echo "  make deploy  - Copy the committed code to the server and restart it"
	@echo "  make logs    - Follow the server's monitor log"
	@echo "  make clean   - Remove Python cache files"

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -t . -v

catalog:
	$(PYTHON) scripts/build_catalog.py

pricecharting-ids:
	PYTHONPATH=src $(PYTHON) scripts/map_pricecharting.py

telegram-chat-id:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor telegram-chat-id

test-alert:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor test-alert

poll:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor poll

run:
	PYTHONPATH=src $(PYTHON) -m pokemon_deal_monitor run

# Copies the last commit, not uncommitted changes. The server's .env and
# database are left alone. Files are extracted as the monitor user, so the
# running service never finds its data directory owned by root.
deploy:
	@git diff --quiet HEAD || echo "Warning: uncommitted changes are not deployed."
	git archive HEAD | ssh $(DEPLOY_HOST) 'sudo -u monitor tar -x --no-overwrite-dir -C $(DEPLOY_DIR) \
		&& install -m 644 $(DEPLOY_DIR)/deploy/pokemon-deal-monitor.service /etc/systemd/system/ \
		&& systemctl daemon-reload \
		&& systemctl restart pokemon-deal-monitor \
		&& systemctl is-active pokemon-deal-monitor'

logs:
	ssh $(DEPLOY_HOST) journalctl -u pokemon-deal-monitor -f -o cat

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '.pytest_cache' -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete


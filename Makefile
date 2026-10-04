up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	python -m pytest -m "not live" -q

smoke:
	python scripts/smoke.py

calibrate:
	python scripts/calibrate.py

collect-calibration:
	python scripts/collect_calibration_ads.py

export-labels:
	docker compose run --rm -v $(CURDIR)/tests/golden:/out orchestrator python scripts/export_for_labeling.py 40 /out/real_labeled.jsonl

lint:
	python -m ruff check .
	python -m mypy shared/ services/api/app/

discover:
	docker compose run --rm job-discovery python -m app.worker --once

match:
	docker compose run --rm job-matching python -m app.worker --once

generate:
	docker compose run --rm cv-generator python -m app.worker --once

analyze:
	docker compose run --rm application-analyzer python -m app.worker --once

browser:
	docker compose run --rm browser-agent python -m app.worker --once

explorer:
	python -c "import webbrowser; webbrowser.open('artifacts')"

backup:
	bash scripts/backup.sh

restore:
	bash scripts/restore.sh $(FILE)

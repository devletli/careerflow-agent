up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

test:
	docker compose run --rm job-matching pytest
	docker compose run --rm job-discovery pytest

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
	explorer artifacts

backup:
	bash scripts/backup.sh

restore:
	bash scripts/restore.sh $(FILE)

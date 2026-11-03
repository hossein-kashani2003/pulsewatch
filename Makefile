.PHONY: cert up down logs test smoke
cert:   ; bash scripts/gen-cert.sh
up:     ; docker compose up -d --build
down:   ; docker compose down
logs:   ; docker compose logs -f --tail=50
test:   ; cd app && pip install -q -r requirements-dev.txt && ruff check . && pytest -q
smoke:
	@curl -ksf https://localhost/health && echo
	@set -a; . ./.env; set +a; \
	curl -ks -X POST https://localhost/api/monitors -H "X-API-Key: $$API_KEY" \
	  -H 'Content-Type: application/json' -d '{"name":"Example","url":"https://example.com","interval_s":10}'; echo

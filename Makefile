# Общие команды репозитория. Линт и тесты каждой области живут в её собственном Makefile.
WORKSPACES := core server web

.PHONY: setup lint test check guard

setup: ## make setup OWNER=ivan|arthur|andrew — подключить хуки и назвать себя
	@test -n "$(OWNER)" || { echo "Укажите участника: make setup OWNER=<ivan|arthur|andrew>"; exit 1; }
	@python3 scripts/checks.py setup $(OWNER)

lint: ## decision log, запрещённые файлы, линтеры областей
	@python3 scripts/checks.py lint
	@for w in $(WORKSPACES); do $(MAKE) --no-print-directory -C $$w lint || exit 1; done

test: ## тесты общих проверок и тесты областей
	@python3 -m unittest discover -s scripts/tests -q
	@for w in $(WORKSPACES); do $(MAKE) --no-print-directory -C $$w test || exit 1; done

check: lint test ## всё, что обязано быть зелёным перед коммитом

guard: ## не задел ли я чужую область относительно origin/main
	@python3 scripts/checks.py workspaces --base origin/main

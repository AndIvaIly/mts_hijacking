# server/ — рабочая область Arthur

API-сервер, хранение сессий и заявок, конфигурация. Сюда же относятся `deploy/` и корневые `Dockerfile`, `compose.yaml`, `.dockerignore`, `.env.example`.

Менять файлы здесь может только Arthur. Остальные читают; нужна правка — пишут владельцу (правила в [AGENTS.md](../AGENTS.md)).

| Документ | Что в нём |
| --- | --- |
| [docs/requirements.md](docs/requirements.md) | Требования и план выполнения по этапам |
| [docs/acceptance.md](docs/acceptance.md) | Критерии приёмки и способ проверки каждого |
| [docs/questions.md](docs/questions.md) | Вопросы, которые нужно решить |

Линт и тесты области — цели `lint` и `test` в [Makefile](Makefile); их вызывают корневой `make check` и CI.

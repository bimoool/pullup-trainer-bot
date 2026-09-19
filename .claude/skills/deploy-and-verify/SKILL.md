---
name: deploy-and-verify
description: Как код попадает на staging и в прод, и какие ограничения сервера надо учитывать. Использовать при изменениях в Dockerfile/docker-compose/workflows/скриптах деплоя, при падении деплоя, и когда нужно проверить изменение на живом окружении.
---

# Деплой и проверка

## Два контура, оба только по `workflow_dispatch` (никогда не на push)

| | Прод | Staging |
|---|---|---|
| Workflow | `deploy.yml` | `deploy-staging.yml` |
| Что деплоит | коммит по SHA | ветку по имени |
| Каталог на VPS | `/root/pullup-trainer-bot` | `/home/deploy/pullup-trainer-bot-staging` |
| Compose-проект | по умолчанию | `pullup-staging` |
| Порт Mini App | 8001 | 8002 |
| Домен | `app.bimoool.com` | `staging.app.bimoool.com` |
| SSH-ключ | `VPS_DEPLOY_SSH_KEY` | `VPS_STAGING_DEPLOY_SSH_KEY` (отдельный) |

## Жёсткое ограничение SSH

Оба ключа заперты forced-command обёрткой в `authorized_keys`. Через SSH **нельзя** прогнать
произвольный shell-скрипт — принимается только буквальный паттерн:

- прод: `./deploy.sh <40-hex-sha>` → `sudo deploy-run.sh`
- staging: `./deploy-staging.sh <branch>` → `~/deploy-staging-run.sh`

Всё остальное отклоняется с `rejected command: ...`. Секреты (`STAGING_BOT_TOKEN`,
`STAGING_CLONE_TOKEN`) читаются скриптом на сервере из `~/.staging-secrets.env`,
а не прокидываются через SSH-команду. Менять логику деплоя = менять скрипт на сервере,
не workflow.

## Ограничения железа

VPS — 1 vCPU / 1 GB RAM, и на нём живут другие проекты. Практические следствия:

- Сборка образов занимает минуты; после неё `uvicorn` стартует медленно.
- Health-check после `docker compose up -d` должен быть **циклом с ретраями**, а не
  фиксированным `sleep` — фиксированная пауза даёт ложные падения деплоя.
- Порты: только `127.0.0.1`, наружу отдаёт nginx/Caddy на хосте. Занятый порт = чужой
  контейнер, проверять `docker ps -a | grep <порт>` до паники.

## Известная заноза

`Dockerfile` копирует в образ только `app/`, `pyproject.toml`, `alembic.ini` — **`scripts/` в образ
не попадает**. Любой разовый скрипт (`backfill_multi_program.py` и т.п.) внутри контейнера
не запустится без `docker cp`. Если скрипт нужен в проде регулярно — чинить Dockerfile,
а не обходить копированием.

## Смена схемы БД

Порядок всегда: собрать образ → накатить миграции → поднять контейнеры. Обратный порядок
(поднять старый код на новой схеме) уже приводил к инциденту.

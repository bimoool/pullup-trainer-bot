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

## Что в образе

`Dockerfile` (образ `app`) копирует `app/`, `scripts/`, `pyproject.toml`, `alembic.ini` (`COPY scripts ./scripts`,
с 1685a76) — разовые скрипты (`backfill_multi_program.py`, `seed_*.py`) внутри контейнера `app` доступны:
`docker compose run --rm app python scripts/<x>.py`. Образ `web` (`Dockerfile.web`) копирует только `app/`, без
`scripts/`. **Деплой не запускает ни один скрипт** (`deploy/deploy-run.sh`: build → `alembic upgrade head` → up),
поэтому всё, что должно быть на каждой установке, обязано ехать миграцией: системный каталог (программа
«Подтягивания», библиотека упражнений, готовые тренировки) — data-миграция `a4c8e1f7b2d9`
(`docs/SYSTEM_CONTENT_CONTRACT.md`, #296). Скрипты — ручные инструменты оператора, не часть деплоя.

## Смена схемы БД

Порядок всегда: собрать образ → накатить миграции → поднять контейнеры. Обратный порядок
(поднять старый код на новой схеме) уже приводил к инциденту.

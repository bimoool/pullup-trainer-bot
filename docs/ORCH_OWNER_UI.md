# ORCH-2: управление с телефона

GitHub — источник состояния и исполнитель цикла. Открытый ChatGPT и домашний компьютер
не нужны. ChatGPT scheduled watcher — только необязательный наблюдатель: его задержка или
ошибка не останавливает GitHub Actions. Права записи обычного ChatGPT-коннектора не предполагаются.

## Одно действие

- **Одобрить задачу и запустить очередь:** новый комментарий `/orch approve` в открытой задаче.
  Planner проверяет автора комментария через GitHub API, проверяет структуру задачи, ставит
  `orch:owner-approved` и `status:ready`, запускает batch при отсутствии активного.
  Неполная задача отклоняется. Задачи берутся по существующим приоритетам очереди, поэтому
  одобренная задача не обязательно первая.
- **Запустить/продолжить уже готовую очередь:** новый комментарий `/orch start` в
  [dashboard #230](https://github.com/bimoool/pullup-trainer-bot/issues/230).
  Running batch сохраняет счётчики. После STOP/OWNER REVIEW новый start — явное одобрение
  следующего batch, максимум 5 завершений / 8 попыток. Если worker ещё работает, новый batch
  не начинается; после его завершения отправьте start ещё раз.
- **Остановить:** `/orch stop` в #230. Это мягкая остановка: уже выполняющаяся задача может
  завершить тесты и merge в свою разрешённую ветку; следующая не начнётся. Метка `orch:paused`
  на #230 дополнительно блокирует planner и вход нового worker до owner start.
  Сам owner stop-комментарий также проверяется перед выбором/запуском: отменённый
  в очереди Actions stop-run не теряет остановку; более старый start её не снимет.

Только новые комментарии bimoool, точное совпадение команды (пробелы по краям допустимы).
Редактирование комментария не запускает работу. PR-комментарии, чужие команды, аргументы,
имена веток и shell-фрагменты не принимаются. Одни изменения labels работу не запускают.

## Где смотреть

#230: dispatcher подтверждает **передачу**, planner — **применение**, worker — результат и
счётчик. Ошибка owner-command даёт ссылку на run. Тело #230 — актуальный canonical status;
для sandbox смотрите комментарии с явной sandbox-веткой. В задаче — brief и worker report.
GitHub уведомляет по обычным настройкам подписки: нажмите Subscribe на #230.

## Безопасность и размещение

На main нужен только `.github/workflows/orch-dispatcher.yml`: issue_comment исполняется с
DEFAULT branch. Workflow без checkout, shell и deploy secrets; фиксированный dispatch
`orch-planner.yml` с ref `develop/current`. Минимальные permissions: contents read,
issues/actions write. Planner независимо перечитывает owner comment, отклоняет изменённые,
старше часа и повторно применённые команды. Batch-переход и plan выполняются в существующей
группе `orch-state`. Команда не является произвольным параметром shell.

Planner/worker и gate остаются ORCH-1. Product merge только в develop/current; main и
production недоступны как target команд. Deploy workflow не вызывается.

## Изолированный live proof

Только точные `/orch sandbox-start` и `/orch sandbox-stop` в #230 выбирают заранее
зафиксированный `orch-sandbox/orch2-ui-proof`. Это единственное исключение к canonical base,
не свободный ввод ветки. Dispatcher всё равно исполняет planner workflow на develop/current.
Sandbox state обязан иметь limit=1 и scope_label=orch:ui-proof. Proof issue также имеет
`orch:test`, поэтому исключён из canonical очереди. Sandbox не переписывает тело #230.

Семантика GitHub: [issue_comment и workflow_dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows),
[GITHUB_TOKEN dispatch исключение](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

# Известные классы багов

Повторяющиеся паттерны ошибок, каждый пойман на реальном инциденте и
задокументирован с явным правилом на будущее — перенесено из `CLAUDE.md`
(issue #174) без пересказа, только заголовки/порядок.

## Известный класс бага: `callback.message.from_user` — это бот, не человек

В реальном Telegram сообщение, к которому прикреплена inline-кнопка,
отправлено ботом — `callback.message.from_user` всегда бот. Нажавшего
кнопку видно только через `callback.from_user`. Баг: `_finalize_workout`
брал `telegram_id` из `message.from_user.id` — для callback-варианта
(«Пропустить» у комментария) это ловило id бота, `get_by_telegram_id`
возвращал `None`, `user.id` падал `AttributeError` **после** `state.clear()`
— тренировка терялась молча, без сообщения об ошибке (aiogram глотает
необработанное исключение в хендлере). Подтверждено трассировкой из
логов прод-бота. Тот же паттерн жил ещё в трёх местах (`backdate.py`,
`menu.py::render_profile`, `profile_edit.py`) — везде заменено на явный
`telegram_id`, переданный от исходного callback/message, а не выведенный
из `message.from_user.id` задним числом.

Тестовая фикстура `tests/test_bot/conftest.py::make_callback_update` —
единственный источник `Update` с `CallbackQuery` для `tests/test_bot/`,
специально ставит `message.from_user` = бот (не нажавший), как в реальном
Telegram. Не заводить локальных копий с обратной (неверной) семантикой —
именно неверная копия маскировала баг до его обнаружения.

**Правило**: в любом хендлере, где `message` может прийти из
`CallbackQuery`, брать `telegram_id` только из `callback.from_user.id`
(или явного параметра, прокинутого от него), никогда из
`message.from_user.id`.


## Известный класс бага: `message.text` — `None` у сообщения с картинкой

Прод-инцидент (issue #69): рассылка "📢 Рассылка всем" и еженедельный
дайджест (`handle_weekly_digest_reply`) брали текст из `message.text`
напрямую и передавали его в `bot.send_message`. Когда админ присылает
сообщение с картинкой, Telegram кладёт подпись в `message.caption`, а
`message.text` остаётся `None` — `aiogram`/pydantic отклоняет
`SendMessage(text=None)` валидацией (`1 validation error for SendMessage:
text — Input should be a valid string`), рассылка падала целиком, ни один
пользователь не получал сообщение. Тот же провал ждал
`WeeklyDigestRepository.record` (колонка `text` — `NOT NULL`).

Фикс — `app/bot/handlers/admin.py::_broadcast_source_text` (`message.text
or message.caption`) как единственный источник текста для рассылки, и
ветвление на `bot.send_photo(..., caption=...)`, если в сообщении есть
`message.photo` — иначе картинка терялась бы молча, а подпись ушла бы как
обычный текст без неё. Тот же паттерн (`message.text` без учёта
`message.photo`/`message.caption`) правился заодно и в `handle_admin_dm_text`
(личное сообщение пользователю из карточки в `/admin`) — тот же класс
бага, тот же вызывающий код мог получить картинку так же легко.

**Правило**: в любом хендлере, принимающем свободный текст от админа для
пересылки другому пользователю, не читать `message.text` напрямую, если
сообщение может прийти с вложением — проверять `message.photo` и
использовать `message.caption` как текст в этом случае.


## Известный класс бага: альбом (несколько фото) — Telegram шлёт его как несколько Update, не один

Прод-инцидент (issue #72), найден сразу после фикса issue #69 выше: админ
прикрепил к рассылке НЕСКОЛЬКО фото — ушло одно фото с подписью, остальные
отдельными сообщениями без текста. Причина не в `_broadcast_to_onboarded_
users` самой по себе (она уже брала `message.photo`/`message.caption`
правильно), а в том, что Telegram доставляет альбом не одним сообщением с
несколькими фото, а несколькими отдельными Update с общим
`media_group_id` — по одному Update на каждое фото. `aiogram`-диспетчер в
реальном polling обрабатывает Update конкурентными asyncio-задачами
(`Dispatcher._polling`, `handle_as_tasks=True` по умолчанию), не дожидаясь
хендлера предыдущего Update — каждое фото альбома по отдельности ловило
`waiting_for_broadcast_text` и самостоятельно запускало полную рассылку.

Фикс — `app/bot/middlewares.py::MediaGroupMiddleware`, outer-middleware,
подключенный только на `admin_router.message`
(`app/bot/handlers/admin.py`, не глобально на весь `Dispatcher`, чтобы не
трогать альбомы вне админских сценариев). Буферизует части одного альбома
по `media_group_id`: первая часть ждёт `ALBUM_DEBOUNCE_SECONDS`, копит
остальные части (обычно приходят с разницей в десятки-сотни мс) в общий
список и передаёт их все хендлеру одним вызовом через `data["album"]`;
остальные части сами добавляют себя в буфер и завершаются без вызова
хендлера — иначе он запустился бы ещё раз на каждую из них.
`_broadcast_to_onboarded_users`, `handle_admin_broadcast_text`,
`handle_weekly_digest_reply` и `handle_admin_dm_text` при непустом `album`
шлют `bot.send_media_group` с `InputMediaPhoto(caption=...)` на одном
элементе массива вместо `send_photo` на каждое фото по отдельности; caption
ищется по ВСЕМ частям альбома (`_album_caption`), не только по первой
пришедшей — Telegram не гарантирует, что подпись окажется именно на
дошедшей до буфера первой.

**Правило**: любой хендлер, ожидающий «одно сообщение = один Update» (в
частности — рассылки/пересылка от админа), не может просто проверять
`message.photo` для случая с несколькими фото — Telegram гарантированно
разобьёт такое сообщение на несколько Update с общим `media_group_id`.
Нужна буферизация по `media_group_id` до хендлера (см.
`MediaGroupMiddleware`), не точечная правка внутри самого хендлера.


## Известный класс бага: `Input`/`Select` из `@telegram-apps/telegram-ui` без `Section` — визуально невидимы (issue #170)

`AppRoot` (`webapp-frontend/src/main.tsx`) задаёт CSS-переменные темы
(`--tgui--bg_color`/`--tgui--section_bg_color`/`--tgui--outline` и т.п.) на
весь поддерево, но сам не даёт `Input`/`Select` контрастного фона — их
собственный фон (`background: var(--tgui--bg_color)`) совпадает с фоном
страницы, а рамка (`box-shadow` с `--tgui--outline`, ~5% непрозрачности)
почти не видна. Именно `<Section>` (свой `background:
var(--tgui--section_bg_color)`, обычно серый на светлой теме) даёт полю
видимый контраст — без неё поле технически в DOM, принимает фокус/ввод, но
выглядит пустым местом, ни подписи `header`, ни рамки не разглядеть.
`OnboardingScreen.tsx` был единственным местом в проекте, где `Input`/
`Select` рендерились не через `<Section>` (везде — `ProfileEditForm.tsx`/
`BackdateForm.tsx`/`HistoryEditForm.tsx` — уже оборачивали); исправлено
обёрткой `<Section className="block-section">` вокруг полей на каждой фазе
(`baseline_input` и все 5 шагов анкеты), тем же паттерном, что и в
остальных формах.

**Правило**: `Input`/`Select` из этого кита всегда оборачивать в
`<Section>` (или `<List>`), не рендерить напрямую в `<div>` — сам компонент
не подскажет об этом ни ошибкой, ни визуальным сигналом сильнее, чем
"как будто светлый на светлом".


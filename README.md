# vk-notification-bot

Telegram-бот, который ретранслирует уведомления из ВКонтакте в Telegram: личные сообщения, лайки, комментарии, упоминания, заявки в друзья, репосты и приглашения.

Создан как замена push-уведомлениям приложения ВК, которое удалили из App Store.

## Что умеет

- **ЛС** — мгновенно через VK Long Poll (текст, вложения, стикеры, голосовые, форварды).
- **Лайки / комментарии / упоминания / друзья / репосты / приглашения** — через `notifications.get`.
- **Гибкая настройка** — каждую категорию можно включить/выключить через inline-меню.
- **Пауза** — `/pause` останавливает всё, `/resume` возвращает.
- **Безопасное хранение** — токен и cookie ВК шифруются Fernet'ом, ключ — в `.env`.
- **Устойчивость к Flood control** — после VK API error 9/29 бот не долбит API, а ждёт минуты/часы и продолжает доставлять ЛС из Long Poll без лишних method-вызовов.

## Стек

- Python 3.11+
- aiogram 3
- aiohttp
- aiosqlite + cryptography

## Установка локально

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Скопировать вывод в .env как FERNET_KEY=...
# Получить BOT_TOKEN у @BotFather и вставить в .env

python -m bot.main
```

Тесты:

```bash
pip install -r requirements-dev.txt
pytest
```

## Как подключить аккаунт ВК

Kate Mobile, VK Admin и официальный клиент для Android больше не отдают доступ к сообщениям через `oauth.vk.com` (`application is blocked` / `Unavailable for apps with direct auth`).

Бот берёт сессию **сайта vk.com**: cookie `remixsid` → `login.vk.com/?act=web_token` (приложение 6287487). Токен живёт ~24 минуты и обновляется сам, пока cookie валиден.

1. Открыть [vk.ru](https://vk.ru) в браузере и войти.
2. F12 → Application (Приложение) → Cookies → `https://vk.ru` → **remixsid**.
3. Скопировать Value и прислать боту одной строкой: `remixsid=...`

Не копировать весь заголовок Cookie из Network — Telegram обрезает длинные сообщения, и `remixsid` часто оказывается в обрезанном хвосте. Не копировать `document.cookie` из консоли: `remixsid` HttpOnly, его там нет.

⚠️ Cookie — полный вход в аккаунт. В БД хранится зашифрованным (Fernet). Сообщение с cookie бот сразу удаляет. `/stop` стирает сессию; дополнительно стоит «Выйти на всех устройствах» в настройках VK.

## Команды бота

| Команда | Что делает |
|---|---|
| `/start` | Инструкция + приём Cookie |
| `/settings` | Меню настроек категорий |
| `/pause` | Поставить уведомления на паузу |
| `/resume` | Возобновить |
| `/stop` | Удалить аккаунт из бота |
| `/help` | Та же справка, что в `/start` |
| `/auth` | Снова показать инструкцию |

## Архитектура

```
bot/        # aiogram handlers
vk/         # VK API client + Long Poll + notifications + flood limiter + web_token
storage/    # SQLite, шифрование токенов, модели
core/       # config, WorkerManager (запуск/остановка тасков на юзера)
deploy/     # пример systemd-юнита
```

На каждого активного юзера крутятся две asyncio-таски — Long Poll для ЛС и поллер `notifications.get` для остального. При `/pause`, `/stop` или невалидном токене таски корректно гасятся.

Все вызовы `api.vk.com/method/` идут через общий `VKFloodController`: пауза между запросами, длинный cooldown после error 9/29, и глобальная пауза, если сразу несколько токенов ловят flood (типичный IP-бан).

## Flood control (VK API error 9)

С сентября 2026 VK заблокировал Kate Mobile и ужесточил лимиты для сторонних клиентов. Позже закрылись и VK Admin, и web-OAuth официального Android. Старые токены отвечают error 9 или `invalid_request`; бот просит Cookie с vk.com. Частые `notifications.get` и немедленный reconnect `messages.getLongPollServer` сами поддерживают блокировку.

Что делает бот:

- между method-вызовами всех пользователей — минимальный интервал (`VK_API_MIN_INTERVAL`) и **не больше одного** `api.vk.com/method` за раз;
- после error 9 — пауза от `VK_FLOOD_COOLDOWN` секунд (по умолчанию 15 мин) с экспонентой до часа;
- если flood ловят два токена подряд, API молчит для всех `VK_GLOBAL_FLOOD_COOLDOWN` секунд (по умолчанию 30 мин);
- ЛС всё равно уходят: Long Poll `a_check` не ходит в method API, а текст берётся из события, если `messages.getById` недоступен;
- `notifications.get` по умолчанию раз в 90 секунд, старт поллеров разнесён.

## Деплой (systemd)

Пример юнита — `deploy/vkbot.service`. Рабочая директория `/opt/vk-notification-bot`, пользователь `vkbot`, БД в `data/` (нужен write).

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vkbot
sudo journalctl -u vkbot -f
```

## Что не пересылается

- Звонки VK Calls — нет в публичном API.
- Истории, клипы — нет в `notifications.get`.
- Уведомления от сообществ-подписок (новые посты в группах) — это не «персональные» уведомления, VK их не отдаёт через этот метод.

## Лимиты

VK банит токены при подозрительной активности (запросы с серверных IP, частые вызовы). Для маленькой группы и интервала 90+ сек нагрузка заметно ниже, но 100% гарантии нет: политика VK по сторонним клиентам меняется. Если токен умирает — бот перестанет получать события и тихо остановит воркеры юзера; в логе будет `Token invalid`.

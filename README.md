# 🤖 SD.MRDN Telegram Notifier Hub

Единый сервис отправки уведомлений SD.MRDN в Telegram. Развёртывается на внешнем хостинге [Bothost.ru](https://bothost.ru).

---

## 🚀 1. Развёртывание на Bothost.ru

1. Зайдите в панель [Bothost.ru](https://bothost.ru) и создайте новый проект/бота:
   - **Тип:** `Python 3.12` (или Docker)
   - **Команда запуска:** `uvicorn app:app --host 0.0.0.0 --port 8080` (или дефолтный порт хостинга)
2. Загрузите файлы из этой папки (`app.py`, `requirements.txt`, `Dockerfile`).
3. В разделе **«Переменные окружения» (Environment Variables)** на Bothost укажите:
   - `TELEGRAM_BOT_TOKEN`: токен бота от `@BotFather`.
   - `TELEGRAM_USER_CHAT_ID`: ваш персональный Telegram ID.
   - `TELEGRAM_GROUP_CHAT_ID`: ID супергруппы (`-100...`).
   - `TELEGRAM_TOPIC_ID`: ID топика релизов в супергруппе.
   - `GITLAB_WEBHOOK_SECRET`: любой секретный ключ (например, `sd_mrdn_gl_token_999`).
   - `SD_MRDN_API_SECRET`: секретный ключ для ядра платформы.
4. Запустите сервис и скопируйте публичный URL вашего бота на Bothost (например: `https://bothost-app-xyz.bothost.ru`).

---

## 🦊 2. Настройка GitLab Webhook

1. В репозитории GitLab перейдите в:
   **Настройки (Settings) → Webhooks → Добавить новый webhook (Add new webhook)**.
2. Заполните поля:
   - **URL:** `https://<ВАШ_БОТ_НА_BOTHOST>/gitlab-webhook`
   - **Секретный токен (Secret token):** значение переменной `GITLAB_WEBHOOK_SECRET`, которое вы указали на Bothost.
   - **Триггер (Trigger):**
     - Отметьте галочкой только: ☑ **События пайплайна (Pipeline events)**.
   - **Проверка SSL (Enable SSL verification):** ☑ Включено.
3. Нажмите **Добавить webhook (Add webhook)**.
4. Проверьте отправку: нажмите кнопку **Test → Pipeline events**. В логах Bothost отобразится `200 OK`.

---

## ⚡ 3. Отправка внутренних событий из SD.MRDN

Для отправки алертов о заявках или сбоях из бэкенда SD.MRDN отправляется HTTP POST запрос:
```http
POST https://<ВАШ_БОТ_НА_BOTHOST>/sd-event
Content-Type: application/json
X-SD-Secret: <SD_MRDN_API_SECRET>

{
  "event_type": "ticket_created",
  "severity": "CRITICAL",
  "title": "Остановка линии розлива #2",
  "description": "Сбой датчика оптической отбраковки L1. Время простоя > 10 мин.",
  "target": "all",
  "company_name": "ООО «Меридиан»",
  "ticket_id": 1042,
  "url": "https://sd.mrdn.cloud/#tickets/1042"
}
```
Параметр `target`:
- `admin` — только в ЛС администратору;
- `group` — только в топик супергруппы;
- `all` — и в супергруппу, и в ЛС.

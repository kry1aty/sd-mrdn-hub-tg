"""SD.MRDN Telegram Notifier Hub (развёртывается на Bothost.ru).

Единый шлюз оповещений SD.MRDN в Telegram:
1. GitLab CI/CD Webhook (/gitlab-webhook):
   - При успешном деплое:
     * в топик релизов супергруппы: СТРОГО тело коммита (plain text);
     * лично администратору: подробная карточка со всеми ссылками (HTML).
   - При сбое деплоя: алерт лично администратору с логом ошибки.
2. События платформы SD.MRDN (/sd-event):
   - Критические инциденты (P1/P2)
   - Превышения дедлайнов SLA (SLA Watchdog)
   - Передача 24/7 смен (Shift Handover)
   - Системные алерты каналов связи (MAX Bot / ВАТС / Email)
"""
import os
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sd_mrdn_telegram_hub")

# Переменные окружения (задаются в панели Bothost)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_USER_CHAT_ID = os.getenv("TELEGRAM_USER_CHAT_ID", "").strip()
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "").strip()
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_TOPIC_ID", "").strip()
GITLAB_WEBHOOK_SECRET = os.getenv("GITLAB_WEBHOOK_SECRET", "").strip()
SD_MRDN_API_SECRET = os.getenv("SD_MRDN_API_SECRET", "").strip()

http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    logger.info("SD.MRDN Telegram Notifier Hub запущен на Bothost.")
    yield
    if http_client:
        await http_client.aclose()


app = FastAPI(title="SD.MRDN Telegram Notifier Hub", lifespan=lifespan)


async def send_telegram(
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = None,
    message_thread_id: Optional[str] = None,
) -> bool:
    """Универсальная отправка сообщения в Telegram через Bot API."""
    if not TELEGRAM_BOT_TOKEN or not chat_id or not text.strip():
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if message_thread_id:
        payload["message_thread_id"] = int(message_thread_id)

    try:
        assert http_client is not None
        res = await http_client.post(url, json=payload)
        if res.status_code == 200:
            return True
        logger.warning("Ошибка отправки Telegram (%s): %s", res.status_code, res.text)
    except Exception as exc:
        logger.error("Сбой сетевого запроса к Telegram API: %s", exc)
    return False


def extract_commit_body(full_message: str, title: str) -> str:
    """Извлекает тело коммита (описание изменений без заголовка)."""
    if not full_message:
        return title or "Обновление системы"

    parts = full_message.strip().split("\n\n", 1)
    if len(parts) > 1 and parts[1].strip():
        return parts[1].strip()

    lines = [line.strip() for line in full_message.strip().split("\n") if line.strip()]
    if len(lines) > 1:
        return "\n".join(lines[1:])

    return title or full_message.strip()


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "sd-mrdn-telegram-hub"}


# ============================================================================
# 1. ПРИЁМНИК GITLAB CI/CD WEBHOOK
# ============================================================================
@app.post("/gitlab-webhook")
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
):
    if GITLAB_WEBHOOK_SECRET and x_gitlab_token != GITLAB_WEBHOOK_SECRET:
        logger.warning("Отклонён GitLab Webhook: неверный X-Gitlab-Token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    payload = await request.json()
    if payload.get("object_kind") != "pipeline":
        return {"ok": True, "skipped": "Non-pipeline event"}

    attrs = payload.get("object_attributes", {})
    pipeline_status = attrs.get("status")
    ref = attrs.get("ref", "")
    pipeline_id = attrs.get("id")
    pipeline_url = f"{payload.get('project', {}).get('web_url', '')}/-/pipelines/{pipeline_id}"

    if pipeline_status not in ("success", "failed"):
        return {"ok": True, "skipped": f"Status '{pipeline_status}' ignored"}

    if ref not in ("staging", "master", "main"):
        return {"ok": True, "skipped": f"Branch '{ref}' ignored"}

    commit = payload.get("commit", {})
    commit_title = commit.get("title", "")
    commit_message = commit.get("message", "")
    commit_sha = commit.get("id", "")[:8]
    author_name = commit.get("author", {}).get("name", "Разработчик")
    env_name = "STAGING" if ref == "staging" else "PRODUCTION"

    if pipeline_status == "success":
        logger.info("Успешный деплой %s (%s). Отправка карточек...", ref, commit_sha)

        # 1. В ветку (топик) супергруппы: СТРОГО ТЕЛО КОММИТА (Plain text)
        commit_body = extract_commit_body(commit_message, commit_title)
        if TELEGRAM_GROUP_CHAT_ID:
            await send_telegram(
                chat_id=TELEGRAM_GROUP_CHAT_ID,
                text=commit_body,
                parse_mode=None,
                message_thread_id=TELEGRAM_TOPIC_ID or None,
            )

        # 2. Лично администратору: подробная карточка со всеми ссылками (HTML)
        if TELEGRAM_USER_CHAT_ID:
            user_msg = (
                f"🚀 <b>Обновление SD.MRDN установлено на {env_name}!</b>\n\n"
                f"📌 <b>Что сделано:</b> {commit_title}\n"
                f"🌿 <b>Ветка:</b> <code>{ref}</code> (<code>{commit_sha}</code>)\n"
                f"👤 <b>Автор:</b> {author_name}\n"
                f"🖥️ <b>Пульт:</b> <a href=\"https://sd.mrdn.cloud\">sd.mrdn.cloud</a>\n"
                f"🔍 <a href=\"{pipeline_url}\">Конвейер в GitLab</a>"
            )
            await send_telegram(
                chat_id=TELEGRAM_USER_CHAT_ID,
                text=user_msg,
                parse_mode="HTML",
            )

    elif pipeline_status == "failed":
        logger.warning("Сбой пайплайна %s (%s). Отправка алерта...", ref, commit_sha)
        if TELEGRAM_USER_CHAT_ID:
            alert_msg = (
                f"❌ <b>Сбой установки SD.MRDN на {env_name}!</b>\n\n"
                f"📌 <b>Коммит:</b> {commit_title}\n"
                f"🌿 <b>Ветка:</b> <code>{ref}</code> (<code>{commit_sha}</code>)\n"
                f"👤 <b>Автор:</b> {author_name}\n"
                f"⚠️ <a href=\"{pipeline_url}\">Смотреть лог ошибки в GitLab</a>"
            )
            await send_telegram(
                chat_id=TELEGRAM_USER_CHAT_ID,
                text=alert_msg,
                parse_mode="HTML",
            )

    return {"ok": True, "status": pipeline_status, "ref": ref}


# ============================================================================
# 2. ПРИЁМНИК СОБЫТИЙ ПЛАТФОРМЫ SD.MRDN (Заявки, SLA, Дежурства, Каналы)
# ============================================================================
class SDEventPayload(BaseModel):
    event_type: str = Field(..., description="ticket_created | sla_breach | handover | system_alert")
    severity: str = Field("INFO", description="INFO | WARNING | CRITICAL")
    title: str = Field(..., max_length=255)
    description: str = Field(...)
    target: str = Field("admin", description="admin | group | all")
    topic_id: Optional[str] = Field(None, description="Кастомный ID топика супергруппы")
    ticket_id: Optional[int] = None
    company_name: Optional[str] = None
    url: Optional[str] = None


@app.post("/sd-event")
async def sd_event(
    event: SDEventPayload,
    x_sd_secret: Optional[str] = Header(None, alias="X-SD-Secret"),
):
    if SD_MRDN_API_SECRET and x_sd_secret != SD_MRDN_API_SECRET:
        logger.warning("Отклонён SD-Event: неверный X-SD-Secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")

    icon = "ℹ️"
    if event.severity == "WARNING":
        icon = "⚠️"
    elif event.severity == "CRITICAL":
        icon = "🚨"

    msg = f"{icon} <b>SD.MRDN: {event.title}</b>\n\n{event.description}\n"
    if event.company_name:
        msg += f"\n🏢 <b>Предприятие:</b> {event.company_name}"
    if event.ticket_id:
        msg += f"\n🎫 <b>Заявка:</b> #{event.ticket_id}"
    if event.url:
        msg += f"\n🔗 <a href=\"{event.url}\">Перейти в пульт</a>"

    dest_topic = event.topic_id or TELEGRAM_TOPIC_ID or None

    # Отправка в супергруппу
    if event.target in ("group", "all") and TELEGRAM_GROUP_CHAT_ID:
        await send_telegram(
            chat_id=TELEGRAM_GROUP_CHAT_ID,
            text=msg,
            parse_mode="HTML",
            message_thread_id=dest_topic,
        )

    # Отправка лично администратору
    if event.target in ("admin", "all") and TELEGRAM_USER_CHAT_ID:
        await send_telegram(
            chat_id=TELEGRAM_USER_CHAT_ID,
            text=msg,
            parse_mode="HTML",
        )

    return {"ok": True, "event": event.event_type}

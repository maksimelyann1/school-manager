import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import ParentReportSettings


router = APIRouter(prefix="/ai", tags=["AI"])

DEFAULT_MODEL = "gemini-2.5-flash"
ALLOWED_CONTEXTS = {"message", "template", "auto_message"}


class PolishTextRequest(BaseModel):
    text: str
    context: str | None = "message"


def _polish_prompt(text: str, context: str) -> str:
    context_label = {
        "message": "звичайного повідомлення в Telegram",
        "template": "шаблону повідомлення в Telegram",
        "auto_message": "відкладеного або автоматичного повідомлення в Telegram",
    }.get(context, "повідомлення в Telegram")

    return f"""Ти — український редактор текстів для Telegram.
Твоє завдання: покращити текст {context_label}, не змінюючи структуру повідомлення.

Головне правило форматування:
- збережи переноси рядків рівно там, де їх зробив користувач;
- не об'єднуй рядки в один, навіть якщо в кожному рядку лише 1-3 слова;
- збережи порожні рядки, відступи, пробіли на початку рядків і візуальне групування;
- не прибирай зайві на вигляд відступи, якщо вони були в оригіналі;
- якщо додаєш емодзі або Telegram HTML-форматування, роби це всередині наявних рядків, не перебудовуючи макет; емодзі можна ставити як на початку рядка, так і в кінці або біля ключового слова, якщо це виглядає природно.

Що можна покращувати:
- виправ український правопис, граматику, пунктуацію та друкарські помилки;
- зроби текст природним, теплим, охайним і зрозумілим;
- активніше додавай тематичні емодзі, які точно підходять до сенсу тексту: навчання, час, нагадування, свято, важливість, дедлайн, фото, відео, домашнє завдання, успіх тощо;
- не став емодзі лише автоматично в кінці кожного рядка: комбінуй початок, кінець і акценти всередині рядка. Наприклад: "Скоро урок" можна оформити як "🔔Скоро урок👩‍💻";
- емодзі мають допомагати швидко зчитати настрій і тему повідомлення, але не замінювати важливі слова і не спотворювати факти;
- можна робити короткі заголовки жирними через Telegram HTML: <b>Заголовок</b>;
- важливий час або дату, наприклад 14:00 чи 27.05.2026, можна виділяти акцентом через <u>14:00</u>;
- можна виділяти важливі короткі фрази жирним або підкресленням, але без перевантаження.

Обмеження:
- збережи всі факти, імена, дати, час, ціни, номери груп, посилання та важливі формулювання;
- не вигадуй нові деталі, події, дедлайни, посилання або умови;
- якщо у тексті вже є HTML/Telegram-теги форматування, не ламай їх і не створюй невалідні теги;
- використовуй тільки прості Telegram HTML-теги: <b>, <i>, <u>, <s>, <code>, <pre>, <blockquote>, <spoiler>, <a href="...">;
- не додавай пояснення, заголовки типу "Ось покращений текст", лапки навколо відповіді або markdown-блоки.

Поверни тільки готовий покращений текст, збережений у тій самій структурі рядків.

Текст користувача:
{text}"""


@router.post("/polish-text")
async def polish_text(payload: PolishTextRequest, db: Session = Depends(get_db)):
    raw_text = str(payload.text or "")
    text = raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Спочатку введіть текст")

    settings = db.query(ParentReportSettings).first()
    api_key = ((settings.google_ai_api_key if settings else "") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Додайте Google AI API key в основних налаштуваннях")

    context = payload.context if payload.context in ALLOWED_CONTEXTS else "message"
    model = ((settings.google_ai_model if settings else "") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": _polish_prompt(raw_text, context)}]}],
                    "generationConfig": {"temperature": 0.55},
                },
            )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail=f"Помилка підключення до Google AI: {error}") from error

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Google AI повернув помилку HTTP {response.status_code}: {response.text[:500]}",
        )

    data = response.json()
    candidates = data.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    polished = "".join(str(part.get("text", "")) for part in parts if part.get("text"))
    if not polished.strip():
        raise HTTPException(status_code=502, detail="Google AI не повернув текст")

    return {"text": polished}

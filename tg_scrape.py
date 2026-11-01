"""
Объявления об обмене USD/EUR из Telegram-чата «Обмен Валюты Москва» (@obmenvmsk).
Читает чат от имени аккаунта (Telethon, строка сессии в секретах GitHub),
вытаскивает курс покупки/продажи, метро, считает «стаж» автора в чате
и пишет блок moscow_tg в rates.json.
Нужны переменные окружения: TG_API_ID, TG_API_HASH, TG_SESSION.
"""
import os, re, json, asyncio, datetime, pathlib, statistics
from collections import defaultdict

CHAT = "obmenvmsk"
OUT = pathlib.Path(__file__).with_name("rates.json")
MSK = datetime.timezone(datetime.timedelta(hours=3))
HOURS_FRESH = 24          # объявления за последние сутки идут в выдачу
DAYS_HISTORY = 7          # за сколько дней считаем «стаж» автора
MAX_MESSAGES = 6000       # предохранитель
TOP = 10

CUR = {
    "USD": (re.compile(r"\$|usd|доллар|долар|бакс|💵", re.I), (60, 130)),
    "EUR": (re.compile(r"€|eur|евро|💶", re.I), (70, 150)),
}
# число 2–3 знака (с копейками), не часть большего числа: 81.5 да, 5000 и 80000 нет
NUM_RE = re.compile(r"(?<![\d.,])(\d{2,3}(?:[.,]\d{1,2})?)(?![\d])")
SIDE_RE = re.compile(r"(покупка|покупаю|куплю|скупаю|скупка|buy)|(продажа|продаю|продам|продаём|sell)", re.I)
# признаки физической точки: офис, касса, пункт обмена, ТЦ/БЦ, адрес с домом, часы работы
OFFICE_RE = re.compile(
    r"(офис\w*|касс[аеуы]\w*|пункт\w*\s+обмена|обменн\w+\s+пункт\w*|точк[аеуи]\w*|"
    r"\bтц\b|\bбц\b|торгов\w+\s+центр\w*|бизнес[\s-]центр\w*|"
    r"\b(?:ул\.|улица|пр-т|проспект|пер\.|переулок|шоссе|наб\.|набережная|бульвар|б-р)\s*[А-ЯЁа-яё0-9\-\. ]{2,40}?,?\s*(?:д\.|дом)?\s*\d+|"
    r"работаем\s+(?:с|ежедневно|без\s+выходных)|приезжайте|приходите)", re.I)
METRO_RE = re.compile(r"(?:\bм\.|\bм\s|метро\s*)\s*([А-ЯЁ][а-яё]+(?:[\s\-][А-ЯЁа-яё][а-яё]+){0,2})")


def num(s):
    return float(s.replace(",", "."))


def parse(text):
    """-> {code: {"buy": x, "sell": y}} — buy: автор покупает валюту, sell: продаёт.
    Для каждого числа берём ближайшую валюту и ближайшее слово «куплю/продам» перед ним."""
    marks = sorted((m.start(), code) for code, (rx, _) in CUR.items() for m in rx.finditer(text))
    sides = [(m.start(), "buy" if m.group(1) else "sell") for m in SIDE_RE.finditer(text)]
    if not marks or not sides:
        return {}
    res = {}
    for m in NUM_RE.finditer(text):
        pos, v = m.start(), num(m.group(1))
        before = [c for p, c in marks if p < pos]
        code = before[-1] if before else marks[0][1] if marks[0][0] - pos < 15 else None
        side = next((sd for p, sd in reversed(sides) if p < pos), None)
        if not code or not side:
            continue
        lo, hi = CUR[code][1]
        if lo <= v <= hi:
            res.setdefault(code, {}).setdefault(side, v)
    return res


async def collect():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(os.environ["TG_SESSION"]),
                            int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    now = datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(days=DAYS_HISTORY)
    days_by_user = defaultdict(set)
    offers = []
    async with client:
        n = 0
        async for msg in client.iter_messages(CHAT, limit=MAX_MESSAGES):
            if msg.date < since:
                break
            n += 1
            uid = msg.sender_id
            if uid is None or not msg.message:
                continue
            days_by_user[uid].add(msg.date.astimezone(MSK).date())
            if msg.date < now - datetime.timedelta(hours=HOURS_FRESH):
                continue
            parsed = parse(msg.message)
            if not parsed:
                continue
            sender = await msg.get_sender()
            uname = getattr(sender, "username", None)
            name = " ".join(x for x in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if x) \
                or getattr(sender, "title", None) or ""
            metro = METRO_RE.search(msg.message)
            office = OFFICE_RE.search(msg.message)
            offers.append({
                "uid": uid, "user": f"@{uname}" if uname else None, "name": name,
                "time": msg.date.astimezone(MSK).strftime("%d.%m %H:%M"),
                "metro": metro.group(1) if metro else None,
                "office": re.sub(r"\s+", " ", office.group(0)).strip() if office else None,
                "text": re.sub(r"\s+", " ", msg.message)[:280],
                "link": f"https://t.me/{CHAT}/{msg.id}",
                "rates": parsed,
            })
    return offers, days_by_user, n


def build(offers, days_by_user):
    out = {}
    for code in CUR:
        block = {}
        for side in ("sell", "buy"):          # sell: автор продаёт = вы покупаете
            rows = [(o, o["rates"][code][side]) for o in offers if side in o["rates"].get(code, {})]
            if len(rows) >= 4:                 # отсекаем явные опечатки и приманки (±4% от медианы)
                med = statistics.median(v for _, v in rows)
                rows = [(o, v) for o, v in rows if abs(v - med) / med <= 0.04]
            # от каждого автора — только его лучшее свежее объявление
            best = {}
            for o, v in rows:
                cur = best.get(o["uid"])
                if cur is None or (v < cur[1] if side == "sell" else v > cur[1]):
                    best[o["uid"]] = (o, v)
            ranked = sorted(best.values(), key=lambda t: t[1], reverse=(side == "buy"))
            with_office = [t for t in ranked if t[0]["office"]][:TOP]
            items = sorted({id(t[0]): t for t in ranked[:TOP] + with_office}.values(),
                           key=lambda t: t[1], reverse=(side == "buy"))
            block[side] = [{
                "rate": v, "user": o["user"], "name": o["name"], "time": o["time"],
                "metro": o["metro"], "office": o["office"], "link": o["link"], "text": o["text"],
                "days": len(days_by_user.get(o["uid"], ())),
            } for o, v in items]
        out[code] = block
    return out


def main():
    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    data.setdefault("errors", [])
    data["errors"] = [e for e in data["errors"] if not e.startswith("Telegram")]
    if not os.environ.get("TG_SESSION"):
        print("TG_SESSION не задан — пропускаю Telegram")
        return
    try:
        offers, days, n = asyncio.run(collect())
        data["moscow_tg"] = {
            "updated": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"),
            "source": f"t.me/{CHAT}", "scanned": n, "offers": len(offers),
            "history_days": DAYS_HISTORY, "rates": build(offers, days),
        }
        print(f"Telegram: просмотрено {n}, объявлений с курсом {len(offers)}")
        for o in offers[:15]:
            print(" ", o["rates"], "|", o["text"][:120])
    except Exception as e:
        data["errors"].append(f"Telegram: {type(e).__name__}: {e}")
        print("Telegram ОШИБКА:", e)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()

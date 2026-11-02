"""Разбор объявлений из чата @obmenvmsk: таблицы курсов обменников и свободный текст «куплю/продам»."""
import re

# невидимые символы, которыми обменники «ломают» цифры против парсеров
INVISIBLE = re.compile(r"[­​-‏⁠-⁤﻿]")

CUR_RE = re.compile(r"(?<![A-Za-z])(USD|EUR|\$|€|доллар\w*|бакс\w*|евро)", re.I)
RANGE = {"USD": (60, 130), "EUR": (70, 150)}
RATE_RE = re.compile(r"(?<![\d.,])(\d{2,3}[.,]\d{1,2})(?![\d])")

OFFICE_RE = re.compile(
    r"(офис\w*|касс[аеуы]\w*|пункт\w*\s+обмена|обменн\w+\s+пункт\w*|точк[аеуи]\w*|"
    r"\bтц\b|\bбц\b|торгов\w+\s+центр\w*|бизнес[\s-]центр\w*|парковк\w*|"
    r"\b(?:ул\.|улица|пр-т|проспект|пер\.|переулок|шоссе|наб\.|набережная|бульвар|б-р)\s*[А-ЯЁа-яё0-9\-\. ]{2,40}?,?\s*(?:д\.|дом)?\s*\d+|"
    r"работаем\s+(?:с|ежедневно|без\s+выходных)|график\s*:?\s*\d|приезжайте|приходите)", re.I)
METRO_RE = re.compile(r"(?:\b[мМ]\.|\b[мМ]\s|(?i:метро)\s*)\s*([А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё][а-яё]+)*(?:\s[а-яё]{3,}(?![а-яё]*\s*[:|]))?)")
SIDE_RE = re.compile(r"(покупка|покупаю|куплю|скупаю|скупка|buy)|(продажа|продаю|продам|продаём|sell)", re.I)
NUM_RE = re.compile(r"(?<![\d.,])(\d{2,3}(?:[.,]\d{1,2})?)(?![\d])")


def clean(text):
    t = INVISIBLE.sub("", text or "")
    # «8 3,25» -> «83,25»: одиночная цифра, оторванная от курса
    return re.sub(r"(?<![\d.,])(\d) (\d[.,]\d{2})(?![\d])", r"\1\2", t)


def code_of(token):
    t = token.lower()
    return "EUR" if t in ("eur", "€") or t.startswith("евро") else "USD"


def num(s):
    return float(s.replace(",", "."))


def parse_table(text):
    """Таблица «валюта — покупка — продажа». -> {"USD": [{"variant", "buy", "sell"}, ...], "EUR": [...]}
    Пара соседних курсов после метки валюты = одна строка; меньший — покупка обменника, больший — продажа."""
    t = clean(text)
    marks = [(m.start(), m.end(), code_of(m.group(1))) for m in CUR_RE.finditer(t)]
    rates = [(m.start(), m.end(), num(m.group(1))) for m in RATE_RE.finditer(t)]
    rows = {}
    for i, (ms, me, code) in enumerate(marks):
        nxt = marks[i + 1][0] if i + 1 < len(marks) else len(t)
        inside = [r for r in rates if me <= r[0] < nxt]
        if len(inside) < 2:
            continue
        (a0, a1, a), (b0, b1, b) = inside[0], inside[1]
        lo, hi = RANGE[code]
        if not (lo <= a <= hi and lo <= b <= hi) or b0 - a1 > 8 or a0 - me > 40:
            continue
        if abs(a - b) / min(a, b) > 0.06:
            continue
        variant = re.sub(r"[\s|:\-–—()]+", " ", t[me:a0]).strip(" ,.")
        rows.setdefault(code, []).append({"variant": variant, "buy": min(a, b), "sell": max(a, b)})
    return rows


def parse_free(text):
    """Свободный текст: «куплю $ по 81.5», «продам доллары 82,3». -> {"USD": {"buy": x, "sell": y}}"""
    t = clean(text)
    marks = sorted((m.start(), code_of(m.group(1))) for m in CUR_RE.finditer(t))
    sides = [(m.start(), "buy" if m.group(1) else "sell") for m in SIDE_RE.finditer(t)]
    if not marks or not sides:
        return {}
    res = {}
    for m in NUM_RE.finditer(t):
        pos, v = m.start(), num(m.group(1))
        before = [c for p, c in marks if p < pos]
        code = before[-1] if before else marks[0][1] if marks[0][0] - pos < 15 else None
        side = next((sd for p, sd in reversed(sides) if p < pos), None)
        if not code or not side:
            continue
        lo, hi = RANGE[code]
        if lo <= v <= hi:
            res.setdefault(code, {}).setdefault(side, v)
    return res


def parse_offer(text):
    """Единый результат: {code: {"buy", "sell", "variant"}} — основная (первая) строка по каждой валюте,
    плюс "rows" со всеми строками таблицы."""
    table = parse_table(text)
    if table:
        return {c: {**rows[0], "rows": rows} for c, rows in table.items()}
    return {c: {**v, "variant": "", "rows": []} for c, v in parse_free(text).items()}


def office_of(text):
    m = OFFICE_RE.search(clean(text))
    return re.sub(r"\s+", " ", m.group(0)).strip() if m else None


def metro_of(text):
    m = METRO_RE.search(clean(text))
    return m.group(1) if m else None

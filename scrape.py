"""
Лучшие наличные курсы с адресами:
  Минск  — select.by  (USD, EUR, 100 RUB в BYN)
  Москва — ru.myfin.by (USD, EUR в RUB)
Результат -> rates.json рядом со скриптом.
"""
import json, re, datetime, urllib.request, urllib.parse, pathlib, html as htmllib
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
OUT = pathlib.Path(__file__).with_name("rates.json")
MSK = datetime.timezone(datetime.timedelta(hours=3))
MAX_PLACES = 3          # сколько адресов показывать на одну позицию
MAX_AGE_DAYS = 3        # курс отделения старше — не учитываем (Москва)


def get(url, xhr=False, referer=None):
    h = {"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"}
    if xhr:
        h["X-Requested-With"] = "XMLHttpRequest"
        h["Accept"] = "application/json, text/javascript, */*; q=0.01"
    if referer:
        h["Referer"] = referer
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def num(s):
    try:
        return float(str(s).replace(",", ".").replace("\xa0", "").strip())
    except ValueError:
        return None


def best(places, key, highest):
    """Лучший курс по полю key и все точки с этим курсом."""
    vals = [p[key] for p in places if p.get(key)]
    if not vals:
        return None
    top = max(vals) if highest else min(vals)
    hits = [p for p in places if p.get(key) == top]
    # сначала по одному отделению от каждого банка, потом остальные
    seen, first, rest = set(), [], []
    for p in hits:
        (rest if p["bank"] in seen else first).append(p)
        seen.add(p["bank"])
    shown = (first + rest)[:MAX_PLACES]
    clean = [{k: v for k, v in p.items() if k not in ("buy", "sell")} for p in shown]
    return {"rate": top, "count": len(hits), "banks": sorted(seen), "places": clean}


# ---------------- Минск, select.by ----------------
SEL = "https://select.by"
MINSK_COLS = {"USD": (1, 2), "EUR": (3, 4), "RUB": (5, 6)}   # индексы buy/sell в строке API
MINSK_PER = {"USD": 1, "EUR": 1, "RUB": 100}


def minsk():
    page = get(f"{SEL}/minsk/kurs")
    soup = BeautifulSoup(page, "html.parser")
    table = soup.select_one("table.courses-main")
    if not table:
        raise ValueError("не найдена таблица банков")
    banks = []
    for tr in table.select("tr.tablesorter-hasChildRow"):
        name = tr.find("td").get_text(" ", strip=True)
        child = tr.find_next_sibling("tr")
        slide = child.select_one("td.slide[id]") if child else None
        if slide:
            banks.append((name, slide["id"]))
    if not banks:
        raise ValueError("не найден список банков")

    rows = {c: [] for c in MINSK_COLS}
    for bank, bid in banks:
        data = json.loads(get(f"{SEL}/api/minsk/kurs/{bid}", xhr=True, referer=f"{SEL}/minsk/kurs") or "[]")
        for row in data:
            a = BeautifulSoup(row[0], "html.parser")
            link = a.select_one("a.btn-tomap")
            if not link:
                continue
            tel = a.select_one('a[href^="tel:"]')
            title = link.get("data-name", "")
            branch = title.split(":", 1)[1].split(",", 1)[0].strip() if ":" in title else ""
            base = {
                "bank": bank,
                "branch": branch,
                "addr": link.get_text(" ", strip=True),
                "lat": num(link.get("data-x")),
                "lon": num(link.get("data-y")),
                "phone": tel.get_text(strip=True) if tel else None,
            }
            for cur, (ib, isell) in MINSK_COLS.items():
                rows[cur].append({**base, "buy": num(row[ib]), "sell": num(row[isell])})

    res = {}
    for cur, places in rows.items():
        res[cur] = {"per": MINSK_PER[cur], "quote": "BYN",
                    "buy": best(places, "buy", True),      # банк покупает = вы сдаёте
                    "sell": best(places, "sell", False)}   # банк продаёт = вы покупаете
    return res, len(banks)


# ---------------- Москва, ru.myfin.by ----------------
MYFIN = "https://ru.myfin.by"
MOS_CODES = ("USD", "EUR")


def moscow_currency(code):
    """Все отделения банков Москвы со страницы Myfin (с пагинацией), лучший курс + адреса."""
    places, today = [], datetime.datetime.now(MSK).date()
    for page in range(1, 11):
        url = f"{MYFIN}/currency/{code.lower()}/moskva" + (f"?page={page}" if page > 1 else "")
        soup = BeautifulSoup(get(url), "html.parser")
        table = soup.select_one("table.with_department")
        if not table:
            if page == 1:
                raise ValueError("не найдена таблица банков")
            break
        banks = {}
        for tr in table.select("tr[data-bank-alias]"):
            name = tr.select_one("td.bank_name")
            banks[tr.get("data-key")] = (name.get_text(" ", strip=True) if name else tr["data-bank-alias"], tr["data-bank-alias"])
        for tr in table.select("tr.hidden-info-block"):
            if "more_header" in tr.get("class", []):
                continue
            key = next((c[2:] for c in tr.get("class", []) if re.fullmatch(r"tr\d+", c)), None)
            a = tr.find("a")
            vals = [num(td.get_text()) for td in tr.select("td.center")]
            if key not in banks or not a or len(vals) < 2:
                continue
            t = tr.find("time")
            when = None
            if t and t.get("datetime"):
                try:
                    d = datetime.date.fromisoformat(t["datetime"][:10])
                    if (today - d).days > MAX_AGE_DAYS:
                        continue
                except ValueError:
                    pass
                when = t.get_text(strip=True)
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(a.get("href", "")).query)
            bank, alias = banks[key]
            places.append({
                "bank": bank,
                "branch": (qs.get("search_string") or [""])[0].replace("\xa0", " "),
                "addr": re.sub(r"^Москва,\s*", "", a.get_text(" ", strip=True)),
                "updated": when,
                "link": MYFIN + a["href"] if a.get("href", "").startswith("/") else None,
                "buy": vals[0], "sell": vals[1],
            })
        if not soup.select_one(f'.pagination a[href*="page={page + 1}"]'):
            break
    if not places:
        raise ValueError("нет отделений с актуальным курсом")
    return {"per": 1, "quote": "RUB",
            "buy": best(places, "buy", True),
            "sell": best(places, "sell", False)}


def main():
    old = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    now = datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M")
    data = {"minsk": old.get("minsk", {}), "moscow": old.get("moscow", {}), "errors": []}

    try:
        rates, n = minsk()
        data["minsk"] = {"updated": now, "source": "select.by", "banks": n, "rates": rates}
    except Exception as e:
        data["errors"].append(f"Минск (select.by): {e}")

    mos_rates, ok = {k: v for k, v in (data["moscow"] or {}).get("rates", {}).items() if k in MOS_CODES}, False
    for code in MOS_CODES:
        try:
            mos_rates[code] = moscow_currency(code)
            ok = True
        except Exception as e:
            data["errors"].append(f"Москва {code} (myfin): {e}")
    if ok:
        data["moscow"] = {"updated": now, "source": "ru.myfin.by", "rates": mos_rates}

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1)[:3000])
    if data["errors"]:
        print("ОШИБКИ:", *data["errors"], sep="\n")


if __name__ == "__main__":
    main()

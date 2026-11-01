"""
Лучшие наличные курсы с адресами:
  Минск  — select.by  (USD, EUR, 100 RUB в BYN)
  Москва — banki.ru   (USD, EUR в RUB)
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


# ---------------- Москва, banki.ru ----------------
BANKI = "https://www.banki.ru"
MOS_IDS = {"USD": 840, "EUR": 978}


def moscow_currency(code):
    referer = f"{BANKI}/products/currency/cash/{code.lower()}/moskva/"
    offices, now = {}, datetime.datetime.now(MSK)
    # разные сортировки -> в выдачу попадают отделения с лучшей покупкой и с лучшей продажей
    for sort, order in (("buy", "desc"), ("sale", "asc"), ("recommend", "desc")):
        q = urllib.parse.urlencode({
            "sortAttribute": sort, "order": order, "currencyId": MOS_IDS[code], "currencyCode": code,
            "regionUrl": "moskva", "regionId": 4, "isExchangeOffices": 0, "page": 1, "perPage": 100,
            "pagePath": "currencyCashCodeCity", "isPagination": "true"})
        raw = get(f"{BANKI}/products/currencyNodejsApi/getBanksWithOffices/?{q}", xhr=True, referer=referer)
        try:
            j = json.loads(raw)
        except ValueError:
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw))[:160]
            raise ValueError(f"не JSON ({len(raw)} байт): {snippet}")
        for b in j.get("list", []):
            for o in b.get("exchangeOffices") or []:
                ex = o.get("exchange") or {}
                date = ex.get("refreshDate")
                if date:
                    try:
                        if (now - datetime.datetime.fromisoformat(date)).days > MAX_AGE_DAYS:
                            continue
                    except ValueError:
                        pass
                ci, co = o.get("contactInformation") or {}, o.get("coordinates") or {}
                bal = (o.get("currencyBalanceStatus") or {}).get("status")
                offices[o["id"]] = {
                    "bank": b.get("name"),
                    "branch": htmllib.unescape(o.get("name") or ""),
                    "addr": (ci.get("address") or co.get("address") or "").replace("г Москва, ", ""),
                    "metro": co.get("metroStation"),
                    "lat": co.get("latitude"), "lon": co.get("longitude"),
                    "phone": ci.get("phone"),
                    "updated": date[:16].replace("T", " ") if date else None,
                    "stock": bal,
                    "buy": ex.get("buy"), "sell": ex.get("sale"),
                }
    places = list(offices.values())
    if not places:
        raise ValueError("нет отделений")
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

    mos_rates, ok = {k: v for k, v in (data["moscow"] or {}).get("rates", {}).items() if k in MOS_IDS}, False
    for code in MOS_IDS:
        try:
            mos_rates[code] = moscow_currency(code)
            ok = True
        except Exception as e:
            data["errors"].append(f"Москва {code} (banki.ru): {e}")
    if ok:
        data["moscow"] = {"updated": now, "source": "banki.ru", "rates": mos_rates}

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=1)[:3000])
    if data["errors"]:
        print("ОШИБКИ:", *data["errors"], sep="\n")


if __name__ == "__main__":
    main()

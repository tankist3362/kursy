"""
Объявления обменников из чата @obmenvmsk через веб-версию Telegram (без api_id).
Сессия веб-Telegram берётся из секрета TG_WEB_STORAGE (JSON localStorage браузера, где выполнен вход).
Результат: блок moscow_tg в rates.json; «стаж» авторов копится в tg_seen.json.
"""
import os, re, json, time, datetime, pathlib
from tg_parse import parse_offer, office_of, metro_of, clean

CHAT = "obmenvmsk"
HERE = pathlib.Path(__file__).parent
OUT, SEEN = HERE / "rates.json", HERE / "tg_seen.json"
MSK = datetime.timezone(datetime.timedelta(hours=3))
HOURS_FRESH = 24
DAYS_HISTORY = 7
TOP = 12
URL = "https://web.telegram.org/k/#?tgaddr=tg%3A%2F%2Fresolve%3Fdomain%3D" + CHAT

EXTRACT_JS = r"""
() => {
  const SKIP = '.time, .reactions, .bubble-name-rank, .reply, .webpage';
  const blockOf = el => { while (el && getComputedStyle(el).display === 'inline') el = el.parentElement; return el; };
  return [...document.querySelectorAll('.bubble[data-mid]')].map(x => {
    const n = x.querySelector('.colored-name');
    const msg = x.querySelector('.message');
    let text = '';
    if (msg) {
      // склеиваем куски одного блока без пробела, разные блоки (ячейки таблицы, строки) — через пробел
      const w = document.createTreeWalker(msg, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
      let prevBlock = null;
      while (w.nextNode()) {
        const node = w.currentNode;
        let piece = null, host = node;
        if (node.nodeType === 3) { piece = node.nodeValue; host = node.parentElement; }
        else if (node.tagName === 'IMG' && node.classList.contains('emoji')) piece = node.alt || '';
        else continue;
        if (!piece || (host.closest(SKIP) && msg.contains(host.closest(SKIP)))) continue;
        let hid = false;
        for (let e = host; e && e !== msg; e = e.parentElement) if (getComputedStyle(e).display === 'none') { hid = true; break; }
        if (hid) continue;
        const b = blockOf(host);
        text += (prevBlock && b !== prevBlock ? ' ' : '') + piece;
        prevBlock = b;
      }
    }
    return {mid: x.dataset.mid, ts: +x.dataset.timestamp, uid: n ? n.dataset.peerId : null,
            name: n ? (n.querySelector('.peer-title-inner') || n).textContent.trim() : null,
            tag: (x.querySelector('.bubble-name-rank') || {}).textContent || null, text: text.replace(/\s+/g, ' ').trim()};
  });
}
"""


def collect(storage):
    from playwright.sync_api import sync_playwright
    msgs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 1000}, locale="ru-RU",
                                  user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                             "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
        ctx.add_init_script("""(data => { if (location.hostname === 'web.telegram.org' && !sessionStorage.getItem('_seeded')) {
            for (const [k, v] of Object.entries(data)) localStorage.setItem(k, v);
            sessionStorage.setItem('_seeded', '1'); } })(%s)""" % json.dumps(storage))
        page = ctx.new_page()
        page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
        try:
            page.wait_for_selector(".chatlist-container, .chatlist", timeout=45000)
        except Exception:
            page.screenshot(path=str(HERE / "tg_debug.png"))
            raise RuntimeError("веб-Telegram не вошёл в аккаунт — сессию нужно скопировать заново")
        page.goto(URL)
        page.wait_for_selector(".bubble[data-mid]", timeout=45000)
        time.sleep(3)
        border = time.time() - HOURS_FRESH * 3600
        for _ in range(60):                       # листаем вверх, пока не дойдём до суток назад
            for m in page.evaluate(EXTRACT_JS):
                msgs[m["mid"]] = m
            oldest = min((m["ts"] for m in msgs.values() if m["ts"]), default=time.time())
            if oldest < border:
                break
            page.evaluate("() => { const s = document.querySelector('.bubbles .scrollable-y') "
                          "|| document.querySelector('.bubbles .scrollable'); if (s) s.scrollTop = 0; }")
            time.sleep(2.5)
        page.screenshot(path=str(HERE / "tg_debug.png"))
        browser.close()
    return list(msgs.values())


def msg_link(mid):
    try:
        mid = int(mid)
        return f"https://t.me/{CHAT}/{mid % 4294967296 if mid > 4294967296 else mid}"
    except (TypeError, ValueError):
        return f"https://t.me/{CHAT}"


def build(msgs):
    now = time.time()
    today = datetime.datetime.now(MSK).date()
    seen = json.loads(SEEN.read_text("utf-8")) if SEEN.exists() else {}
    for m in msgs:
        if m["uid"]:
            d = datetime.datetime.fromtimestamp(m["ts"], MSK).date().isoformat()
            seen.setdefault(m["uid"], [])
            if d not in seen[m["uid"]]:
                seen[m["uid"]].append(d)
    cutoff = (today - datetime.timedelta(days=DAYS_HISTORY - 1)).isoformat()
    seen = {u: sorted(x for x in ds if x >= cutoff) for u, ds in seen.items()}
    seen = {u: ds for u, ds in seen.items() if ds}
    SEEN.write_text(json.dumps(seen, ensure_ascii=False), "utf-8")

    offers = []
    for m in msgs:
        if not m["uid"] or now - m["ts"] > HOURS_FRESH * 3600:
            continue
        parsed = parse_offer(m["text"])
        if not parsed:
            continue
        offers.append({**m, "parsed": parsed})

    out = {}
    for code in ("USD", "EUR"):
        block = {}
        for side in ("sell", "buy"):              # sell: обменник продаёт = вы покупаете
            best = {}
            for o in offers:
                v = o["parsed"].get(code, {}).get(side)
                if v is None:
                    continue
                cur = best.get(o["uid"])
                if cur is None or o["ts"] > cur[0]["ts"]:   # у автора берём самое свежее объявление
                    best[o["uid"]] = (o, v)
            items = sorted(best.values(), key=lambda t: t[1], reverse=(side == "buy"))
            verified_or_office = [t for t in items if t[0]["tag"] or office_of(t[0]["text"])]
            keep = {t[0]["uid"]: t for t in items[:TOP] + verified_or_office[:TOP]}
            items = sorted(keep.values(), key=lambda t: t[1], reverse=(side == "buy"))
            block[side] = [{
                "rate": v, "variant": o["parsed"][code].get("variant", ""),
                "rows": [{"variant": r["variant"], "buy": r["buy"], "sell": r["sell"]} for r in o["parsed"][code].get("rows", [])],
                "user": None, "name": o["name"], "verified": bool(o["tag"]), "tag": (o["tag"] or "").strip() or None,
                "time": datetime.datetime.fromtimestamp(o["ts"], MSK).strftime("%d.%m %H:%M"),
                "metro": metro_of(o["text"]), "office": office_of(o["text"]),
                "link": msg_link(o["mid"]), "text": re.sub(r"\s+", " ", clean(o["text"]))[:300],
                "days": len(seen.get(o["uid"], [])),
            } for o, v in items]
        out[code] = block
    return out, len(offers)


def main():
    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {}
    data["errors"] = [e for e in data.get("errors", []) if not e.startswith("Telegram")]
    raw = os.environ.get("TG_WEB_STORAGE")
    if not raw:
        print("TG_WEB_STORAGE не задан — пропускаю веб-Telegram")
        return
    try:
        storage = json.loads(raw)
        msgs = collect(storage)
        rates, n_offers = build(msgs)
        data["moscow_tg"] = {"updated": datetime.datetime.now(MSK).strftime("%Y-%m-%d %H:%M"),
                             "source": f"t.me/{CHAT}", "scanned": len(msgs), "offers": n_offers,
                             "history_days": DAYS_HISTORY, "rates": rates}
        print(f"Telegram: сообщений {len(msgs)}, объявлений с курсом {n_offers}")
        for m in sorted(msgs, key=lambda m: m["ts"])[-8:]:
            print(" ", m["name"], "|", m["tag"], "|", parse_offer(m["text"]), "|", clean(m["text"])[:100])
    except Exception as e:
        data["errors"].append(f"Telegram: {type(e).__name__}: {str(e)[:200]}")
        print("Telegram ОШИБКА:", e)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")


if __name__ == "__main__":
    main()

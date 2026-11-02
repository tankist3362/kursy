"""
Получение api_id / api_hash на my.telegram.org без браузера (запуск в Codespaces).
python tg_app.py -> номер телефона -> код, который придёт в Telegram (чат «Telegram»).
Если приложение уже есть, просто покажет его коды; если нет — создаст.
Коды ниоткуда не отправляются, кроме самого my.telegram.org.
"""
import re, sys, html
import urllib.request, urllib.parse, http.cookiejar

BASE = "https://my.telegram.org"
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
op.addheaders = [("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"),
                 ("X-Requested-With", "XMLHttpRequest"), ("Origin", BASE), ("Referer", BASE + "/auth")]


def post(path, data):
    with op.open(BASE + path, urllib.parse.urlencode(data).encode()) as r:
        return r.read().decode("utf-8", "replace")


def get(path):
    with op.open(BASE + path) as r:
        return r.read().decode("utf-8", "replace")


def show_codes(page):
    def field(label):
        m = re.search(label + r".*?<span[^>]*>\s*(?:<strong>)?([^<\s]+)", page, re.S)
        return html.unescape(m.group(1)) if m else None
    api_id, api_hash = field("App api_id"), field("App api_hash")
    if api_id and api_hash:
        print("\n=== Готово ===\napi_id:  ", api_id, "\napi_hash:", api_hash,
              "\nЗапишите их себе и переходите к: python login.py")
        return True
    return False


phone = input("Номер телефона (+7...): ").strip()
r = post("/auth/send_password", {"phone": phone})
if "random_hash" not in r:
    sys.exit("my.telegram.org ответил: " + r.strip()[:200])
random_hash = re.search(r'"random_hash"\s*:\s*"([^"]+)"', r).group(1)
code = input("Код из Telegram (придёт в чат «Telegram»): ").strip()
r = post("/auth/login", {"phone": phone, "random_hash": random_hash, "password": code})
if r.strip() != "true":
    sys.exit("Вход не удался: " + r.strip()[:200])
print("Вход выполнен.")

page = get("/apps")
if show_codes(page):
    sys.exit()

m = re.search(r'name="hash"\s+value="([^"]+)"', page)
if not m:
    sys.exit("Не нашёл форму создания приложения. Начало страницы:\n" + re.sub(r"\s+", " ", page)[:500])
r = post("/apps/create", {"hash": m.group(1), "app_title": "kursy3362", "app_shortname": "kursy3362",
                          "app_url": "", "app_platform": "other", "app_desc": ""})
if r.strip():
    print("Ответ на создание:", re.sub(r"\s+", " ", r)[:300])
if not show_codes(get("/apps")):
    sys.exit("Приложение не появилось — пришлите Claude текст ответа выше (без кодов входа).")

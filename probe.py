import urllib.request, re, sys
from bs4 import BeautifulSoup
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36","Accept-Language":"ru"}
h=urllib.request.urlopen(urllib.request.Request("https://ru.myfin.by/currency/usd/moskva",headers=UA),timeout=40).read().decode()
s=BeautifulSoup(h,"html.parser")
for i,t in enumerate(s.find_all("table")[:6]):
    rows=t.find_all("tr")
    print("TABLE",i,t.get("class"),t.get("id"),len(rows))
    for r in rows[:4]: print("   ",re.sub(r"\s+"," ",r.get_text(" ",strip=True))[:200])
    if len(rows)>2: print("   HTML:",re.sub(r"\s+"," ",str(rows[2]))[:1500])
for m in set(re.findall(r'["\'](/[a-z0-9_/\-]*(?:ajax|api|offices|branch|filial|map)[a-z0-9_/\-\.]*)',h))[:30]: print("URL",m)
for k in ["адрес","address","data-bank","data-id","otdelen","filial"]:
    i=h.find(k); print("KEY",k,i, re.sub(r"\s+"," ",h[max(0,i-200):i+300]) if i>0 else "")

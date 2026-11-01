import urllib.request, re
from bs4 import BeautifulSoup
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36","Accept-Language":"ru"}
h=urllib.request.urlopen(urllib.request.Request("https://ru.myfin.by/currency/usd/moskva",headers=UA),timeout=40).read().decode()
t=BeautifulSoup(h,"html.parser").select("table.with_department")[0]
rows=t.find_all("tr")
from collections import Counter
print("CLASSES",Counter(" ".join(r.get("class") or []) for r in rows).most_common(12))
for r in rows[3:9]: print("ROW",re.sub(r"\s+"," ",str(r))[:1200])
banks=[r for r in rows if "row" in (r.get("class") or []) and r.get("data-bank-alias")]
print("BANKS",len(banks))
pg=[a.get("href") for a in BeautifulSoup(h,"html.parser").select(".pagination a")][:10]; print("PAGES",pg)

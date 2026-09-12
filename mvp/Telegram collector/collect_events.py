#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сбор ПРОДАЮЩИХ постов из @postypashki_old
Период: 31.07.2026 – 10.09.2026
Фильтр: взвешенный словарь, порог >= 3 и хотя бы один маркер веса >= 2
Выход: events.csv
"""

import requests, time, re, csv
from bs4 import BeautifulSoup
from datetime import datetime

# ============ КОНФИГ ============
CHANNEL = "postypashki_old"
START   = datetime(2026, 7, 31)
END     = datetime(2026, 9, 10, 23, 59)
OUT     = "events.csv"
THRESHOLD = 3          # минимальный суммарный вес
MIN_STRONG = 2         # минимум один маркер с весом >= 2

# ============ ВЗВЕШЕННЫЙ СЛОВАРЬ ============
# вес 3 — явная продажа
# вес 2 — сильный маркер
# вес 1 — слабый маркер
WEIGHTS = {
    # --- вес 3: прямая продажа ---
    "наши курсы": 3, "наш курс": 3, "наших курсов": 3,
    "записывайся": 3, "записаться": 3, "запись на курс": 3,
    "покупка курса": 3, "по покупке курсов": 3,
    "скидка": 3, "скидки": 3, "скидку": 3, "скидкам": 3,
    "распродажа": 3, "промокод": 3,
    "набор на курс": 3, "открыт набор": 3, "открывают набор": 3,
    "стартует": 3, "старт": 3, "поток": 3, "потоки": 3,
    "новый поток": 3, "следующий поток": 3,
    "количество мест ограничено": 3,
    "для вопросов и покупок": 3,
    "финальная распродажа": 3,
    "успей": 3, "успейте": 3, "торопитесь": 3,

    # --- вес 2: сильный маркер ---
    "последние часы": 2, "последний день скидки": 2,
    "выгодный момент": 2, "специальная цена": 2,
    "самый выгодный": 2,
    "пет проекты": 2, "пет-проекты": 2, "мини проекты": 2,
    "портфолио": 2, "разбор реальных": 2,
    "пробные собесы": 2, "пробный собес": 2,
    "сопровождение": 2, "рефералка": 2,
    "программа курса": 2,
    "не тянем": 2,

    # --- вес 1: слабый маркер ---
    "разберем": 1, "разберём": 1,
    "научимся": 1, "научишься": 1,
    "овладеть": 1, "изучаем": 1, "изучить": 1, "освоить": 1,
    "курс заточен": 1, "теория будет разобрана": 1,
    "отзывы": 1, "отзыв": 1,
    "подробности": 1,
}

PROMO_RE    = re.compile(r"\b([A-ZА-Я]{3,12}\d{0,4})\b")
DISCOUNT_RE = re.compile(r"(\d{1,2})\s?%")
PRICE_RE    = re.compile(r"(\d[\d\s]{2,7})\s?(?:₽|руб|р\.|рублей)")

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ============ ВЗВЕШЕННАЯ КЛАССИФИКАЦИЯ ============
def sale_score(text: str) -> tuple[int, list[str], bool]:
    """
    Возвращает (суммарный вес, найденные слова, есть ли сильный маркер).
    """
    t = text.lower()
    total = 0
    found = []
    has_strong = False
    for phrase, w in WEIGHTS.items():
        if phrase in t:
            total += w
            found.append(f"{phrase}({w})")
            if w >= MIN_STRONG:
                has_strong = True
    return total, found, has_strong


def is_sale_post(text: str) -> bool:
    total, _, strong = sale_score(text)
    return total >= THRESHOLD and strong


# ============ ИЗВЛЕЧЕНИЕ СУЩНОСТЕЙ ============
def extract(text: str) -> dict:
    prices = []
    for m in PRICE_RE.findall(text):
        try:
            prices.append(int(m.replace(" ", "")))
        except ValueError:
            pass
    return {
        "promo_codes": ";".join(list(set(PROMO_RE.findall(text)))[:5]),
        "discounts": ";".join(str(x) for x in DISCOUNT_RE.findall(text)),
        "prices": ";".join(str(x) for x in prices),
    }


# ============ ПАРСЕР ============
def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def fetch(before=None):
    url = f"https://t.me/s/{CHANNEL}"
    if before:
        url += f"?before={before}"
    return requests.get(url, headers=HEADERS, timeout=30).text


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for wrap in soup.select(".tgme_widget_message_wrap"):
        try:
            msg = wrap.select_one(".tgme_widget_message")
            if not msg or not msg.get("data-post"):
                continue
            mid = int(msg["data-post"].split("/")[-1])
            t_el = msg.select_one(".tgme_widget_message_text")
            text = t_el.get_text(" ", strip=True) if t_el else ""
            dt = None
            for t in msg.find_all("time"):
                if t.has_attr("datetime"):
                    dt = parse_date(t["datetime"])
                    break
            v_el = msg.select_one(".tgme_widget_message_views")
            views = v_el.get_text(strip=True) if v_el else ""
            out.append({
                "msg_id": mid,
                "date": dt,
                "date_iso": dt.isoformat() if dt else "",
                "views": views,
                "text": text,
                "url": f"https://t.me/{CHANNEL}/{mid}",
            })
        except Exception:
            continue
    return out


def collect():
    allp, before = [], None
    for page in range(200):
        try:
            html = fetch(before)
        except Exception as e:
            print("[!]", e); break
        batch = parse(html)
        if not batch:
            break
        allp.extend(batch)
        oldest_id = min(p["msg_id"] for p in batch)
        oldest_dt = min((p["date"] for p in batch if p["date"]), default=None)
        print(f"[i] стр.{page+1}: +{len(batch)}, всего {len(allp)}, старейший {oldest_dt}")
        if oldest_dt and oldest_dt < START:
            print(f"[i] Дошли до {oldest_dt} — стоп")
            break
        if oldest_id == before:
            break
        before = oldest_id
        time.sleep(1)

    seen, uniq = set(), []
    for p in sorted(allp, key=lambda x: x["msg_id"]):
        if p["msg_id"] in seen:
            continue
        seen.add(p["msg_id"]); uniq.append(p)
    return uniq


# ============ MAIN ============
def main():
    print(f"=== {CHANNEL} | {START.date()} – {END.date()} ===")
    posts = collect()
    print(f"[i] всего постов собрано: {len(posts)}")

    in_period = [p for p in posts if p["date"] and START <= p["date"] <= END]
    print(f"[i] постов в периоде: {len(in_period)}")

    events = []
    for p in in_period:
        total, words, strong = sale_score(p["text"])
        if total >= THRESHOLD and strong:
            p["score"] = total
            p["matched"] = ";".join(words)
            events.append(p)

    print(f"[✓] продающих постов: {len(events)}")
    print(f"[i] отфильтровано контентных: {len(in_period) - len(events)}")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        fields = ["msg_id", "date", "views", "score", "matched",
                  "promo_codes", "discounts", "prices", "url", "text"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            ex = extract(e["text"])
            w.writerow({
                "msg_id": e["msg_id"],
                "date": e["date_iso"],
                "views": e["views"],
                "score": e["score"],
                "matched": e["matched"],
                "promo_codes": ex["promo_codes"],
                "discounts": ex["discounts"],
                "prices": ex["prices"],
                "url": e["url"],
                "text": e["text"][:500],
            })
    print(f"[✓] записано в {OUT}: {len(events)} строк")

    print("\n=== Топ по весу ===")
    for e in sorted(events, key=lambda x: -x["score"])[:10]:
        print(f"  [{e['score']}] {e['date_iso'][:10]}  {e['url']}")
        print(f"      matched: {e['matched'][:120]}")
        print(f"      {e['text'][:100]}...")


if __name__ == "__main__":
    main()
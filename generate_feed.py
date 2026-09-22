"""
Lion Auctions → Meta Vehicles catalog feed generator.

Scrapes lionauctions.com listings and writes feed.xml in Meta's
Automotive Inventory Ads format. Runs on GitHub Actions hourly.
"""
from __future__ import annotations

import asyncio
import html
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

BASE = "https://lionauctions.com"
SITEMAPS = [f"{BASE}/listings-sitemap.xml", f"{BASE}/listings-sitemap2.xml"]
OUT = Path("public/feed.xml")
CONCURRENCY = 8
TIMEOUT = 30.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; LionAuctionsFeedBot/1.0; "
    "+https://github.com/) - Meta catalog feed generator"
)

# --- ka → Meta enum maps ---
FUEL = {"ბენზინი": "GASOLINE", "დიზელი": "DIESEL", "ჰიბრიდი": "HYBRID",
        "ელექტრო": "ELECTRIC", "გაზი": "OTHER"}
TRANS = {"ავტომატიკა": "AUTOMATIC", "მექანიკა": "MANUAL", "CVT": "CVT"}
DRIVE = {"ოთხივე წამყვანი": "AWD", "წინა წამყვანი": "FWD",
         "უკანა წამყვანი": "RWD", "4x4": "FOUR_WD"}
COND = {"დაზიანებული": "FAIR", "ვარგისი": "GOOD", "ახალი": "EXCELLENT",
        "გამოყენებული": "GOOD"}
BODY = {"ჯიპი": "SUV", "სედანი": "SEDAN", "კუპე": "COUPE",
        "ჰეტჩბექი": "HATCHBACK", "უნივერსალი": "WAGON",
        "მინივენი": "VAN", "პიკაპი": "PICKUP",
        "კაბრიოლეტი": "CONVERTIBLE", "ქროსოვერი": "CROSSOVER"}

# Colors (Georgian → English, for Meta consistency)
COLOR = {
    "თეთრი": "White", "შავი": "Black", "ნაცრისფერი": "Gray",
    "ვერცხლისფერი": "Silver", "წითელი": "Red", "ლურჯი": "Blue",
    "მწვანე": "Green", "ყვითელი": "Yellow", "ყავისფერი": "Brown",
    "ოქროსფერი": "Gold", "ნარინჯისფერი": "Orange", "ბეჟი": "Beige",
    "იისფერი": "Purple", "ვარდისფერი": "Pink",
}


async def get_urls(client: httpx.AsyncClient) -> list[str]:
    urls: list[str] = []
    for sm in SITEMAPS:
        r = await client.get(sm)
        r.raise_for_status()
        found = re.findall(r"<loc>([^<]+)</loc>", r.text)
        listing = [u for u in found if "/listings/" in u and not u.rstrip("/").endswith("listings")]
        urls.extend(listing)
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def parse_listing(html_text: str, url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html_text, "lxml")

    # Title widget: "#12345 MAKE MODEL YEAR"
    title_el = soup.select_one(".elementor-widget-motors-single-listing-classified-title")
    title_text = " ".join(title_el.stripped_strings) if title_el else ""
    tm = re.match(r"^#(\d+)\s+(.+?)\s+((?:19|20)\d{2})$", title_text)
    if not tm:
        return None
    lot_id = tm.group(1)
    make_model_str = tm.group(2)
    year = tm.group(3)

    # Spec list
    specs: dict[str, str] = {}
    for li in soup.select(".elementor-widget-motors-single-listing-classified-listing-data li.data-list-item"):
        label_el = li.select_one(".item-label")
        val_el = li.select_one(".heading-font") or li.select_one("span:last-child")
        if label_el and val_el:
            label = label_el.get_text(strip=True)
            value = val_el.get_text(strip=True) or val_el.get("title")
            if label and value:
                specs[label] = value

    # Price widget
    price_el = soup.select_one(".elementor-widget-motors-single-listing-classified-price")
    for tag in (price_el.select("script, style") if price_el else []):
        tag.decompose()
    price_text = " ".join(price_el.stripped_strings) if price_el else ""
    sold_now = bool(re.search(r"\bsold\b|გაიყიდა", price_text, re.I))
    usd_prices = [
        int(m.replace(" ", "").replace(",", ""))
        for m in re.findall(r"\$\s?([\d\s,]+)", price_text)
    ]
    usd_prices = [p for p in usd_prices if p > 100]

    # Gallery images
    gallery = soup.select_one(".elementor-widget-motors-single-listing-gallery")
    imgs: list[str] = []
    if gallery:
        for tag in gallery.select("a[href], img"):
            u = tag.get("href") if tag.name == "a" else tag.get("src")
            if u and "/wp-content/uploads/" in u and re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I):
                imgs.append(u)
    # keep only originals (no -798x466 suffixes)
    full = [u for u in imgs if not re.search(r"-\d+x\d+\.", u)]
    imgs = list(dict.fromkeys(full)) if full else list(dict.fromkeys(imgs))
    imgs = imgs[:20]

    # Description (fallback to meta)
    desc_meta = ""
    md = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
    if md:
        desc_meta = md.get("content", "")

    vin = specs.get("VIN:") or specs.get("VIN") or ""
    if not vin:
        m = re.search(r"VIN[:\s]+([A-HJ-NPR-Z0-9]{11,17})", html_text)
        vin = m.group(1) if m else ""

    make = specs.get("მწარმოებელი", "").strip()
    model = specs.get("მოდელი", "") or make_model_str.replace(make, "").strip()

    return {
        "url": url,
        "lot_id": lot_id,
        "year": year,
        "make": make,
        "model": model,
        "mileage": specs.get("გარბენი", ""),
        "category": specs.get("კატეგორია", ""),
        "fuel": specs.get("საწვავის ტიპი", ""),
        "transmission": specs.get("გადაცემათა კოლოფი", ""),
        "drive": specs.get("წამყვანი თვლები", ""),
        "exterior_color": specs.get("ექსტერიერის ფერი", ""),
        "interior_color": specs.get("ინტერიერის ფერი", ""),
        "engine": specs.get("ძრავი", ""),
        "condition_ka": specs.get("მდგომარეობა", ""),
        "status_ka": specs.get("სტატუსი", ""),
        "customs": specs.get("განბაჟება", ""),
        "vin": vin,
        "starting_bid_usd": usd_prices[0] if usd_prices else None,
        "buy_now_usd": usd_prices[1] if len(usd_prices) > 1 else None,
        "sold_now": sold_now,
        "images": imgs,
        "description_meta": desc_meta,
    }


def mileage_km(raw: str) -> tuple[int, str]:
    if not raw:
        return 0, "KM"
    m = re.search(r"([\d\s,]+)", raw)
    if not m:
        return 0, "KM"
    num = int(re.sub(r"[^\d]", "", m.group(1)) or "0")
    if "mi" in raw.lower():
        return round(num * 1.60934), "KM"
    return num, "KM"


def color_en(ka: str) -> str:
    return COLOR.get(ka.strip(), ka.strip())


def xml_escape(s: Any) -> str:
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def build_item(v: dict[str, Any]) -> str | None:
    price = v.get("buy_now_usd") or v.get("starting_bid_usd")
    if not price or not v.get("make") or not v.get("model"):
        return None
    mi_val, mi_unit = mileage_km(v.get("mileage", ""))
    imgs = v.get("images") or []
    img_lines = []
    for i, u in enumerate(imgs[:20]):
        tag = "image_link" if i == 0 else "additional_image_link"
        img_lines.append(f"    <{tag}>{xml_escape(u)}</{tag}>")

    parts = [
        v.get("condition_ka") and f"მდგომარეობა: {v['condition_ka']}",
        v.get("status_ka") and f"სტატუსი: {v['status_ka']}",
        v.get("customs") and f"განბაჟება: {v['customs']}",
        v.get("engine") and f"ძრავი: {v['engine']}L",
        v.get("starting_bid_usd") and f"საწყისი ბიდი: ${v['starting_bid_usd']}",
        v.get("buy_now_usd") and f"ყიდვის ფასი: ${v['buy_now_usd']}",
    ]
    desc = (v.get("description_meta") or "") + " · " + " · ".join(p for p in parts if p)
    desc = desc.strip(" ·")[:5000]

    availability = "out of stock" if v.get("sold_now") else "in stock"
    title = f"{v['year']} {v['make']} {v['model']}"

    return "\n".join([
        "  <item>",
        f"    <id>{xml_escape(v.get('lot_id') or v.get('vin'))}</id>",
        f"    <title>{xml_escape(title)}</title>",
        f"    <description>{xml_escape(desc)}</description>",
        f"    <link>{xml_escape(v['url'])}</link>",
        *img_lines,
        f"    <make>{xml_escape(v['make'])}</make>",
        f"    <model>{xml_escape(v['model'])}</model>",
        f"    <year>{xml_escape(v['year'])}</year>",
        f"    <vin>{xml_escape(v.get('vin', ''))}</vin>",
        "    <mileage>",
        f"      <value>{mi_val}</value>",
        f"      <unit>{mi_unit}</unit>",
        "    </mileage>",
        f"    <body_style>{BODY.get(v.get('category', ''), 'OTHER')}</body_style>",
        f"    <fuel_type>{FUEL.get(v.get('fuel', ''), 'OTHER')}</fuel_type>",
        f"    <transmission>{TRANS.get(v.get('transmission', ''), 'OTHER')}</transmission>",
        f"    <drivetrain>{DRIVE.get(v.get('drive', ''), 'OTHER')}</drivetrain>",
        f"    <exterior_color>{xml_escape(color_en(v.get('exterior_color', '')))}</exterior_color>",
        f"    <interior_color>{xml_escape(color_en(v.get('interior_color', '')))}</interior_color>",
        f"    <price>{price}.00 USD</price>",
        "    <condition>used</condition>",
        f"    <state_of_vehicle>{COND.get(v.get('condition_ka', ''), 'GOOD')}</state_of_vehicle>",
        f"    <availability>{availability}</availability>",
        "    <dealer_name>Lion Auctions</dealer_name>",
        "    <dealer_communication_channel>WEBSITE</dealer_communication_channel>",
        "  </item>",
    ])


async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> dict[str, Any] | None:
    async with sem:
        try:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            return parse_listing(r.text, url)
        except Exception as e:
            print(f"[warn] {url}: {e}", file=sys.stderr)
            return None


async def main() -> int:
    t0 = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    limits = httpx.Limits(max_connections=CONCURRENCY * 2, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=TIMEOUT, headers={"User-Agent": USER_AGENT},
        limits=limits, follow_redirects=True,
    ) as client:
        urls = await get_urls(client)
        print(f"[info] {len(urls)} URLs from sitemaps", file=sys.stderr)
        sem = asyncio.Semaphore(CONCURRENCY)
        tasks = [fetch_one(client, sem, u) for u in urls]
        results: list[dict[str, Any]] = []
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            v = await coro
            if v:
                results.append(v)
            if i % 100 == 0:
                print(f"[info] scraped {i}/{len(urls)}  ok:{len(results)}", file=sys.stderr)

    # Filter out sold listings that Meta shouldn't advertise
    active = [v for v in results if not v.get("sold_now")]
    items_xml = [build_item(v) for v in active]
    items_xml = [x for x in items_xml if x]

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0">\n'
        '<channel>\n'
        '<title>Lion Auctions — Vehicle Catalog</title>\n'
        f'<link>{BASE}</link>\n'
        '<description>Auto-generated vehicles feed for Meta Commerce Manager</description>\n'
        + "\n".join(items_xml)
        + "\n</channel>\n</rss>\n"
    )
    OUT.write_text(xml, encoding="utf-8")
    dt = time.time() - t0
    print(
        f"[done] total_scraped={len(results)}  active={len(active)}  in_feed={len(items_xml)}  "
        f"file={OUT}  bytes={len(xml.encode('utf-8'))}  seconds={dt:.1f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))


import json
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.vreb.org/current-statistics"
DATA_FILE = Path("market-data.json")

MONTHS = (
    "January February March April May June July August "
    "September October November December"
).split()


def number(value):
    return int(value.replace(",", ""))


def extract(pattern, text, label):
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError(f"Cannot verify {label}")
    return match


def main():
    print("Checking VREB current statistics...")

    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={
            "User-Agent": "DayTeamMarketDashboard/1.0"
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    heading = soup.find(
        string=re.compile(
            r"Victoria Real Estate Market Report for",
            re.IGNORECASE,
        )
    )

    if not heading:
        raise ValueError("Market report heading not found")

    heading_text = heading.strip()

    period = extract(
        r"Report for\s+(" + "|".join(MONTHS) + r")\s+(\d{4})",
        heading_text,
        "reporting month",
    )

    month = period.group(1).capitalize()
    year = int(period.group(2))

    current_period = year * 12 + MONTHS.index(month)

    existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))

    old_month = existing.get("reporting_month")
    old_year = existing.get("reporting_year")

    if old_month in MONTHS and isinstance(old_year, int):
        old_period = old_year * 12 + MONTHS.index(old_month)
        if current_period <= old_period:
            print("No newer monthly report. No changes.")
            return

    # Read only the current report section.
    report = heading.parent
    parts = []

    for element in report.next_elements:
        if getattr(element, "name", None) == "h4":
            break

        if getattr(element, "name", None) == "p":
            content = element.get_text(" ", strip=True)
            if content:
                parts.append(content)

    text = " ".join(parts)

    if len(text) < 500:
        raise ValueError("Report text is incomplete")

    sales = extract(
        r"A total of\s+([\d,]+)\s+properties were sold"
        r".{0,150}?([\d.]+)\s+per cent fewer",
        text,
        "monthly sales",
    )

    inventory = extract(
        r"There were\s+([\d,]+)\s+active listings"
        r".{0,250}?([\d.]+)\s+per cent increase",
        text,
        "active listings",
    )

    detached = extract(
        r"benchmark value for a single family home"
        r".{0,400}?increased by\s+([\d.]+)\s+per cent"
        r"\s+to\s+\$([\d,]+)",
        text,
        "detached benchmark",
    )

    condo = extract(
        r"benchmark value for a condominium"
        r".{0,400}?decreased by\s+([\d.]+)\s+per cent"
        r"\s+to\s+\$([\d,]+)",
        text,
        "condominium benchmark",
    )

    stats = {
        "total_sales": number(sales.group(1)),
        "total_sales_yoy_percent": -float(sales.group(2)),
        "active_listings": number(inventory.group(1)),
        "active_listings_yoy_percent": float(inventory.group(2)),
        "victoria_core_detached_benchmark":
            number(detached.group(2)),
        "victoria_core_detached_yoy_percent":
            float(detached.group(1)),
        "victoria_core_condo_benchmark":
            number(condo.group(2)),
        "victoria_core_condo_yoy_percent":
            -float(condo.group(1)),
    }

    # Conservative sanity checks.
    if not 100 <= stats["total_sales"] <= 3000:
        raise ValueError("Sales outside expected range")

    if not 500 <= stats["active_listings"] <= 15000:
        raise ValueError("Inventory outside expected range")

    for key in (
        "victoria_core_detached_benchmark",
        "victoria_core_condo_benchmark",
    ):
        if not 100000 <= stats[key] <= 5000000:
            raise ValueError(f"Unusual benchmark: {key}")

    for key, value in stats.items():
        if key.endswith("_yoy_percent") and abs(value) > 80:
            raise ValueError(f"Unusual annual change: {key}")

    updated = {
        "status": "verified",
        "reporting_month": month,
        "reporting_year": year,
        "last_updated": date.today().isoformat(),
        "source": "Victoria Real Estate Board",
        "source_url": SOURCE_URL,
        "statistics": stats,
    }

    DATA_FILE.write_text(
        json.dumps(updated, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Prepared {month} {year} market statistics")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Update stopped safely: {error}", file=sys.stderr)
        sys.exit(1)

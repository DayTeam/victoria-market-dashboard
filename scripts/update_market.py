
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.vreb.org/current-statistics"
DATA_FILE = Path("market-data.json")

MONTHS = (
    "January February March April May June July August "
    "September October November December"
).split()

NUMBER = r"([\d,]+)"
PERCENT = r"(\d+(?:\.\d+)?)"

DIRECTION = {
    "increased": 1,
    "increase": 1,
    "more": 1,
    "higher": 1,
    "rose": 1,
    "decreased": -1,
    "decrease": -1,
    "fewer": -1,
    "lower": -1,
    "fell": -1,
}


def extract(pattern, text, label):
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.DOTALL
    )
    if not match:
        raise ValueError(
            f"Cannot reliably extract {label}"
        )
    return match


def integer(value):
    return int(value.replace(",", ""))


def signed_percent(direction, amount):
    word = direction.lower()
    if word not in DIRECTION:
        raise ValueError(
            f"Unknown percentage direction: {word}"
        )
    return DIRECTION[word] * float(amount)


def signed_percent(direction, amount):
    # Existing code stays here


def get_report():
    # NEW replacement function goes here
    # including all the code I provided


def extract_sales(text):
    # Existing code continues here


def extract_sales(text):
    match = extract(
        r"A total of\s+" + NUMBER +
        r"\s+properties were sold"
        r".{0,200}?" + PERCENT +
        r"\s+per cent\s+(fewer|more)"
        r"\s+than",
        text,
        "total sales and annual change"
    )

    return (
        integer(match.group(1)),
        signed_percent(
            match.group(3),
            match.group(2)
        )
    )


def extract_inventory(text):
    match = extract(
        r"There were\s+" + NUMBER +
        r"\s+active listings"
        r".{0,400}?"
        r"(an?\s+)?(increase|decrease)"
        r"\s+of\s+" + PERCENT +
        r"\s+per cent\s+"
        r"(?:from|compared to).*?"
        r"(?:at the end of|in)\s+"
        r"(" + "|".join(MONTHS) + r")"
        r"\s+(\d{4})",
        text,
        "active listings annual change"
    )

    return (
        integer(match.group(1)),
        signed_percent(
            match.group(3),
            match.group(4)
        ),
        match.group(5).capitalize(),
        int(match.group(6))
    )


def extract_benchmark(text, property_type):
    if property_type == "detached":
        anchor = (
            r"benchmark value for a single family home"
            r"\s+in the Victoria Core"
        )
    else:
        anchor = (
            r"benchmark value for a condominium"
            r"\s+in the Victoria Core area"
        )

    match = extract(
        anchor +
        r".{0,500}?"
        r"(increased|decreased)\s+by\s+" +
        PERCENT +
        r"\s+per cent\s+to\s+\$" +
        NUMBER,
        text,
        property_type + " benchmark"
    )

    return (
        integer(match.group(3)),
        signed_percent(
            match.group(1),
            match.group(2)
        )
    )


def validate(stats):
    if not 100 <= stats["total_sales"] <= 3000:
        raise ValueError("Unusual sales total")

    if not 500 <= stats["active_listings"] <= 15000:
        raise ValueError("Unusual inventory total")

    for key in (
        "victoria_core_detached_benchmark",
        "victoria_core_condo_benchmark"
    ):
        if not 100000 <= stats[key] <= 5000000:
            raise ValueError(
                f"Unusual benchmark price: {key}"
            )

    for key, value in stats.items():
        if key.endswith("_yoy_percent"):
            if abs(value) > 80:
                raise ValueError(
                    f"Unusual annual change: {key}"
                )


def main():
    print("Checking official VREB statistics...")

    existing = json.loads(
        DATA_FILE.read_text(encoding="utf-8")
    )

    month, year, report = get_report()

    print(f"VREB report found: {month} {year}")

    current_period = (
        year * 12 + MONTHS.index(month)
    )

    old_month = existing.get("reporting_month")
    old_year = existing.get("reporting_year")

    if (
        old_month in MONTHS
        and type(old_year) is int
        and existing.get("status") == "verified"
    ):
        old_period = (
            old_year * 12 + MONTHS.index(old_month)
        )

        if current_period <= old_period:
            print(
                "No newer monthly report. No changes."
            )
            return

    sales, sales_change = extract_sales(report)

    inventory, inventory_change, yoy_month, yoy_year = (
        extract_inventory(report)
    )

    # Confirm inventory comparison is year-over-year,
    # rather than month-over-month.
    if yoy_month != month or yoy_year != year - 1:
        raise ValueError(
            "Inventory comparison period is not "
            "the same month in the previous year"
        )

    detached, detached_change = (
        extract_benchmark(report, "detached")
    )

    condo, condo_change = (
        extract_benchmark(report, "condo")
    )

    stats = {
        "total_sales": sales,
        "total_sales_yoy_percent": sales_change,
        "active_listings": inventory,
        "active_listings_yoy_percent":
            inventory_change,
        "victoria_core_detached_benchmark":
            detached,
        "victoria_core_detached_yoy_percent":
            detached_change,
        "victoria_core_condo_benchmark": condo,
        "victoria_core_condo_yoy_percent":
            condo_change
    }

    validate(stats)

    updated = {
        "status": "verified",
        "reporting_month": month,
        "reporting_year": year,
        "last_updated": datetime.now(
            timezone.utc
        ).date().isoformat(),
        "source": "Victoria Real Estate Board",
        "source_url": SOURCE_URL,
        "statistics": stats
    }

    DATA_FILE.write_text(
        json.dumps(updated, indent=2) + "\n",
        encoding="utf-8"
    )

    print(
        f"Prepared verified report: {month} {year}"
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Update stopped safely: {error}",
            file=sys.stderr
        )
        sys.exit(1)

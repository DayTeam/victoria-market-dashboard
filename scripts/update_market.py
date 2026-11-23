
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://www.vreb.org/current-statistics"
DATA_FILE = Path("market-data.json")

MONTHS = [
    "January", "February", "March", "April",
    "May", "June", "July", "August",
    "September", "October", "November", "December"
]

MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"
NUMBER = r"([\d,]+)"
PERCENT = r"(\d+(?:\.\d+)?)"

EXPECTED_STAT_KEYS = {
    "total_sales",
    "total_sales_yoy_percent",
    "active_listings",
    "active_listings_yoy_percent",
    "victoria_core_detached_benchmark",
    "victoria_core_detached_yoy_percent",
    "victoria_core_condo_benchmark",
    "victoria_core_condo_yoy_percent"
}


def find(pattern, text, label):
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    if match is None:
        raise ValueError(
            f"Could not reliably extract {label}"
        )

    return match


def number(value):
    return int(value.replace(",", ""))


def signed_change(direction, value):
    direction = direction.lower()
    amount = float(value)

    if direction in (
        "increased", "increase", "more",
        "higher", "rose", "up"
    ):
        return amount

    if direction in (
        "decreased", "decrease", "fewer",
        "lower", "fell", "down"
    ):
        return -amount

    raise ValueError(
        f"Unrecognized direction: {direction}"
    )


def period_number(month, year):
    return year * 12 + MONTHS.index(month)


def get_report():
    print(
        "Checking official VREB statistics...",
        flush=True
    )

    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; DayTeamMarketDashboard/1.0)"
            )
        }
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.content,
        "html.parser"
    )

    heading_pattern = re.compile(
        r"Victoria Real Estate Market Report for\s+"
        + MONTH_PATTERN +
        r"\s+\d{4}",
        re.IGNORECASE
    )

    heading = soup.find(
        ["h1", "h2", "h3", "h4"],
        string=heading_pattern
    )

    if heading is None:
        raise ValueError(
            "Official VREB report heading not found"
        )

    heading_text = heading.get_text(
        " ", strip=True
    )

    period_match = find(
        r"Report for\s+(" +
        MONTH_PATTERN +
        r")\s+(\d{4})",
        heading_text,
        "reporting month"
    )

    month = period_match.group(1).capitalize()
    year = int(period_match.group(2))

    print(
        f"VREB report found: {month} {year}",
        flush=True
    )

    # Read the report from the entire page text.
    # This avoids problems with nested HTML elements.
    page_text = soup.get_text(
        " ", strip=True
    )

    page_text = re.sub(
        r"\s+", " ", page_text
    )

    heading_match = heading_pattern.search(
        page_text
    )

    if heading_match is None:
        raise ValueError(
            "Cannot locate report body"
        )

    report = page_text[heading_match.end():]

    # Stop at the next report or information section.
    stop = re.search(
        r"Victoria Real Estate Market Report for\s+"
        + MONTH_PATTERN +
        r"\s+\d{4}"
        r"|For More Information"
        r"|Notes for Interpreting Our Statistics",
        report,
        flags=re.IGNORECASE
    )

    if stop:
        report = report[:stop.start()]

    if len(report) < 500:
        raise ValueError(
            "Report text appears incomplete"
        )

    return month, year, report


def get_sales(report):
    match = find(
        r"A total of\s+" + NUMBER +
        r"\s+properties were sold"
        r".{0,250}?" + PERCENT +
        r"\s+per cent\s+(fewer|more)"
        r"\s+than",
        report,
        "total sales"
    )

    sales = number(match.group(1))

    change = signed_change(
        match.group(3),
        match.group(2)
    )

    return sales, change


def get_inventory(report, month, year):
    match = find(
        r"There were\s+" + NUMBER +
        r"\s+active listings for sale"
        r".{0,700}?"
        r"(\d+(?:\.\d+)?)\s+per cent\s+"
        r"(increase|decrease)"
        r"\s+from\s+the\s+" + NUMBER +
        r"\s+active listings"
        r".{0,100}?"
        r"at the end of\s+(" +
        MONTH_PATTERN +
        r")\s+(\d{4})",
        report,
        "annual active listings comparison"
    )

    inventory = number(match.group(1))

    change = signed_change(
        match.group(3),
        match.group(2)
    )

    comparison_month = (
        match.group(5).capitalize()
    )
    comparison_year = int(match.group(6))

    if (
        comparison_month != month
        or comparison_year != year - 1
    ):
        raise ValueError(
            "Inventory comparison is not year-over-year"
        )

    return inventory, change


def get_benchmark(report, property_type):
    if property_type == "detached":
        anchor = (
            r"benchmark value for a single family home"
            r"\s+in the Victoria Core"
        )
    elif property_type == "condo":
        anchor = (
            r"benchmark value for a condominium"
            r"\s+in the Victoria Core area"
        )
    else:
        raise ValueError(
            "Unknown property type"
        )

    match = find(
        anchor +
        r".{0,450}?"
        r"(increased|decreased)\s+by\s+" +
        PERCENT +
        r"\s+per cent\s+to\s+\$" +
        NUMBER,
        report,
        property_type + " benchmark"
    )

    value = number(match.group(3))

    change = signed_change(
        match.group(1),
        match.group(2)
    )

    return value, change


def validate_statistics(stats):
    if not 100 <= stats["total_sales"] <= 3000:
        raise ValueError(
            "Sales figure outside expected range"
        )

    if not 500 <= stats["active_listings"] <= 15000:
        raise ValueError(
            "Inventory figure outside expected range"
        )

    for key in (
        "victoria_core_detached_benchmark",
        "victoria_core_condo_benchmark"
    ):
        if not 100000 <= stats[key] <= 5000000:
            raise ValueError(
                f"Benchmark outside expected range: {key}"
            )

    for key, value in stats.items():
        if key.endswith("_yoy_percent"):
            if abs(value) > 80:
                raise ValueError(
                    f"Unusual annual change: {key}"
                )


def check_existing_schema(existing):
    if not isinstance(existing, dict):
        raise ValueError(
            "Existing market data is not a JSON object"
        )

    if not isinstance(
        existing.get("statistics"), dict
    ):
        raise ValueError(
            "Existing dashboard schema differs: "
            "statistics object not found"
        )

    missing = EXPECTED_STAT_KEYS - set(
        existing["statistics"].keys()
    )

    if missing:
        raise ValueError(
            "Existing dashboard uses different "
            "statistics fields: " +
            ", ".join(sorted(missing))
        )

    if existing.get("reporting_month") not in MONTHS:
        raise ValueError(
            "Existing reporting month is missing "
            "or invalid"
        )

    if type(existing.get("reporting_year")) is not int:
        raise ValueError(
            "Existing reporting year is missing "
            "or invalid"
        )


def main():
    if not DATA_FILE.exists():
        raise ValueError(
            "market-data.json does not exist"
        )

    existing = json.loads(
        DATA_FILE.read_text(
            encoding="utf-8"
        )
    )

    month, year, report = get_report()

    check_existing_schema(existing)

    old_month = existing["reporting_month"]
    old_year = existing["reporting_year"]

    current_period = period_number(
        month, year
    )

    previous_period = period_number(
        old_month, old_year
    )

    if current_period <= previous_period:
        print(
            "No newer monthly report. No changes.",
            flush=True
        )
        return

    print(
        "Newer report detected. "
        "Extracting statistics...",
        flush=True
    )

    sales, sales_change = get_sales(report)

    inventory, inventory_change = (
        get_inventory(report, month, year)
    )

    detached, detached_change = (
        get_benchmark(report, "detached")
    )

    condo, condo_change = (
        get_benchmark(report, "condo")
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

    validate_statistics(stats)

    # Preserve other existing dashboard fields.
    updated = existing.copy()

    updated["reporting_month"] = month
    updated["reporting_year"] = year
    updated["status"] = "verified"
    updated["last_updated"] = datetime.now(
        timezone.utc
    ).date().isoformat()
    updated["source"] = "Victoria Real Estate Board"
    updated["source_url"] = SOURCE_URL

    updated_statistics = existing[
        "statistics"
    ].copy()

    updated_statistics.update(stats)

    updated["statistics"] = updated_statistics

    # Only write after every extraction and
    # validation step has succeeded.
    DATA_FILE.write_text(
        json.dumps(
            updated,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Verified statistics prepared: {month} {year}",
        flush=True
    )

    print(
        json.dumps(stats, indent=2),
        flush=True
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Update stopped safely: {error}",
            file=sys.stderr,
            flush=True
        )
        sys.exit(1)

#!/usr/bin/env python3
"""
Populate monitored_users and analyst_users tables.

Reads:
  - dfp-demo/data/output/profiles/*.json  (50 user profile files)
  - dfp-demo/config/user_baselines.yaml    (user_role + work_hours per user)

Derives:
  - company from email domain
  - job_title via rule engine (user_role + top apps)
  - seniority from hash(username) % 4
  - avatar_color from user_role
  - department from user_role mapping
  - primary location / OS / browser / device from profile most_common lists

Usage:
    cd dfp-demo
    python scripts/utils/populate_users_table.py
    python scripts/utils/populate_users_table.py --dry-run

Environment variables (loaded from .env automatically):
    POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parents[3] / ".env"
    load_dotenv(_env_path, override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Paths (relative to dfp-demo/)
# ---------------------------------------------------------------------------
DFP_DEMO = Path(__file__).resolve().parents[3]  # dfp-demo/
PROFILES_DIR = DFP_DEMO / "data" / "output" / "profiles"
BASELINES_FILE = DFP_DEMO / "config" / "user_baselines.yaml"

from modules.utils.db import get_db_params  # noqa: E402

DB_CONFIG = get_db_params()

# ---------------------------------------------------------------------------
# Domain → company name
# ---------------------------------------------------------------------------
DOMAIN_COMPANY: dict[str, str] = {
    "contoso.com": "Contoso Ltd.",
    "woodgrovebank.com": "Woodgrove Bank",
    "globalcorp.com": "GlobalCorp",
    "fabrikam.com": "Fabrikam Inc.",
    "adventureworks.com": "Adventure Works",
    "tailspintoys.com": "Tailspin Toys",
    "wingtiptoys.com": "Wingtip Toys",
    "northwind.com": "Northwind Traders",
    "litwareinc.com": "Litware Inc.",
    "fourthcoffee.com": "Fourth Coffee",
    "proseware.com": "Proseware",
    "cohowinery.com": "Coho Winery",
    "citypower.com": "City Power & Light",
    "consolidated.com": "Consolidated Corp.",
    "techsolutions.com": "TechSolutions",
    "innovate.com": "Innovate Ltd.",
    "solutions.org": "Solutions Org",
    "blueyonderairlines.com": "Blue Yonder Airlines",
    "enterprise.co.uk": "Enterprise UK",
    "azure.example": "Azure Example Corp.",
}

# ---------------------------------------------------------------------------
# user_role → department
# ---------------------------------------------------------------------------
ROLE_DEPARTMENT: dict[str, str] = {
    "engineering": "Engineering",
    "hr": "Human Resources",
    "sales_marketing": "Sales & Marketing",
    "general": "Operations",
}

# ---------------------------------------------------------------------------
# user_role → avatar CSS color
# ---------------------------------------------------------------------------
ROLE_AVATAR_COLOR: dict[str, str] = {
    "engineering": "#c8f04b",  # brand-dark-lime
    "hr": "#4b8ef0",  # denim-blue
    "sales_marketing": "#f07b4b",  # orange
    "general": "#8a8a8a",  # gray
}

# ---------------------------------------------------------------------------
# Seniority from hash
# ---------------------------------------------------------------------------
SENIORITY_LEVELS = ["Junior", "Mid", "Senior", "Principal"]


def seniority_from_username(username: str) -> str:
    digest = int(hashlib.md5(username.encode()).hexdigest(), 16)
    return SENIORITY_LEVELS[digest % 4]


# ---------------------------------------------------------------------------
# Job title rule engine
# ---------------------------------------------------------------------------
JOB_TITLE_RULES: list[tuple[str, set[str], str]] = [
    ("engineering", {"GitHub", "AWS Console", "Azure Portal"}, "Software Engineer"),
    ("engineering", {"Azure Portal", "Microsoft Intune"}, "DevOps Engineer"),
    ("engineering", {"Okta", "ServiceNow", "Microsoft Intune"}, "Security Engineer"),
    ("engineering", {"Adobe Creative Cloud"}, "UX/UI Designer"),
    ("hr", {"Workday", "ServiceNow"}, "HR Manager"),
    ("hr", {"DocuSign", "Workday"}, "People Operations"),
    ("sales_marketing", {"Salesforce", "Zoom"}, "Account Executive"),
    ("sales_marketing", {"Adobe Creative Cloud", "Slack"}, "Marketing Manager"),
    ("general", {"Power BI", "Dynamics 365"}, "Business Analyst"),
    ("general", {"Microsoft Teams", "SharePoint", "Microsoft Planner"}, "Operations Manager"),
    ("general", {"DocuSign"}, "Compliance Analyst"),
]

ROLE_DEFAULT_TITLE: dict[str, str] = {
    "engineering": "Software Engineer",
    "hr": "HR Specialist",
    "sales_marketing": "Sales Representative",
    "general": "Operations Analyst",
}


def derive_job_title(user_role: str, top_apps: list[str]) -> str:
    app_set = set(top_apps)
    for role, required_apps, title in JOB_TITLE_RULES:
        if role == user_role and required_apps & app_set:
            return title
    return ROLE_DEFAULT_TITLE.get(user_role, "Analyst")


# ---------------------------------------------------------------------------
# Location parsing: "City, Region, Country" → (city, country, lat, lon)
# ---------------------------------------------------------------------------
def parse_location_string(loc_str: str) -> tuple[str, str]:
    """Return (city, country) from 'City, Region, Country' or 'City, Country'."""
    parts = [p.strip() for p in loc_str.split(",")]
    city = parts[0] if parts else loc_str
    country = parts[-1] if len(parts) > 1 else ""
    return city, country


def build_all_locations(profile: dict) -> list[dict]:
    """Build [{city, country, lat, lon, frequency}] from profile locations data."""
    locations_data = profile.get("locations", {})
    most_common = locations_data.get("most_common", [])
    coordinates = {c[0]: (c[1], c[2]) for c in locations_data.get("coordinates", [])}

    result = []
    for loc_entry in most_common:
        loc_str, freq = loc_entry[0], loc_entry[1]
        city, country = parse_location_string(loc_str)
        lat, lon = coordinates.get(city, (None, None))
        result.append(
            {
                "city": city,
                "country": country,
                "lat": lat,
                "lon": lon,
                "frequency": freq,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Profile parsing
# ---------------------------------------------------------------------------
def parse_profile(path: Path, baselines: dict) -> dict:
    with open(path) as f:
        p = json.load(f)

    username = p["username"]
    meta = p.get("meta", {})
    display_name = meta.get("user_display_name", "")
    name_parts = display_name.split(" ", 1)
    first_name = name_parts[0] if name_parts else ""
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    domain = username.split("@")[-1] if "@" in username else ""
    company = DOMAIN_COMPANY.get(domain, domain.split(".")[0].capitalize())

    # user_role from baselines
    baseline = baselines.get(username, {}).get("normal_behavior", {})
    user_role = baseline.get("user_role", "general")
    work_hours_start = baseline.get("work_hours", {}).get("start", 9)
    work_hours_end = baseline.get("work_hours", {}).get("end", 17)
    work_day_nums = baseline.get("work_days", [0, 1, 2, 3, 4])
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    active_days = [day_names[d] for d in work_day_nums if d < 7]

    # Apps
    apps_raw = p.get("apps", {}).get("most_common", [])
    top_apps = [a[0] for a in apps_raw]
    apps_jsonb = [{"app": a[0], "count": a[1]} for a in apps_raw]

    # Devices
    devices_raw = p.get("devices", {}).get("most_common", [])
    primary_device = devices_raw[0][0] if devices_raw else None
    devices_jsonb = [{"name": d[0], "count": d[1]} for d in devices_raw]

    # OS
    os_raw = p.get("operating_systems", {}).get("most_common", [])
    primary_os = os_raw[0][0] if os_raw else None

    # Browser
    browser_raw = p.get("browsers", {}).get("most_common", [])
    primary_browser = browser_raw[0][0] if browser_raw else None

    # Locations
    all_locations = build_all_locations(p)
    primary_loc = all_locations[0] if all_locations else {}
    primary_city = primary_loc.get("city")
    primary_country = primary_loc.get("country")
    home_lat = primary_loc.get("lat")
    home_lon = primary_loc.get("lon")

    # Activity hours typical range → work_hours override if not in baselines
    typical_range = p.get("activity_hours_utc", {}).get("typical_range", "")
    if not baseline.get("work_hours") and typical_range:
        m = re.match(r"(\d+):00-(\d+):00", typical_range)
        if m:
            work_hours_start = int(m.group(1))
            work_hours_end = int(m.group(2))

    # Active days override from profile if not in baselines
    if not baseline.get("work_days"):
        typical_days = p.get("active_days_of_week", {}).get("typical_days", [])
        if typical_days:
            active_days = typical_days

    return {
        "username": username,
        "user_guid": meta.get("user_id_guid"),
        "display_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": username,
        "company": company,
        "department": ROLE_DEPARTMENT.get(user_role, "Operations"),
        "user_role": user_role,
        "job_title": derive_job_title(user_role, top_apps),
        "seniority": seniority_from_username(username),
        "primary_location_city": primary_city,
        "primary_location_country": primary_country,
        "home_location_lat": home_lat,
        "home_location_lon": home_lon,
        "all_locations": json.dumps(all_locations),
        "primary_os": primary_os,
        "primary_browser": primary_browser,
        "primary_device": primary_device,
        "devices": json.dumps(devices_jsonb),
        "apps": json.dumps(apps_jsonb),
        "work_hours_start": work_hours_start,
        "work_hours_end": work_hours_end,
        "active_days": active_days,
        "total_events": p.get("total_events", 0),
        "avatar_color": ROLE_AVATAR_COLOR.get(user_role, "#8a8a8a"),
        "avatar_initials": (first_name[:1] + last_name[:1]).upper(),
        "corp_vpn": baseline.get("corp_vpn", False),
    }


# ---------------------------------------------------------------------------
# Analyst seed data
# ---------------------------------------------------------------------------
ANALYST_SEEDS = [
    # soc_analyst_l1 (3)
    {
        "username": "alice.morgan@soc.internal",
        "display_name": "Alice Morgan",
        "first_name": "Alice",
        "last_name": "Morgan",
        "email": "alice.morgan@soc.internal",
        "analyst_role": "soc_analyst_l1",
        "level": 1,
        "avatar_color": "#4b8ef0",
        "avatar_initials": "AM",
    },
    {
        "username": "ben.carter@soc.internal",
        "display_name": "Ben Carter",
        "first_name": "Ben",
        "last_name": "Carter",
        "email": "ben.carter@soc.internal",
        "analyst_role": "soc_analyst_l1",
        "level": 1,
        "avatar_color": "#4b8ef0",
        "avatar_initials": "BC",
    },
    {
        "username": "chloe.park@soc.internal",
        "display_name": "Chloe Park",
        "first_name": "Chloe",
        "last_name": "Park",
        "email": "chloe.park@soc.internal",
        "analyst_role": "soc_analyst_l1",
        "level": 1,
        "avatar_color": "#4b8ef0",
        "avatar_initials": "CP",
    },
    # soc_analyst_l2 (3)
    {
        "username": "david.osei@soc.internal",
        "display_name": "David Osei",
        "first_name": "David",
        "last_name": "Osei",
        "email": "david.osei@soc.internal",
        "analyst_role": "soc_analyst_l2",
        "level": 2,
        "avatar_color": "#c8f04b",
        "avatar_initials": "DO",
    },
    {
        "username": "elena.voss@soc.internal",
        "display_name": "Elena Voss",
        "first_name": "Elena",
        "last_name": "Voss",
        "email": "elena.voss@soc.internal",
        "analyst_role": "soc_analyst_l2",
        "level": 2,
        "avatar_color": "#c8f04b",
        "avatar_initials": "EV",
    },
    {
        "username": "fraser.bell@soc.internal",
        "display_name": "Fraser Bell",
        "first_name": "Fraser",
        "last_name": "Bell",
        "email": "fraser.bell@soc.internal",
        "analyst_role": "soc_analyst_l2",
        "level": 2,
        "avatar_color": "#c8f04b",
        "avatar_initials": "FB",
    },
    # soc_analyst_l3 (2)
    {
        "username": "grace.tanaka@soc.internal",
        "display_name": "Grace Tanaka",
        "first_name": "Grace",
        "last_name": "Tanaka",
        "email": "grace.tanaka@soc.internal",
        "analyst_role": "soc_analyst_l3",
        "level": 3,
        "avatar_color": "#f07b4b",
        "avatar_initials": "GT",
    },
    {
        "username": "hassan.ali@soc.internal",
        "display_name": "Hassan Ali",
        "first_name": "Hassan",
        "last_name": "Ali",
        "email": "hassan.ali@soc.internal",
        "analyst_role": "soc_analyst_l3",
        "level": 3,
        "avatar_color": "#f07b4b",
        "avatar_initials": "HA",
    },
    # soc_manager (1)
    {
        "username": "irene.walsh@soc.internal",
        "display_name": "Irene Walsh",
        "first_name": "Irene",
        "last_name": "Walsh",
        "email": "irene.walsh@soc.internal",
        "analyst_role": "soc_manager",
        "level": 3,
        "avatar_color": "#8a8a8a",
        "avatar_initials": "IW",
    },
    # compliance_officer (1)
    {
        "username": "james.reed@soc.internal",
        "display_name": "James Reed",
        "first_name": "James",
        "last_name": "Reed",
        "email": "james.reed@soc.internal",
        "analyst_role": "compliance_officer",
        "level": 2,
        "avatar_color": "#8a8a8a",
        "avatar_initials": "JR",
    },
]

# ---------------------------------------------------------------------------
# DB insertion
# ---------------------------------------------------------------------------
UPSERT_MONITORED = """
INSERT INTO monitored_users (
    username, user_guid, display_name, first_name, last_name, email,
    company, department, user_role, job_title, seniority,
    primary_location_city, primary_location_country,
    home_location_lat, home_location_lon, all_locations,
    primary_os, primary_browser, primary_device, devices, apps,
    work_hours_start, work_hours_end, active_days,
    total_events, avatar_color, avatar_initials, corp_vpn
) VALUES (
    %(username)s, %(user_guid)s, %(display_name)s, %(first_name)s, %(last_name)s, %(email)s,
    %(company)s, %(department)s, %(user_role)s, %(job_title)s, %(seniority)s,
    %(primary_location_city)s, %(primary_location_country)s,
    %(home_location_lat)s, %(home_location_lon)s, %(all_locations)s::jsonb,
    %(primary_os)s, %(primary_browser)s, %(primary_device)s,
    %(devices)s::jsonb, %(apps)s::jsonb,
    %(work_hours_start)s, %(work_hours_end)s, %(active_days)s,
    %(total_events)s, %(avatar_color)s, %(avatar_initials)s, %(corp_vpn)s
)
ON CONFLICT (username) DO UPDATE SET
    user_guid              = EXCLUDED.user_guid,
    display_name           = EXCLUDED.display_name,
    company                = EXCLUDED.company,
    department             = EXCLUDED.department,
    user_role              = EXCLUDED.user_role,
    job_title              = EXCLUDED.job_title,
    seniority              = EXCLUDED.seniority,
    primary_location_city  = EXCLUDED.primary_location_city,
    primary_location_country = EXCLUDED.primary_location_country,
    home_location_lat      = EXCLUDED.home_location_lat,
    home_location_lon      = EXCLUDED.home_location_lon,
    all_locations          = EXCLUDED.all_locations,
    primary_os             = EXCLUDED.primary_os,
    primary_browser        = EXCLUDED.primary_browser,
    primary_device         = EXCLUDED.primary_device,
    devices                = EXCLUDED.devices,
    apps                   = EXCLUDED.apps,
    work_hours_start       = EXCLUDED.work_hours_start,
    work_hours_end         = EXCLUDED.work_hours_end,
    active_days            = EXCLUDED.active_days,
    total_events           = EXCLUDED.total_events,
    avatar_color           = EXCLUDED.avatar_color,
    avatar_initials        = EXCLUDED.avatar_initials,
    corp_vpn               = EXCLUDED.corp_vpn,
    updated_at             = NOW();
"""

UPSERT_ANALYST = """
INSERT INTO analyst_users (
    username, display_name, first_name, last_name, email,
    analyst_role, level, avatar_color, avatar_initials
) VALUES (
    %(username)s, %(display_name)s, %(first_name)s, %(last_name)s, %(email)s,
    %(analyst_role)s, %(level)s, %(avatar_color)s, %(avatar_initials)s
)
ON CONFLICT (username) DO UPDATE SET
    display_name    = EXCLUDED.display_name,
    analyst_role    = EXCLUDED.analyst_role,
    level           = EXCLUDED.level,
    avatar_color    = EXCLUDED.avatar_color,
    avatar_initials = EXCLUDED.avatar_initials;
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Populate users tables from profiles")
    parser.add_argument("--dry-run", action="store_true", help="Parse and print rows without writing")
    args = parser.parse_args()

    # Load baselines
    with open(BASELINES_FILE) as f:
        raw = yaml.safe_load(f)
    baselines: dict = raw.get("users", {})

    # Parse profiles
    profiles = []
    for path in sorted(PROFILES_DIR.glob("*.json")):
        try:
            row = parse_profile(path, baselines)
            profiles.append(row)
        except Exception as e:
            print(f"  WARN: skipping {path.name}: {e}", file=sys.stderr)

    print(f"Parsed {len(profiles)} monitored users")
    print(f"Prepared {len(ANALYST_SEEDS)} analyst seed rows")

    if args.dry_run:
        for row in profiles:
            print(f"  {row['username']:50s}  {row['user_role']:20s}  {row['job_title']}")
        print("\nAnalysts:")
        for row in ANALYST_SEEDS:
            print(f"  {row['username']:40s}  {row['analyst_role']}")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn:
            with conn.cursor() as cur:
                for row in profiles:
                    cur.execute(UPSERT_MONITORED, row)
                print(f"  Upserted {len(profiles)} rows into monitored_users")

                for row in ANALYST_SEEDS:
                    cur.execute(UPSERT_ANALYST, row)
                print(f"  Upserted {len(ANALYST_SEEDS)} rows into analyst_users")
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()

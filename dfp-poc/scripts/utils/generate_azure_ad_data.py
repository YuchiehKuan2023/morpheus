#!/usr/bin/env python3
"""
Generate Production-Ready Azure AD Log Data for DFP

This script generates realistic Azure AD sign-in logs that match NVIDIA's
official DFP data format and schema. The data is 100% compliant with:
- NVIDIA Morpheus DFP Azure AD schema
- Real Azure AD SignInActivity log structure
- Production-level usernames, UUIDs, and attributes

Reference:
    - NVIDIA: examples/digital_fingerprinting/production/morpheus/dfp/schemas/azure_ad_schema.json
    - Azure AD: https://docs.microsoft.com/en-us/azure/active-directory/reports-monitoring/reference-azure-monitor-sign-ins-log-schema

Usage:
    # Generate training data (1500 events, 1 user, realistic behavior)
    python scripts/utils/generate_azure_ad_data.py \\
        --output data/input/train/azure_ad_train.jsonl \\
        --num-events 1500 \\
        --num-users 1 \\
        --duration-days 70 \\
        --start-time "2025-08-11T00:00:00+00:00" \\
        --min-events-per-user 1500 \\
        --events-per-user uniform \\
        --user-seed 42 \\
        --event-seed 42

    # Generate training data (150k events, 50 users)
    python scripts/utils/generate_azure_ad_data.py \\
        --output data/input/train/azure_ad_train.jsonl \\
        --num-events 150000 \\
        --num-users 50 \\
        --duration-days 70 \\
        --min-events-per-user 300 \\
        --events-per-user variable \\
        --user-seed 42 \\
        --event-seed 42

Author: Tomasz Zabek <tzabek@deloitte.co.uk>
Date: 2025-11-15
"""

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

# ============================================================================
# NVIDIA-Compliant Azure AD Data Configuration
# ============================================================================

# Real-world organizational structure
DEPARTMENTS = [
    "Engineering",
    "Sales",
    "Marketing",
    "Finance",
    "HR",
    "Operations",
    "Product",
    "Legal",
    "IT",
    "Security",
    "Customer Success",
    "Research",
]

# Geographic coordinates for impossible travel detection (50 global cities)
# Each location has realistic lat/lon coordinates for haversine distance calculation
LOCATIONS = [
    # North America (15 cities)
    {"city": "Seattle", "state": "Washington", "country": "United States", "coords": (47.6062, -122.3321)},
    {"city": "New York", "state": "New York", "country": "United States", "coords": (40.7128, -74.0060)},
    {"city": "San Francisco", "state": "California", "country": "United States", "coords": (37.7749, -122.4194)},
    {"city": "Austin", "state": "Texas", "country": "United States", "coords": (30.2672, -97.7431)},
    {"city": "Chicago", "state": "Illinois", "country": "United States", "coords": (41.8781, -87.6298)},
    {"city": "Boston", "state": "Massachusetts", "country": "United States", "coords": (42.3601, -71.0589)},
    {"city": "Los Angeles", "state": "California", "country": "United States", "coords": (34.0522, -118.2437)},
    {"city": "Miami", "state": "Florida", "country": "United States", "coords": (25.7617, -80.1918)},
    {"city": "Denver", "state": "Colorado", "country": "United States", "coords": (39.7392, -104.9903)},
    {"city": "Toronto", "state": "Ontario", "country": "Canada", "coords": (43.6532, -79.3832)},
    {"city": "Vancouver", "state": "British Columbia", "country": "Canada", "coords": (49.2827, -123.1207)},
    {"city": "Montreal", "state": "Quebec", "country": "Canada", "coords": (45.5017, -73.5673)},
    {"city": "Mexico City", "state": "Mexico City", "country": "Mexico", "coords": (19.4326, -99.1332)},
    {"city": "Atlanta", "state": "Georgia", "country": "United States", "coords": (33.7490, -84.3880)},
    {
        "city": "Washington DC",
        "state": "District of Columbia",
        "country": "United States",
        "coords": (38.9072, -77.0369),
    },
    # Europe (15 cities)
    {"city": "London", "state": "England", "country": "United Kingdom", "coords": (51.5074, -0.1278)},
    {"city": "Manchester", "state": "England", "country": "United Kingdom", "coords": (53.4808, -2.2426)},
    {"city": "Birmingham", "state": "England", "country": "United Kingdom", "coords": (52.4862, -1.8904)},
    {"city": "Edinburgh", "state": "Scotland", "country": "United Kingdom", "coords": (55.9533, -3.1883)},
    {"city": "Bristol", "state": "England", "country": "United Kingdom", "coords": (51.4545, -2.5879)},
    {"city": "Paris", "state": "Île-de-France", "country": "France", "coords": (48.8566, 2.3522)},
    {"city": "Berlin", "state": "Berlin", "country": "Germany", "coords": (52.5200, 13.4050)},
    {"city": "Munich", "state": "Bavaria", "country": "Germany", "coords": (48.1351, 11.5820)},
    {"city": "Amsterdam", "state": "North Holland", "country": "Netherlands", "coords": (52.3676, 4.9041)},
    {"city": "Brussels", "state": "Brussels", "country": "Belgium", "coords": (50.8503, 4.3517)},
    {"city": "Madrid", "state": "Madrid", "country": "Spain", "coords": (40.4168, -3.7038)},
    {"city": "Barcelona", "state": "Catalonia", "country": "Spain", "coords": (41.3851, 2.1734)},
    {"city": "Rome", "state": "Lazio", "country": "Italy", "coords": (41.9028, 12.4964)},
    {"city": "Milan", "state": "Lombardy", "country": "Italy", "coords": (45.4642, 9.1900)},
    {"city": "Stockholm", "state": "Stockholm", "country": "Sweden", "coords": (59.3293, 18.0686)},
    # Asia-Pacific (15 cities)
    {"city": "Tokyo", "state": "Tokyo", "country": "Japan", "coords": (35.6762, 139.6503)},
    {"city": "Singapore", "state": "Singapore", "country": "Singapore", "coords": (1.3521, 103.8198)},
    {"city": "Sydney", "state": "New South Wales", "country": "Australia", "coords": (-33.8688, 151.2093)},
    {"city": "Melbourne", "state": "Victoria", "country": "Australia", "coords": (-37.8136, 144.9631)},
    {"city": "Hong Kong", "state": "Hong Kong", "country": "Hong Kong", "coords": (22.3193, 114.1694)},
    {"city": "Shanghai", "state": "Shanghai", "country": "China", "coords": (31.2304, 121.4737)},
    {"city": "Beijing", "state": "Beijing", "country": "China", "coords": (39.9042, 116.4074)},
    {"city": "Seoul", "state": "Seoul", "country": "South Korea", "coords": (37.5665, 126.9780)},
    {"city": "Mumbai", "state": "Maharashtra", "country": "India", "coords": (19.0760, 72.8777)},
    {"city": "Bangalore", "state": "Karnataka", "country": "India", "coords": (12.9716, 77.5946)},
    {"city": "Delhi", "state": "Delhi", "country": "India", "coords": (28.7041, 77.1025)},
    {"city": "Bangkok", "state": "Bangkok", "country": "Thailand", "coords": (13.7563, 100.5018)},
    {"city": "Jakarta", "state": "Jakarta", "country": "Indonesia", "coords": (-6.2088, 106.8456)},
    {"city": "Manila", "state": "Metro Manila", "country": "Philippines", "coords": (14.5995, 120.9842)},
    {"city": "Auckland", "state": "Auckland", "country": "New Zealand", "coords": (-36.8485, 174.7633)},
    # Middle East & Africa (5 cities)
    {"city": "Dubai", "state": "Dubai", "country": "United Arab Emirates", "coords": (25.2048, 55.2708)},
    {"city": "Tel Aviv", "state": "Tel Aviv", "country": "Israel", "coords": (32.0853, 34.7818)},
    {"city": "Istanbul", "state": "Istanbul", "country": "Turkey", "coords": (41.0082, 28.9784)},
    {"city": "Johannesburg", "state": "Gauteng", "country": "South Africa", "coords": (-26.2041, 28.0473)},
    {"city": "Cairo", "state": "Cairo", "country": "Egypt", "coords": (30.0444, 31.2357)},
]

# Microsoft 365 / Azure AD applications
MICROSOFT_APPS = [
    "Microsoft Teams",
    "Office 365 Exchange Online",
    "Microsoft SharePoint Online",
    "Microsoft OneDrive for Business",
    "Microsoft Power BI",
    "Microsoft Dynamics 365",
    "Microsoft Azure Portal",
    "Microsoft Intune",
    "Microsoft Stream",
    "Microsoft Planner",
    "Microsoft Forms",
    "Microsoft Yammer",
    "Microsoft To-Do",
    "Microsoft Whiteboard",
    "Microsoft Bookings",
]

# Third-party SaaS applications
SAAS_APPS = [
    "Salesforce",
    "Slack",
    "Zoom",
    "GitHub",
    "Jira",
    "Confluence",
    "Dropbox",
    "Box",
    "Google Workspace",
    "AWS Console",
    "Okta",
    "ServiceNow",
    "Workday",
    "DocuSign",
    "Adobe Creative Cloud",
]

ALL_APPS = MICROSOFT_APPS + SAAS_APPS

# Client applications used for authentication
CLIENT_APPS = [
    "Browser",
    "Mobile Apps and Desktop clients",
    "Exchange ActiveSync",
    "Other clients",
    "IMAP4",
    "POP3",
    "SMTP",
    "Modern Auth Clients",
    "Exchange Web Services",
    "Outlook Service",
    "Authenticated SMTP",
]

# Browsers
BROWSERS = [
    "Chrome 119.0",
    "Chrome 118.0",
    "Firefox 120.0",
    "Firefox 119.0",
    "Safari 17.0",
    "Safari 16.6",
    "Edge 119.0",
    "Edge 118.0",
    "Mobile Safari 17.0",
    "Chrome Mobile 119.0",
]

# Operating systems
OPERATING_SYSTEMS = [
    "Windows 11",
    "Windows 10",
    "macOS 14 Sonoma",
    "macOS 13 Ventura",
    "iOS 17.1",
    "iOS 17.0",
    "Android 14",
    "Android 13",
    "Ubuntu 22.04",
    "Ubuntu 20.04",
]

# Device names (realistic patterns)
DEVICE_PREFIXES = ["DESKTOP", "LAPTOP", "MOBILE", "TABLET", "WORKSTATION"]

# All anomaly-related constants removed - generator only creates clean, realistic data
# Login failures use "Invalid username or password" (3% rate - realistic mistyping)


class AzureADDataGenerator:
    """
    Generate realistic Azure AD sign-in logs matching NVIDIA DFP schema.

    NVIDIA DFP Compliance:
    - Training requires min_history=300 events per user (from dfp_rolling_window.py)
    - Users must be consistent across training and inference datasets
    - Per-user behavioral patterns (apps, locations, devices)
    - Variable activity levels per user (realistic distribution)
    """

    def __init__(self, num_users: int = 50, user_seed: int = 42, event_seed: int | None = None):
        """
        Initialize data generator.

        Args:
            num_users: Number of unique users to generate
            user_seed: Seed for user generation (MUST be same for training and inference)
            event_seed: Seed for event generation (can differ between train/infer)
        """
        # Generate users with consistent seed
        random.seed(user_seed)
        self.num_users = num_users
        self.users = self._generate_users(num_users)

        # Set event seed (allows different event patterns while keeping same users)
        if event_seed is not None:
            random.seed(event_seed)

        self.user_seed = user_seed
        self.event_seed = event_seed

    def _generate_users(self, count: int) -> list[dict[str, Any]]:
        """Generate realistic user profiles."""
        first_names = [
            "James",
            "Mary",
            "John",
            "Patricia",
            "Robert",
            "Jennifer",
            "Michael",
            "Linda",
            "William",
            "Barbara",
            "David",
            "Elizabeth",
            "Richard",
            "Susan",
            "Joseph",
            "Jessica",
            "Thomas",
            "Sarah",
            "Charles",
            "Karen",
            "Christopher",
            "Nancy",
            "Daniel",
            "Lisa",
            "Matthew",
            "Betty",
            "Anthony",
            "Margaret",
            "Mark",
            "Sandra",
            "Donald",
            "Ashley",
            "Steven",
            "Kimberly",
            "Paul",
            "Emily",
            "Andrew",
            "Donna",
            "Joshua",
            "Michelle",
            "Kenneth",
            "Carol",
            "Kevin",
            "Amanda",
            "Brian",
            "Dorothy",
            "George",
            "Melissa",
            "Timothy",
            "Deborah",
            "Ronald",
            "Stephanie",
            "Tomasz",
            "Gabriel",
        ]

        last_names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
            "Hernandez",
            "Lopez",
            "Gonzalez",
            "Wilson",
            "Anderson",
            "Thomas",
            "Taylor",
            "Moore",
            "Jackson",
            "Martin",
            "Lee",
            "Perez",
            "Thompson",
            "White",
            "Harris",
            "Sanchez",
            "Clark",
            "Ramirez",
            "Lewis",
            "Robinson",
            "Walker",
            "Young",
            "Allen",
            "King",
            "Wright",
            "Scott",
            "Torres",
            "Nguyen",
            "Hill",
            "Flores",
            "Green",
            "Adams",
            "Nelson",
            "Baker",
            "Hall",
            "Rivera",
            "Campbell",
            "Mitchell",
            "Carter",
            "Roberts",
            "Zabek",
            "Rymarz",
        ]

        email_domains = [
            "contoso.com",
            "fabrikam.com",
            "northwind.com",
            "adventureworks.com",
            "wingtiptoys.com",
            "tailspintoys.com",
            "litwareinc.com",
            "proseware.com",
            "woodgrovebank.com",
            "cohowinery.com",
            "blueyonderairlines.com",
            "fourthcoffee.com",
            "alpineskihouse.com",
            "citypower.com",
            "consolidated.com",
            "globalcorp.com",
            "techsolutions.com",
            "innovate.com",
            "enterprise.co.uk",
            "solutions.org",
            "dynamics.net",
            "azure.example",
        ]

        users = []
        used_usernames = set()

        attempts = 0
        max_attempts = count * 10  # Prevent infinite loop

        while len(users) < count and attempts < max_attempts:
            attempts += 1

            first = random.choice(first_names)
            last = random.choice(last_names)
            dept = random.choice(DEPARTMENTS)
            home_location = random.choice(LOCATIONS)
            email_domain = random.choice(email_domains)

            username = f"{first.lower()}.{last.lower()}@{email_domain}"

            # Check if username already exists
            if username in used_usernames:
                continue  # Try again with different combination

            used_usernames.add(username)

            # Generate base user first (for consistent seed behavior)
            user = {
                "user_id": str(uuid.uuid4()),
                "username": username,
                "display_name": f"{first} {last}",
                "department": dept,
                "home_location": home_location,
                "typical_apps": random.sample(ALL_APPS, k=random.randint(5, 10)),  # User's normal apps
                "corp_vpn": random.random() < 0.7,  # 70% use corporate VPN
            }

            # Generate 2-4 device configurations per user (laptop, phone, tablet, etc.)
            # Real users access from multiple devices with varying frequency
            # Use deterministic seed based on username to ensure consistent devices per user
            device_seed = hash(user["username"]) % (2**31)
            device_rng = random.Random(device_seed)

            num_devices = device_rng.randint(2, 4)
            devices = []

            for _d in range(num_devices):
                device_type = device_rng.choice(DEVICE_PREFIXES)
                device_name = f"{device_type}-{last.upper()}-{device_rng.randint(1000, 9999)}"

                # Generate stable device_id based on device name (70% have device_id)
                # Use deterministic UUID based on device name for consistency
                has_device_id = device_rng.random() > 0.3
                if has_device_id:
                    # Create deterministic UUID from device name
                    device_uuid_seed = hash(device_name) % (2**31)
                    device_uuid_rng = random.Random(device_uuid_seed)
                    device_id = str(uuid.UUID(int=device_uuid_rng.getrandbits(128)))
                else:
                    device_id = ""

                devices.append(
                    {
                        "name": device_name,
                        "os": device_rng.choice(OPERATING_SYSTEMS),
                        "browser": device_rng.choice(BROWSERS),
                        "weight": device_rng.uniform(0.1, 1.0),  # Usage frequency weight
                        "device_id": device_id,  # Stable device ID
                    }
                )

            # Normalize weights so primary device is most common
            total_weight = sum(d["weight"] for d in devices)
            for d in devices:
                d["weight"] = d["weight"] / total_weight

            # Sort by weight (most used first)
            devices.sort(key=lambda d: d["weight"], reverse=True)

            user["devices"] = devices
            users.append(user)

        if len(users) < count:
            print(f"Warning: Could only generate {len(users)}/{count} unique users")
            print("Consider expanding the name/domain pools or reducing user count")

        return users

    def _get_region(self, location: dict[str, Any]) -> str:
        """Determine region for a location based on coordinates."""
        lat, lon = location["coords"]

        # North America: lat 25-60, lon -130 to -60
        if 25 <= lat <= 60 and -130 <= lon <= -60:
            return "North America"
        # Europe: lat 35-70, lon -10 to 40
        elif 35 <= lat <= 70 and -10 <= lon <= 40:
            return "Europe"
        # Asia-Pacific: lat -40 to 45, lon 100 to 180
        elif -40 <= lat <= 45 and 100 <= lon <= 180:
            return "Asia-Pacific"
        # Middle East & Africa: everything else
        else:
            return "Middle East & Africa"

    def _get_regional_locations(self, region: str) -> list[dict[str, Any]]:
        """Get all locations in the same region."""
        return [loc for loc in LOCATIONS if self._get_region(loc) == region]

    def generate_event(self, timestamp: datetime, user: dict[str, Any]) -> dict[str, Any]:
        """
        Generate a single Azure AD sign-in event with realistic, clean data.
        Includes realistic login failures (3% rate - users occasionally mistype passwords).

        Args:
            timestamp: Event timestamp
            user: User profile dict

        Returns:
            Azure AD sign-in log entry matching NVIDIA schema
        """
        # Generate consistent IDs for this event
        correlation_id = str(uuid.uuid4())
        resource_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())

        # Realistic login failure rate (3% - users occasionally mistype passwords)
        is_failed_login = random.random() < 0.03

        if is_failed_login:
            result_type = "50126"  # Invalid username or password
            result_desc = "Invalid username or password"
            error_code = 50126
            failure_reason = "Invalid username or password"
        else:
            result_type = "0"
            result_desc = "Success"
            error_code = 0
            failure_reason = "None"

        # Base event structure (NVIDIA format)
        event = {
            "time": timestamp.isoformat(),
            "category": "SignInLogs",
            "operationName": "Sign-in activity",
            "resultType": result_type,
            "resultDescription": result_desc,
            "durationMs": random.randint(100, 5000),
            "callerIpAddress": self._generate_ip(user),
            "correlationId": correlation_id,
            "identity": user["username"],
            "Level": 4,
            "location": {
                "city": "",
                "state": "",
                "countryOrRegion": "",
                "geoCoordinates": {"latitude": 0.0, "longitude": 0.0},
            },
            "properties": {
                "id": event_id,
                "createdDateTime": timestamp.isoformat(),
                "userDisplayName": user["display_name"],
                "userPrincipalName": user["username"],
                "userId": user["user_id"],
                "appId": "",  # Will be set with stable app-specific ID
                "appDisplayName": "",
                "ipAddress": "",
                "clientAppUsed": "",
                "correlationId": correlation_id,  # Same as top-level
                "conditionalAccessStatus": "success",
                "isInteractive": True,
                "riskDetail": "none",
                "riskLevelAggregated": "none",
                "riskLevelDuringSignIn": "none",
                "riskState": "none",
                "resourceDisplayName": "Microsoft 365",
                "resourceId": resource_id,
                "status": {
                    "errorCode": error_code,
                    "failureReason": failure_reason,
                    "additionalDetails": "None",
                },
                "deviceDetail": {
                    "deviceId": "",  # Will be set with stable device-specific UUID
                    "displayName": "",
                    "operatingSystem": "",
                    "browser": "",
                    "isCompliant": True,
                    "isManaged": True,
                    "trustType": "Hybrid Azure AD joined",
                },
                "location": {
                    "city": "",
                    "state": "",
                    "countryOrRegion": "",
                    "geoCoordinates": {"latitude": 0.0, "longitude": 0.0},
                },
                "mfaDetail": {
                    "authMethod": "Phone App Notification",
                    "authDetail": "Approved",
                },
                "autonomousSystemNumber": random.randint(1000, 65000),
            },
        }

        # Fill in application from user's typical apps
        app = random.choice(user["typical_apps"])
        event["properties"]["appDisplayName"] = app
        # Generate stable appId based on app name (same app always gets same ID)
        event["properties"]["appId"] = self._generate_stable_app_id(app)

        # Fill in client app
        event["properties"]["clientAppUsed"] = random.choice(CLIENT_APPS)

        # Location will be set by caller (generate_dataset) with proper state tracking
        # This ensures realistic travel times and continuity

        # Device will be set by caller (generate_dataset) with proper location context
        # This ensures mobile devices are used when traveling, desktop at home

        # IP address
        ip = self._generate_ip(user)
        event["callerIpAddress"] = ip
        event["properties"]["ipAddress"] = ip

        return event

    def _generate_stable_app_id(self, app_name: str) -> str:
        """Generate stable appId for an application (based on app name hash)."""
        # Create deterministic UUID using uuid5 (namespace-based UUID)
        # This ensures the same app name ALWAYS produces the same UUID
        namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
        return str(uuid.uuid5(namespace, app_name))

    def _generate_ip(self, user: dict[str, Any]) -> str:
        """Generate realistic IP address based on user's VPN usage."""
        # Corporate IP range (10.x.x.x or 172.16-31.x.x)
        if user["corp_vpn"]:
            return f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        else:
            # Public IP range (avoid reserved ranges)
            return (
                f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}"
            )

    def _generate_realistic_timestamps(
        self, start_time: datetime, duration_days: int, target_events: int, user: dict[str, Any]
    ) -> list[datetime]:
        """Generate realistic timestamps with business hours, weekends, and vacation gaps.

        Args:
            start_time: Starting timestamp
            duration_days: Total duration in days
            target_events: Target number of events to generate
            user: User profile dict

        Returns:
            List of timestamps with realistic patterns
        """
        timestamps = []
        current_date = start_time
        end_date = start_time + timedelta(days=duration_days)

        # Calculate events per active day (accounting for weekends and vacations)
        # Assume 70% of days are active (weekends at 20% + some vacation days)
        estimated_active_days = duration_days * 0.7
        events_per_day = max(1, int(target_events / estimated_active_days))

        # Vacation tracking
        vacation_end_date = None
        vacation_count = 0

        while current_date < end_date and len(timestamps) < target_events:
            # Check if on vacation
            if vacation_end_date and current_date < vacation_end_date:
                current_date += timedelta(days=1)
                continue

            # Random vacation probability (5% chance per week of 1-2 week vacation)
            if vacation_end_date is None and random.random() < 0.01 and vacation_count < 2:
                vacation_days = random.randint(7, 14)
                vacation_end_date = current_date + timedelta(days=vacation_days)
                vacation_count += 1
                print(f"   • {user['username']}: Vacation from {current_date.date()} for {vacation_days} days")
                current_date += timedelta(days=1)
                continue

            # Reset vacation flag
            if vacation_end_date and current_date >= vacation_end_date:
                vacation_end_date = None

            # Weekend reduction (20% activity on Sat/Sun)
            is_weekend = current_date.weekday() >= 5
            if is_weekend:
                daily_events = max(1, int(events_per_day * 0.2))
            else:
                daily_events = events_per_day

            # Generate events for this day
            for _ in range(daily_events):
                if len(timestamps) >= target_events:
                    break

                # Business hours focus (9am-5pm = 70%, off-hours = 30%)
                if random.random() < 0.7:
                    # Business hours (9am-5pm)
                    hour = random.randint(9, 17)
                else:
                    # Off hours (before 9am or after 5pm)
                    hour = random.choice(list(range(0, 9)) + list(range(18, 24)))

                minute = random.randint(0, 59)
                second = random.randint(0, 59)

                timestamp = current_date.replace(hour=hour, minute=minute, second=second)
                timestamps.append(timestamp)

            current_date += timedelta(days=1)

        # Sort chronologically
        timestamps.sort()

        # Return exactly target_events (trim if we generated too many)
        return timestamps[:target_events]

    def generate_dataset(
        self,
        num_events: int,
        start_time: datetime,
        duration_days: int = 60,
        events_per_user: str = "variable",
        min_events_per_user: int = 1,
        unseen_user_count: int = 0,
    ) -> list[dict[str, Any]]:
        """
        Generate a complete dataset of clean, realistic Azure AD events.

        NVIDIA DFP Compliance:
        - Training: Use duration_days=60+ with min_events_per_user=300 (NVIDIA min_history)
        - All users generate events CONCURRENTLY over the same time period
        - Realistic distribution: Some users very active, others less active
        - Data includes realistic variety: 20% travel, 30% device changes, frequent app switching

        Args:
            num_events: Total number of events to generate
            start_time: Starting timestamp
            duration_days: Number of days to spread events across (60+ for training)
            events_per_user: "uniform" (equal per user) or "variable" (realistic distribution)
            min_events_per_user: Minimum events per user (300 for training, 1 for inference)
            unseen_user_count: Number of additional unseen users to add (for generic model testing)

        Returns:
            List of Azure AD event dictionaries
        """
        events = []

        # Add unseen users if requested (for generic model testing in inference)
        all_users = self.users.copy()
        if unseen_user_count > 0:
            # Generate additional users with different seed to ensure they're truly unseen
            original_seed = random.getstate()
            random.seed(self.user_seed + 10000)  # Different seed space
            unseen_users = self._generate_users(unseen_user_count)
            all_users.extend(unseen_users)
            random.setstate(original_seed)

        # Determine events per user based on distribution strategy
        if events_per_user == "uniform":
            # Equal distribution
            user_event_counts = {user["user_id"]: num_events // len(all_users) for user in all_users}
        else:
            # Variable distribution (realistic: some users very active, others less)
            # Use power law distribution to simulate realistic user activity
            weights = [1.0 / (i + 1) ** 0.5 for i in range(len(all_users))]
            total_weight = sum(weights)
            normalized_weights = [w / total_weight for w in weights]

            user_event_counts = {}
            remaining_events = num_events

            for i, user in enumerate(all_users[:-1]):
                count = max(min_events_per_user, int(num_events * normalized_weights[i]))
                user_event_counts[user["user_id"]] = count
                remaining_events -= count

            # Assign remaining events to last user
            user_event_counts[all_users[-1]["user_id"]] = max(min_events_per_user, remaining_events)

        # Generate events with REALISTIC patterns (vacations, weekends, business hours)
        # Each user should have events spread throughout the entire duration_days period
        # with natural gaps for vacations, reduced weekend activity, and business hours focus
        end_time = start_time + timedelta(days=duration_days)

        print(f"\nGenerating realistic activity over {duration_days} days:")
        print(f"   • Start: {start_time.isoformat()}")
        print(f"   • End: {end_time.isoformat()}")
        print("   • Patterns: Business hours (9-5), Weekend reduction (20%), Vacations (5% probability)")

        for user in all_users:
            num_user_events = user_event_counts[user["user_id"]]

            # Generate realistic timestamps with business hours, weekends, and vacations
            user_timestamps = self._generate_realistic_timestamps(
                start_time=start_time, duration_days=duration_days, target_events=num_user_events, user=user
            )

            # User state tracking for behavioral continuity
            current_location = user["home_location"]
            current_device = user["devices"][0]  # Start with primary device
            current_app = random.choice(user["typical_apps"])  # Initialize with first app
            app_session_remaining = 0  # Will trigger new app selection on first event
            last_timestamp = None

            # Helper function to calculate haversine distance
            def haversine_distance(lat1, lon1, lat2, lon2):
                from math import atan2, cos, radians, sin, sqrt

                R = 6371  # Earth radius in km
                dlat = radians(lat2 - lat1)
                dlon = radians(lon2 - lon1)
                a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
                c = 2 * atan2(sqrt(a), sqrt(1 - a))
                return R * c

            # Helper to get minimum travel time (hours) for a distance (km)
            def get_min_travel_time(distance_km):
                """Calculate minimum realistic travel time including ground time.

                Travel speed assumptions:
                - 0-50 km: Local travel, 30-60 km/h average (traffic, parking)
                - 50-200 km: Regional, 80 km/h average (car/train)
                - 200-500 km: Longer regional, 120 km/h average (fast train/short flight)
                - 500+ km: Flight required, 600 km/h cruise + 2 hours ground time
                """
                if distance_km < 50:
                    return distance_km / 40  # 40 km/h average with traffic
                elif distance_km < 200:
                    return distance_km / 80  # 80 km/h regional travel
                elif distance_km < 500:
                    return distance_km / 120  # 120 km/h fast train/short flight
                else:
                    # Flight: 600 km/h cruise + 2 hours for check-in/taxi/boarding/deplaning
                    return (distance_km / 600) + 2.0

            # Helper to select device based on location context
            def select_device_for_location(is_traveling, at_home, user_devices):
                """Select realistic device based on location context."""
                # At home: prefer desktop/laptop (80%)
                if at_home and random.random() < 0.8:
                    desktop_devices = [
                        d for d in user_devices if d["name"].startswith(("DESKTOP", "LAPTOP", "WORKSTATION"))
                    ]
                    if desktop_devices:
                        return max(desktop_devices, key=lambda d: d["weight"])

                # Traveling: prefer mobile devices (90%)
                if is_traveling and random.random() < 0.9:
                    mobile_devices = [d for d in user_devices if d["name"].startswith(("MOBILE", "TABLET"))]
                    if mobile_devices:
                        return max(mobile_devices, key=lambda d: d["weight"])

                # Default: use weighted selection from all devices
                weights = [d["weight"] for d in user_devices]
                return random.choices(user_devices, weights=weights, k=1)[0]

            # Generate events for this user
            for _, timestamp in enumerate(user_timestamps):
                # === LOCATION SELECTION WITH REALISTIC TRAVEL CONSTRAINTS ===
                new_location = current_location
                is_traveling = False

                if last_timestamp is not None:
                    # Calculate time since last event
                    time_gap_hours = (timestamp - last_timestamp).total_seconds() / 3600

                    # Consider travel with 20% probability for realistic diversity
                    # Users travel for business, work from different offices, etc.
                    if random.random() < 0.20:
                        # Get regional locations (stay in same region)
                        home_region = self._get_region(user["home_location"])
                        regional_locations = self._get_regional_locations(home_region)

                        if regional_locations:
                            # Find locations that are physically reachable
                            reachable_locations = []
                            for loc in regional_locations:
                                # Skip current location
                                if loc["city"] == current_location["city"]:
                                    continue

                                distance = haversine_distance(
                                    current_location["coords"][0],
                                    current_location["coords"][1],
                                    loc["coords"][0],
                                    loc["coords"][1],
                                )

                                # Calculate minimum required travel time
                                min_time = get_min_travel_time(distance)

                                # Only consider if we have enough time
                                if time_gap_hours >= min_time:
                                    reachable_locations.append((loc, distance))

                            # If we have reachable locations, pick one (prefer closer)
                            if reachable_locations:
                                # Weight by inverse distance (prefer closer locations)
                                locs, distances = zip(*reachable_locations, strict=False)
                                weights = [1.0 / (d + 1) for d in distances]
                                new_location = random.choices(locs, weights=weights, k=1)[0]
                                is_traveling = True
                                current_location = new_location

                # === DEVICE SELECTION BASED ON LOCATION ===
                at_home = new_location["city"] == user["home_location"]["city"]

                # Change device if location changed or randomly (30% for realistic variety)
                # Mobile workers switch between laptop, phone, tablet throughout day
                if is_traveling or random.random() < 0.30:
                    current_device = select_device_for_location(is_traveling, at_home, user["devices"])

                # === APP SELECTION WITH SESSION CONTINUITY ===
                # Users typically use the same app for multiple events (sessions)
                if app_session_remaining <= 0:
                    # Start new app session
                    current_app = random.choice(user["typical_apps"])

                    # Session length: 1-3 events (realistic: users switch apps frequently)
                    # Reduced from 1-8 to create more app diversity
                    app_session_remaining = random.randint(1, 3)

                app_session_remaining -= 1

                # === GENERATE BASE EVENT ===
                event = self.generate_event(timestamp, user)

                # === UPDATE EVENT WITH TRACKED STATE ===
                # Set location
                event["properties"]["location"]["city"] = new_location["city"]
                event["properties"]["location"]["state"] = new_location["state"]
                event["properties"]["location"]["countryOrRegion"] = new_location["country"]
                event["properties"]["location"]["geoCoordinates"]["latitude"] = new_location["coords"][0]
                event["properties"]["location"]["geoCoordinates"]["longitude"] = new_location["coords"][1]
                event["location"] = event["properties"]["location"].copy()
                event["location_geoCoordinates_latitude"] = new_location["coords"][0]
                event["location_geoCoordinates_longitude"] = new_location["coords"][1]

                # Set device with stable device_id
                event["properties"]["deviceDetail"]["displayName"] = current_device["name"]
                event["properties"]["deviceDetail"]["browser"] = current_device["browser"]
                event["properties"]["deviceDetail"]["operatingSystem"] = current_device["os"]
                event["properties"]["deviceDetail"]["deviceId"] = current_device["device_id"]

                # Set app (use current session app) with stable appId
                event["properties"]["appDisplayName"] = current_app
                event["properties"]["appId"] = self._generate_stable_app_id(current_app)

                last_timestamp = timestamp
                events.append(event)

        # Sort all events by timestamp to ensure chronological order (NVIDIA requirement)
        events.sort(key=lambda x: x["time"])

        return events

    def save_jsonl(self, events: list[dict[str, Any]], output_path: str):
        """Save events to JSONL file."""
        with open(output_path, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        print(f"✓ Saved {len(events)} events to {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate production-ready Azure AD log data for NVIDIA DFP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--output", type=str, required=True, help="Output JSONL file path")

    parser.add_argument("--num-events", type=int, default=1000, help="Number of events to generate (default: 1000)")

    parser.add_argument("--num-users", type=int, default=50, help="Number of unique users (default: 50)")

    parser.add_argument(
        "--user-seed",
        type=int,
        default=42,
        help="Random seed for user generation - MUST be same for training and inference (default: 42)",
    )

    parser.add_argument(
        "--event-seed",
        type=int,
        default=None,
        help="Random seed for event generation - can differ between train/infer (default: None)",
    )

    parser.add_argument(
        "--events-per-user",
        type=str,
        choices=["uniform", "variable"],
        default="variable",
        help="Event distribution: uniform (equal) or variable (realistic power-law) (default: variable)",
    )

    parser.add_argument(
        "--min-events-per-user",
        type=int,
        default=1,
        help="Minimum events per user - use 300 for training (NVIDIA min_history) (default: 1)",
    )

    parser.add_argument(
        "--unseen-users",
        type=int,
        default=0,
        help="Number of unseen users to add (for generic model testing in inference) (default: 0)",
    )

    parser.add_argument(
        "--duration-days",
        type=int,
        default=60,
        help="Number of days to spread events across - use 60+ for training (default: 60)",
    )

    parser.add_argument(
        "--start-time", type=str, default=None, help="Start timestamp (ISO format, default: now - duration_days)"
    )

    args = parser.parse_args()

    # Parse start time
    if args.start_time:
        start_time = datetime.fromisoformat(args.start_time.replace("Z", "+00:00"))
    else:
        start_time = datetime.now(timezone.utc) - timedelta(days=args.duration_days)

    print(f"Generating {args.num_events} clean, realistic Azure AD events...")
    print(f"  Users: {args.num_users}")
    print(f"  Duration: {args.duration_days} days (concurrent for all users)")
    print(f"  User seed: {args.user_seed} (for user consistency)")
    print(f"  Event seed: {args.event_seed}")
    print(f"  Events per user: {args.events_per_user}")
    print(f"  Min events per user: {args.min_events_per_user}")
    print(f"  Unseen users: {args.unseen_users}")
    print(f"  Start time: {start_time.isoformat()}")
    print("  Realistic variety: 20% travel, 30% device changes, 1-3 event app sessions")

    # Generate data
    generator = AzureADDataGenerator(num_users=args.num_users, user_seed=args.user_seed, event_seed=args.event_seed)
    events = generator.generate_dataset(
        num_events=args.num_events,
        start_time=start_time,
        duration_days=args.duration_days,
        events_per_user=args.events_per_user,
        min_events_per_user=args.min_events_per_user,
        unseen_user_count=args.unseen_users,
    )

    # Save to file
    generator.save_jsonl(events, args.output)

    # Calculate actual user statistics
    unique_users = len({e["properties"]["userPrincipalName"] for e in events})
    user_event_counts = {}
    for e in events:
        user = e["properties"]["userPrincipalName"]
        user_event_counts[user] = user_event_counts.get(user, 0) + 1

    min_user_events = min(user_event_counts.values())
    max_user_events = max(user_event_counts.values())
    avg_user_events = sum(user_event_counts.values()) / len(user_event_counts)

    print(f"\nSuccessfully generated {len(events)} clean events")
    print(f"   Unique users: {unique_users}")
    print(f"   Events per user: min={min_user_events}, max={max_user_events}, avg={avg_user_events:.1f}")
    print("   All events: 100% clean, realistic behavior")

    # NVIDIA DFP compliance check
    if args.min_events_per_user >= 300 and args.duration_days >= 60:
        print("\nNVIDIA DFP Training Compliance:")
        print(f"   • min_events_per_user={args.min_events_per_user} >= 300 (min_history)")
        print(f"   • duration_days={args.duration_days} >= 60 (recommended minimum)")
        print(f"   • All users have concurrent activity over {args.duration_days} days")
    elif args.min_events_per_user == 1:
        print(f"\nNVIDIA DFP Inference Compliance: min_events_per_user={args.min_events_per_user} (no minimum)")
    else:
        print("\nWarning: For NVIDIA DFP training, use:")
        print(f"   • --min-events-per-user 300 (current: {args.min_events_per_user})")
        print(f"   • --duration-days 60 (current: {args.duration_days})")


if __name__ == "__main__":
    main()

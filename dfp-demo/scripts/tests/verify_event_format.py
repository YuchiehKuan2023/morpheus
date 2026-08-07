"""Quick smoke-test: verify get_normal_test_event() emits full training format."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.shared.extract_user_profile import get_normal_test_event  # noqa: E402

username = sys.argv[1] if len(sys.argv) > 1 else "brian.ramirez@wingtiptoys.com"
event = get_normal_test_event(username)

REQUIRED_TOP = [
    "time",
    "category",
    "operationName",
    "resultType",
    "resultDescription",
    "durationMs",
    "callerIpAddress",
    "correlationId",
    "identity",
    "Level",
    "location",
    "properties",
    "location_geoCoordinates_latitude",
    "location_geoCoordinates_longitude",
]
REQUIRED_PROPS = [
    "id",
    "createdDateTime",
    "userDisplayName",
    "userPrincipalName",
    "userId",
    "appId",
    "appDisplayName",
    "ipAddress",
    "clientAppUsed",
    "correlationId",
    "conditionalAccessStatus",
    "isInteractive",
    "riskDetail",
    "riskLevelAggregated",
    "riskLevelDuringSignIn",
    "riskState",
    "resourceDisplayName",
    "resourceId",
    "status",
    "deviceDetail",
    "location",
    "mfaDetail",
    "autonomousSystemNumber",
]

missing_top = [k for k in REQUIRED_TOP if k not in event]
missing_props = [k for k in REQUIRED_PROPS if k not in event["properties"]]
device_id = event["properties"]["deviceDetail"].get("deviceId", "")

ok = not missing_top and not missing_props and device_id

print(f"{'✅' if ok else '❌'} Event format check for {username}")
print(f"   Missing top-level keys : {missing_top or 'none'}")
print(f"   Missing properties keys: {missing_props or 'none'}")
print(f"   deviceId               : {device_id or '(EMPTY)'}")
print(f"   App                    : {event['properties']['appDisplayName']}")
print(f"   Device                 : {event['properties']['deviceDetail']['displayName']}")
print(f"   Browser                : {event['properties']['deviceDetail']['browser']}")
print(f"   OS                     : {event['properties']['deviceDetail']['operatingSystem']}")
print(
    f"   Location               : {event['properties']['location']['city']}, {event['properties']['location']['countryOrRegion']}"
)
print(f"   MFA detail             : {event['properties']['mfaDetail']}")
print(f"   Resource               : {event['properties']['resourceDisplayName']}")
print(f"   ASN                    : {event['properties']['autonomousSystemNumber']}")

if not ok:
    sys.exit(1)

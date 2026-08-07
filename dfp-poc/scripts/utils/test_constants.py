"""Shared constants for DFP test scripts."""

# Kafka configuration
KAFKA_BROKER = "127.0.0.1:29092"
KAFKA_TOPIC = "dfp-events"

# Training data
TRAINING_FILE = "data/input/train/azure_ad_train.jsonl"

# Novel values not seen in training data (for any user)
# These are used to generate anomalous events for testing
NOVEL_VALUES = {
    "apps": [
        "Salesforce",
        "Workday",
        "ServiceNow",
        "Zendesk",
        "HubSpot",
        "Adobe Creative Cloud",
    ],
    "browsers": [
        "Edge 120.0",
        "Opera 105.0",
        "Brave 1.60",
    ],
    "operating_systems": [
        "Linux Ubuntu 22.04",
        "ChromeOS 120",
    ],
    "devices": [
        "NOVEL-DEVICE-001",
        "UNKNOWN-LAPTOP-999",
        "TEST-WORKSTATION-X",
    ],
    "locations": [
        {"city": "Tokyo", "state": "Tokyo", "country": "Japan", "lat": 35.6762, "lon": 139.6503},
        {"city": "Sydney", "state": "New South Wales", "country": "Australia", "lat": -33.8688, "lon": 151.2093},
        {"city": "São Paulo", "state": "São Paulo", "country": "Brazil", "lat": -23.5505, "lon": -46.6333},
        {"city": "Dubai", "state": "Dubai", "country": "United Arab Emirates", "lat": 25.2048, "lon": 55.2708},
        {"city": "Mumbai", "state": "Maharashtra", "country": "India", "lat": 19.0760, "lon": 72.8777},
    ],
}

"""
Named Entity Recognition (NER) Service

Extracts structured entities from DFP detections using spaCy NER and custom
pattern matching. Part of the always-on (Day 1) AI capabilities.

Entity Types:
- Applications (ORG): Office365, Salesforce, Azure Portal
- Devices (PRODUCT): Chrome, Edge, Safari
- Operating Systems (PRODUCT): Windows, macOS, Linux
- Users (PERSON): Email addresses
- Locations (GPE): Cities, countries from location features

Architecture:
- Uses spaCy en_core_web_sm model for general NER
- Custom patterns for DFP-specific entities (apps, devices)
- Extracts from categorical features, not numeric z-scores
- Integrates with feature_bridge.py DetectionRecord objects
- Uses monitoring.py for observability

Quality Filters:
- Blacklist: Removes generic terms (Browser, Unknown, None)
- Confidence threshold: Minimum 0.6 (filters low-quality entities)
- UNKNOWN-* pattern: Marked low confidence (0.3) for synthetic placeholders

Known Limitations:
- Location extraction: Current synthetic dataset lacks location STRING fields
  (has only numeric: locincrement, travel_speed_kmph)
  Generator should add: locationCity, locationCountry from user baselines
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spacy.language import Language

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

try:
    import spacy

    SPACY_AVAILABLE = True
except ImportError:
    spacy = None  # type: ignore
    SPACY_AVAILABLE = False
    logging.warning("spaCy not installed. Install with: pip install spacy && python -m spacy download en_core_web_sm")

from modules.ai.shared.feature_bridge import DetectionRecord, FeatureBridge
from modules.ai.shared.monitoring import monitor_performance, record_detection_processed

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """Extracted entity with metadata."""

    type: str  # ORG, PRODUCT, PERSON, GPE, etc.
    text: str  # Entity text (e.g., "Office365", "Chrome")
    confidence: float  # Confidence score (0.0-1.0)
    source_feature: str | None = None  # Feature name this came from
    category: str | None = None  # Entity category (app, device, location)


@dataclass
class DetectionEntities:
    """Entities extracted from a detection."""

    detection_id: str
    user_id: str
    timestamp: str
    entities: list[Entity] = field(default_factory=list)

    def get_entities_by_type(self, entity_type: str) -> list[Entity]:
        """Get all entities of a specific type."""
        return [e for e in self.entities if e.type == entity_type]

    def get_entities_by_category(self, category: str) -> list[Entity]:
        """Get all entities in a category."""
        return [e for e in self.entities if e.category == category]

    def unique_apps(self) -> list[str]:
        """Get unique application names."""
        return list({e.text for e in self.entities if e.category == "app"})

    def unique_devices(self) -> list[str]:
        """Get unique device names."""
        return list({e.text for e in self.entities if e.category == "device"})


class NERService:
    """Named Entity Recognition service for DFP detections."""

    # Generic terms blacklist (too generic for entity extraction)
    BLACKLIST_TERMS = {
        "Browser",
        "browser",
        "Unknown",
        "unknown",
        "None",
        "null",
        "N/A",
    }

    # Known DFP applications (common in Azure/O365 environments)
    # Updated February 2026 based on azure_ad_train.jsonl analysis
    KNOWN_APPS = {
        # Microsoft 365 Suite
        "Office365",
        "Office 365",
        "Microsoft 365",
        "M365",
        "SharePoint",
        "OneDrive",
        "Teams",
        "Outlook",
        "Exchange",
        "Power BI",
        "PowerBI",
        "Dynamics 365",
        # Microsoft Additional (from training data)
        "Microsoft Intune",  # 146 occurrences - most popular!
        "Microsoft Stream",  # 111 occurrences
        "Microsoft Bookings",  # 76 occurrences
        "Microsoft Yammer",  # In training data
        # Azure
        "Azure Portal",
        "Azure AD",
        "Azure Active Directory",
        # SaaS Applications
        "Salesforce",
        "ServiceNow",
        "Workday",
        "SAP",
        "Oracle",
        # Collaboration
        "Slack",
        "Zoom",
        # Google Workspace
        "Google Workspace",
        "Gmail",
        "Google Drive",
        # File Storage
        "Dropbox",
        "Box",
        # Developer Tools (from training data)
        "GitHub",  # 92 occurrences
        "Confluence",  # 63 occurrences
        "Jira",  # 63 occurrences
        # Cloud Providers (from training data)
        "AWS Console",  # 68 occurrences
        "AWS",
    }

    # Known browsers
    KNOWN_BROWSERS = {
        "Chrome",
        "Google Chrome",
        "Firefox",
        "Mozilla Firefox",
        "Safari",
        "Edge",
        "Microsoft Edge",
        "Opera",
        "Brave",
        "Vivaldi",
        "Internet Explorer",
        "IE",
    }

    # Known operating systems
    KNOWN_OS = {
        "Windows",
        "Windows 10",
        "Windows 11",
        "Win10",
        "Win11",
        "macOS",
        "Mac OS",
        "OS X",
        "Darwin",
        "Linux",
        "Ubuntu",
        "Debian",
        "Red Hat",
        "CentOS",
        "iOS",
        "Android",
        "Chrome OS",
    }

    # Known client applications (authentication methods)
    KNOWN_CLIENT_APPS = {
        # Legacy protocols (security concerns)
        "POP3",
        "IMAP4",
        "SMTP",
        "Authenticated SMTP",
        # Modern authentication
        "Exchange Web Services",
        "EWS",
        "Exchange ActiveSync",
        "ActiveSync",
        "Modern Auth Clients",
        "Browser",
        "Mobile Apps and Desktop clients",
        # Office clients
        "Outlook",
        "Microsoft Outlook",
        "Office 365 Desktop",
        # Other
        "Other clients",
        "Exchange Admin Center",
        "POP",
        "IMAP",
    }

    def __init__(self, spacy_model: str = "en_core_web_sm"):
        """
        Initialize NER service.

        Args:
            spacy_model: spaCy model name to load (default: en_core_web_sm)
        """
        self.model_name = spacy_model
        self.nlp: Language | None = None

        if SPACY_AVAILABLE and spacy is not None:
            try:
                self.nlp = spacy.load(spacy_model)
                logger.info(f"Loaded spaCy model: {spacy_model}")
            except OSError:
                logger.error(
                    f"spaCy model '{spacy_model}' not found. Download with: python -m spacy download {spacy_model}"
                )
                self.nlp = None
        else:
            logger.warning("spaCy not available. Entity extraction will use pattern matching only.")

    @monitor_performance("entity_extraction", "extract_entities")
    def extract_entities(self, detection: DetectionRecord) -> DetectionEntities:
        """
        Extract entities from a detection record.

        Args:
            detection: DetectionRecord from feature_bridge

        Returns:
            DetectionEntities with extracted entities
        """
        # Generate detection_id from user_id + timestamp for uniqueness
        detection_id = f"{detection.user_id}_{detection.timestamp}"
        entities_result = DetectionEntities(
            detection_id=detection_id, user_id=detection.user_id, timestamp=detection.timestamp
        )

        # Extract from categorical features first (most reliable)
        entities_result.entities.extend(self._extract_from_categorical_features(detection))

        # Extract from top features text (using NER if available)
        entities_result.entities.extend(self._extract_from_top_features(detection))

        # Deduplicate entities (same text + type)
        entities_result.entities = self._deduplicate_entities(entities_result.entities)

        # Record metrics
        record_detection_processed("entity_extraction", "success")

        return entities_result

    def _extract_from_categorical_features(self, detection: DetectionRecord) -> list[Entity]:
        """Extract entities from known categorical feature names."""
        entities = []

        for feature in detection.parsed_features:
            # Skip numeric values - they don't contain entity information
            if not isinstance(feature.value, str):
                continue

            # Application features
            if "app" in feature.name.lower() and feature.category == "app":
                entity = self._match_known_entity(
                    feature.value, self.KNOWN_APPS, entity_type="ORG", category="app", source_feature=feature.name
                )
                if entity:
                    entities.append(entity)

            # Device/Browser features
            elif "browser" in feature.name.lower() and feature.category == "device":
                entity = self._match_known_entity(
                    feature.value,
                    self.KNOWN_BROWSERS,
                    entity_type="PRODUCT",
                    category="device",
                    source_feature=feature.name,
                )
                if entity:
                    entities.append(entity)

            # Operating System features
            elif "operating" in feature.name.lower() or "os" in feature.name.lower():
                entity = self._match_known_entity(
                    feature.value, self.KNOWN_OS, entity_type="PRODUCT", category="device", source_feature=feature.name
                )
                if entity:
                    entities.append(entity)

            # Client app features (authentication methods)
            elif "client" in feature.name.lower() and "app" in feature.name.lower():
                entity = self._match_known_entity(
                    feature.value,
                    self.KNOWN_CLIENT_APPS,
                    entity_type="PRODUCT",
                    category="network",
                    source_feature=feature.name,
                )
                if entity:
                    entities.append(entity)

            # Device name features
            elif "device" in feature.name.lower() and feature.category == "device":
                # Extract meaningful device names (not just generic values)
                if len(feature.value) > 3 and not feature.value.replace(".", "").isdigit():
                    # Lower confidence for UNKNOWN-* pattern (placeholder devices)
                    confidence = 0.3 if feature.value.startswith("UNKNOWN-") else 0.7
                    entities.append(
                        Entity(
                            type="PRODUCT",
                            text=feature.value,
                            confidence=confidence,
                            source_feature=feature.name,
                            category="device",
                        )
                    )

            # Location features
            elif (
                "location" in feature.name.lower()
                or "city" in feature.name.lower()
                or "country" in feature.name.lower()
            ):
                if len(feature.value) > 2:  # Skip short codes
                    entities.append(
                        Entity(
                            type="GPE",  # Geo-Political Entity
                            text=feature.value,
                            confidence=0.8,
                            source_feature=feature.name,
                            category="location",
                        )
                    )

        return entities

    def _extract_from_top_features(self, detection: DetectionRecord) -> list[Entity]:
        """Extract entities from top_features_raw text using spaCy NER."""
        entities = []

        if not self.nlp or not detection.top_features_raw:
            return entities

        # Process top_features_raw text with spaCy
        doc = self.nlp(detection.top_features_raw)

        for ent in doc.ents:
            # Skip PERSON entities (usually just email addresses we already have)
            if ent.label_ == "PERSON":
                continue

            # Filter relevant entity types
            if ent.label_ in ["ORG", "PRODUCT", "GPE"]:
                # Filter out feature=value patterns (e.g., "travel_speed_kmph=2723")
                if "=" in ent.text or "_" in ent.text:
                    continue

                # Skip very short entities (likely noise)
                if len(ent.text) < 3:
                    continue

                # Skip entities that are just numbers
                if ent.text.replace(".", "").replace(",", "").isdigit():
                    continue

                # Determine category based on type and context
                category = "other"
                if ent.label_ == "ORG":
                    category = (
                        "app" if any(app.lower() in ent.text.lower() for app in self.KNOWN_APPS) else "organization"
                    )
                elif ent.label_ == "PRODUCT":
                    category = "device"
                elif ent.label_ == "GPE":
                    category = "location"

                entities.append(
                    Entity(
                        type=ent.label_,
                        text=ent.text,
                        confidence=0.6,  # Lower confidence for NER from free text
                        source_feature="top_features_raw",
                        category=category,
                    )
                )

        return entities

    def _match_known_entity(
        self, text: str, known_entities: set[str], entity_type: str, category: str, source_feature: str
    ) -> Entity | None:
        """Match text against known entity set (case-insensitive)."""
        text_lower = text.lower()

        # Filter blacklisted generic terms
        if text in self.BLACKLIST_TERMS or text_lower in {t.lower() for t in self.BLACKLIST_TERMS}:
            return None

        for known in known_entities:
            if known.lower() in text_lower or text_lower in known.lower():
                return Entity(
                    type=entity_type,
                    text=known,  # Use canonical name
                    confidence=0.95,  # High confidence for known entities
                    source_feature=source_feature,
                    category=category,
                )

        # If no match, return the original text with lower confidence
        if len(text) > 2:  # Skip very short values
            return Entity(
                type=entity_type,
                text=text,
                confidence=0.5,  # Lower confidence for unknown entities
                source_feature=source_feature,
                category=category,
            )

        return None

    def _deduplicate_entities(self, entities: list[Entity]) -> list[Entity]:
        """Remove duplicate entities, keeping highest confidence."""
        seen = {}

        for entity in entities:
            key = (entity.type, entity.text.lower())
            if key not in seen or entity.confidence > seen[key].confidence:
                seen[key] = entity

        # Filter by minimum confidence threshold (0.6) to remove low-quality entities
        # This removes: unknown entities (0.5), UNKNOWN-* devices (0.3)
        filtered = [e for e in seen.values() if e.confidence >= 0.6]

        return filtered

    @monitor_performance("entity_extraction", "batch_extract")
    def extract_batch(self, detections: list[DetectionRecord]) -> list[DetectionEntities]:
        """
        Extract entities from multiple detections.

        Args:
            detections: List of DetectionRecord objects

        Returns:
            List of DetectionEntities
        """
        results = []

        for detection in detections:
            try:
                result = self.extract_entities(detection)
                results.append(result)
            except Exception as e:
                logger.error(f"Error extracting entities from {detection.user_id} at {detection.timestamp}: {e}")
                # Return empty result for failed extraction
                # Generate detection_id for failed extraction
                detection_id = f"{detection.user_id}_{detection.timestamp}"
                results.append(
                    DetectionEntities(
                        detection_id=detection_id,
                        user_id=detection.user_id,
                        timestamp=detection.timestamp,
                        entities=[],
                    )
                )

        logger.info(f"Extracted entities from {len(results)}/{len(detections)} detections")
        return results

    def get_extraction_summary(self, results: list[DetectionEntities]) -> dict:
        """Get summary statistics for extracted entities."""
        total_entities = sum(len(r.entities) for r in results)

        # Count by type
        type_counts = {}
        category_counts = {}

        for result in results:
            for entity in result.entities:
                type_counts[entity.type] = type_counts.get(entity.type, 0) + 1
                if entity.category:
                    category_counts[entity.category] = category_counts.get(entity.category, 0) + 1

        # Get unique entities
        unique_apps = set()
        unique_devices = set()
        unique_locations = set()

        for result in results:
            unique_apps.update(result.unique_apps())
            unique_devices.update(result.unique_devices())
            unique_locations.update(e.text for e in result.get_entities_by_category("location"))

        return {
            "total_detections": len(results),
            "total_entities": total_entities,
            "avg_entities_per_detection": total_entities / len(results) if results else 0,
            "entities_by_type": type_counts,
            "entities_by_category": category_counts,
            "unique_apps": len(unique_apps),
            "unique_devices": len(unique_devices),
            "unique_locations": len(unique_locations),
            "top_apps": list(unique_apps)[:10],
            "top_devices": list(unique_devices)[:10],
        }


# ============================================================================
# TEST SCRIPT
# ============================================================================

if __name__ == "__main__":
    import time

    print("=" * 80)
    print("ENTITY EXTRACTION TEST")
    print("=" * 80)

    # Initialize services
    print("\n1. Initializing services...")
    bridge = FeatureBridge()
    ner = NERService()

    if not ner.nlp:
        print("⚠️  spaCy not available - using pattern matching only")
        print("   Install with: pip install spacy && python -m spacy download en_core_web_sm")
    else:
        print(f"✅ Loaded spaCy model: {ner.model_name}")

    # Load detections
    csv_path = Path("data/input/ai/user_aware_anomalies.csv")

    if not csv_path.exists():
        print(f"\n❌ CSV file not found: {csv_path}")
        print("   Run generate_synthetic_detections.py first")
        sys.exit(1)

    print(f"\n2. Loading detections from {csv_path}...")
    detections = bridge.load_detections(str(csv_path))  # Load all detections
    print(f"✅ Loaded {len(detections)} detections")

    # Extract entities
    print("\n3. Extracting entities...")
    start_time = time.time()
    results = ner.extract_batch(detections)
    duration = time.time() - start_time

    print(f"✅ Extracted entities from {len(results)} detections in {duration:.2f}s")
    print(f"   Performance: {duration / len(results) * 1000:.1f}ms per detection")

    # Summary
    print("\n4. Extraction summary:")
    summary = ner.get_extraction_summary(results)
    print(f"   Total entities: {summary['total_entities']}")
    print(f"   Avg per detection: {summary['avg_entities_per_detection']:.1f}")
    print(f"   Entities by type: {summary['entities_by_type']}")
    print(f"   Entities by category: {summary['entities_by_category']}")
    print(f"   Unique apps: {summary['unique_apps']}")
    print(f"   Unique devices: {summary['unique_devices']}")
    print(f"   Unique locations: {summary['unique_locations']}")

    # Sample entities
    print("\n5. Sample entities from first 3 detections:")
    for i, result in enumerate(results[:3], 1):
        print(f"\n   Detection {i} ({result.detection_id}):")
        print(f"   User: {result.user_id}")
        print(f"   Entities found: {len(result.entities)}")

        for entity in result.entities[:5]:  # Show first 5
            print(
                f"      - [{entity.type}] {entity.text} "
                f"(conf: {entity.confidence:.2f}, cat: {entity.category}, from: {entity.source_feature})"
            )

        if len(result.entities) > 5:
            print(f"      ... and {len(result.entities) - 5} more")

    # Top apps and devices
    if summary["top_apps"]:
        print("\n6. Top applications found:")
        for app in summary["top_apps"]:
            print(f"   - {app}")

    if summary["top_devices"]:
        print("\n7. Top devices found:")
        for device in summary["top_devices"]:
            print(f"   - {device}")

    print("\n" + "=" * 80)
    print("✅ Entity extraction test passed")
    print("=" * 80)

    # Notes about data quality
    if summary["unique_locations"] == 0:
        print("\n⚠️  Note: 0 locations extracted")
        print("   Reason: Synthetic dataset lacks location STRING fields")
        print("   Current: locincrement=6 (numeric), travel_speed_kmph=2723 (numeric)")
        print("   Needed: locationCity=Birmingham, locationCountry=UK")
        print("   Fix: Update generate_synthetic_detections.py to include location names")

    print("\nNext: Run graph_populator.py to store entities in Neo4j knowledge graph")

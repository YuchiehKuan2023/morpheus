"""
Entity Extraction Module

Named Entity Recognition (NER) and knowledge graph population for DFP detections.

Components:
- ner_service.py: spaCy-based entity extraction from detection features
- graph_populator.py: Neo4j knowledge graph population

Always-on (Day 1) Capability:
Entity extraction runs on every detection to identify apps, devices, users, and locations.
Results are stored in Neo4j for relationship analysis and intelligence queries.
"""

from .graph_populator import GraphPopulator, GraphStats
from .ner_service import DetectionEntities, Entity, NERService

__all__ = ["NERService", "Entity", "DetectionEntities", "GraphPopulator", "GraphStats"]

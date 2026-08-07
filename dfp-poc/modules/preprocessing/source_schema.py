"""
Source Schema Builder for NVIDIA Azure AD Logs

This module creates the source schema that transforms raw Azure AD logs
(with nested JSON) into the flattened format expected by preprocessing.

NVIDIA Reference:
    nv-morpheus/python/morpheus_dfp/morpheus_dfp/utils/schema_utils.py
    Lines 51-100: _build_azure_schema() source schema definition

Pattern:
    Raw Log (nested) → Source Schema Transform → Flattened DataFrame → Preprocessing Schema
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.preprocessing.column_info import DataFrameInputSchema

logger = logging.getLogger(__name__)


def build_azure_source_schema() -> DataFrameInputSchema:
    """
    Build NVIDIA-compliant source schema for Azure AD authentication logs.

    This schema:
    1. Flattens nested "properties" JSON object
    2. Renames "time" → "timestamp"
    3. Renames "properties.userPrincipalName" → "username"
    4. Creates "location" field from "properties.location.city" + "countryOrRegion"
    5. Flattens device details
    6. Flattens status fields

    Reference:
        NVIDIA: nv-morpheus/.../schema_utils.py lines 51-100

    Returns:
        DataFrameInputSchema configured for source data transformation

    Example:
        >>> # Raw log structure:
        >>> {
        ...     "time": "2024-01-01T10:00:00Z",
        ...     "category": "SignInLogs",
        ...     "properties": {
        ...         "userPrincipalName": "user@company.com",
        ...         "appDisplayName": "Office 365",
        ...         "location": {
        ...             "city": "London",
        ...             "countryOrRegion": "UK"
        ...         },
        ...         "deviceDetail": {
        ...             "browser": "Chrome"
        ...         }
        ...     }
        ... }
        >>>
        >>> # After source schema transform:
        >>> {
        ...     "timestamp": "2024-01-01T10:00:00Z",
        ...     "username": "user@company.com",
        ...     "appDisplayName": "Office 365",
        ...     "location": "London, UK",  # StringCatColumn
        ...     "deviceDetailbrowser": "Chrome",
        ...     "category": "SignInLogs"
        ... }
    """
    from modules.preprocessing.column_info import ColumnInfo, DataFrameInputSchema, DateTimeColumn, StringCatColumn

    # NVIDIA pattern: Define source column transformations
    # Note: RenameColumn is just ColumnInfo with different input_name
    source_column_info = [
        # Timestamp: Rename "time" → "timestamp" and parse as datetime
        DateTimeColumn(name="timestamp", dtype=datetime, input_name="time"),
        # User: Rename top-level identity field to username
        # Note: Raw data has "identity" not "properties.userPrincipalName"
        ColumnInfo(name="username", dtype=str, input_name="identity"),
        # Category (top-level, keep as-is)
        ColumnInfo(name="category", dtype=str),
        # Application/Resource
        ColumnInfo(name="appDisplayName", dtype=str, input_name="properties.appDisplayName"),
        ColumnInfo(name="resourceDisplayName", dtype=str, input_name="properties.resourceDisplayName"),
        ColumnInfo(name="clientAppUsed", dtype=str, input_name="properties.clientAppUsed"),
        # Device details (nested in properties.deviceDetail)
        ColumnInfo(name="deviceDetailbrowser", dtype=str, input_name="properties.deviceDetail.browser"),
        ColumnInfo(name="deviceDetaildisplayName", dtype=str, input_name="properties.deviceDetail.displayName"),
        ColumnInfo(name="deviceDetailoperatingSystem", dtype=str, input_name="properties.deviceDetail.operatingSystem"),
        # NVIDIA PATTERN: Create "location" field from city + country using StringCatColumn
        # This is THE KEY transformation that creates the "location" field for locincrement
        # NOTE: In Azure AD logs, location is NESTED in properties, not top-level!
        # After flattening, it becomes properties.location.city and properties.location.countryOrRegion
        StringCatColumn(
            name="location",
            dtype=str,
            input_columns=[
                "properties.location.city",
                "properties.location.countryOrRegion",
            ],
            sep=", ",
        ),
        # Location coordinates (top-level location.geoCoordinates)
        ColumnInfo(name="location_geoCoordinates_latitude", dtype=float, input_name="location.geoCoordinates.latitude"),
        ColumnInfo(
            name="location_geoCoordinates_longitude", dtype=float, input_name="location.geoCoordinates.longitude"
        ),
        # Status (nested in properties.status)
        ColumnInfo(name="statusfailureReason", dtype=str, input_name="properties.status.failureReason"),
    ]

    # NVIDIA pattern: Specify JSON columns to flatten
    # Azure AD logs have nested "properties" and "location" objects that must be flattened
    # This creates columns like "properties.appDisplayName", "location.city", "properties.deviceDetail.browser"
    schema = DataFrameInputSchema(
        json_columns=["properties", "location"],  # Flatten both properties and location objects
        column_info=source_column_info,
        preserve_columns=[
            "category",  # Keep top-level non-JSON fields
            "location_geoCoordinates_latitude",  # Preserve flattened coordinates from test events
            "location_geoCoordinates_longitude",  # Required for geographic features
        ],
    )

    logger.info("Built NVIDIA-compliant Azure AD source schema")
    logger.debug(f"Source schema: {len(source_column_info)} columns, json_columns={schema.json_columns}")

    return schema


__all__ = ["build_azure_source_schema"]

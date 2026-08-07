#!/usr/bin/env python3
import json

import psycopg2

from modules.utils.db import get_db_params

conn = psycopg2.connect(**get_db_params())

cursor = conn.cursor()
cursor.execute("SELECT user_id, ai_enrichment FROM enriched_anomalies LIMIT 20")

print("Checking similarity scores across 20 detections:\n")

self_match_count = 0
total_with_similar = 0

for row in cursor.fetchall():
    user_id = row[0]
    enrichment = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    similar = enrichment.get("similar_detections", [])

    if similar:
        total_with_similar += 1
        scores = [s.get("similarity_score", 0) for s in similar]

        # Check if first match is suspiciously high (self-match)
        if scores[0] > 0.99:
            self_match_count += 1
            status = "<- SELF-MATCH!"
        else:
            status = ""

        print(f"{user_id[:35]:35} | {len(similar)} similar | {[round(s, 3) for s in scores]} {status}")

print("\nSummary:")
print(f"  Total with similar detections: {total_with_similar}")
print(f"  Self-matches (score > 0.99): {self_match_count}")
print(f"  Properly filtered: {total_with_similar - self_match_count}")

cursor.close()
conn.close()

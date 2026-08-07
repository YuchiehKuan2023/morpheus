# DFP Database Schema Reference

## Used by the AI router at startup — edit here, restart backend to pick up changes

## Format: table.column (type [enum values]) — description

---

## enriched_anomalies

Primary anomaly detection records — one row per detected anomaly event.

| Column                    | Type      | Values / Notes                                                                                                                                                  |
| ------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| anomaly_id                | uuid PK   | Primary key                                                                                                                                                     |
| user_id                   | varchar   | Email address, e.g. `alice.smith@company.com`                                                                                                                   |
| timestamp                 | timestamp | When the sign-in event occurred (no timezone)                                                                                                                   |
| anomaly_score             | float     | Raw DFP model output score                                                                                                                                      |
| mean_abs_z                | float     | Mean absolute z-score across features                                                                                                                           |
| risk_score                | float     | 0–100 composite risk score                                                                                                                                      |
| severity                  | varchar   | `CRITICAL` / `HIGH` / `MEDIUM` / `LOW`                                                                                                                          |
| root_cause                | varchar   | `Geographic Anomaly` / `Browser Anomaly` / `OS Anomaly` / `Unmanaged Device` / `Unauthorized Application Access` / `Account Takeover` / `Multi-Factor Incident` |
| sub_category              | varchar   | More specific classification within root_cause                                                                                                                  |
| status                    | varchar   | `new` / `pending` / `resolved` — workflow lifecycle only. Verdict stored in `analyst_verdict`.                                                                  |
| assigned_to               | integer   | Analyst user ID this anomaly is assigned to (FK → analyst_users.id)                                                                                             |
| validated_by              | varchar   | Analyst who validated it                                                                                                                                        |
| validated_at              | timestamp | When it was validated                                                                                                                                           |
| validation_confidence     | float     | Confidence in the validation decision                                                                                                                           |
| validation_reasoning      | text      | Free-text reasoning for the validation                                                                                                                          |
| classified_by             | varchar   | Who/what classified severity (e.g. `llm`, analyst username)                                                                                                     |
| classified_at             | timestamp | When severity was classified                                                                                                                                    |
| classification_confidence | float     | 0–1 confidence in severity classification                                                                                                                       |
| classification_reasoning  | text      | Reasoning behind the severity classification                                                                                                                    |
| resolved_at               | timestamp | When status moved to `resolved`                                                                                                                                 |
| resolution_notes          | text      | Free-text notes on resolution                                                                                                                                   |
| feedback_to_dfp           | boolean   | Whether this anomaly has been fed back to retrain the DFP model                                                                                                 |
| dfp_retrain_status        | varchar   | Retrain job status for this anomaly                                                                                                                             |
| dfp_retrained_at          | timestamp | When the retrain based on this feedback completed                                                                                                               |
| source                    | varchar   | Origin of the anomaly (e.g. `dfp`, `manual`)                                                                                                                    |
| is_anomaly                | boolean   | Confirmed anomaly flag                                                                                                                                          |
| created_at                | timestamp | Record creation time                                                                                                                                            |
| updated_at                | timestamp | Record last update time                                                                                                                                         |

### enriched_anomalies.original_event (jsonb)

Raw Azure AD / Entra sign-in log event.

```bash
original_event->>'callerIpAddress'                          IP address of the sign-in
original_event->'location'->>'city'                         City of the sign-in
original_event->'location'->>'countryOrRegion'              Country of the sign-in
original_event->'location'->>'state'                        State/region of the sign-in
original_event->'location'->'geoCoordinates'->>'latitude'   Latitude (numeric text)
original_event->'location'->'geoCoordinates'->>'longitude'  Longitude (numeric text)
original_event->>'identity'                                 User principal name / email
original_event->>'operationName'                            e.g. "Sign-in activity"
original_event->>'resultType'                               "0" = success, other = error code
original_event->>'resultDescription'                        e.g. "Success", "Invalid password"
original_event->>'category'                                 e.g. "SignInLogs"
original_event->'properties'->>'appDisplayName'             Application accessed, e.g. "ServiceNow"
original_event->'properties'->>'appId'                      Application GUID
original_event->'properties'->>'clientAppUsed'              Client auth method, e.g. "Authenticated SMTP"
original_event->'properties'->>'ipAddress'                  IP (also at top-level callerIpAddress)
original_event->'properties'->>'isInteractive'              boolean — interactive sign-in?
original_event->'properties'->'deviceDetail'->>'displayName'        Device hostname, e.g. "MOBILE-MOORE-1787"
original_event->'properties'->'deviceDetail'->>'operatingSystem'    OS, e.g. "ChromeOS 120", "Windows 11"
original_event->'properties'->'deviceDetail'->>'browser'            Browser, e.g. "Firefox 119.0", "Chrome 120"
original_event->'properties'->'deviceDetail'->>'isManaged'          boolean — managed device?
original_event->'properties'->'deviceDetail'->>'isCompliant'        boolean — compliant device?
original_event->'properties'->'deviceDetail'->>'trustType'          e.g. "Hybrid Azure AD joined"
original_event->'properties'->'mfaDetail'->>'authMethod'            MFA method, e.g. "Phone App Notification"
original_event->'properties'->'mfaDetail'->>'authDetail'            MFA outcome, e.g. "Approved"
original_event->'properties'->>'conditionalAccessStatus'            e.g. "success", "failure"
original_event->'properties'->>'riskState'                          e.g. "none", "atRisk"
original_event->'properties'->>'riskLevelAggregated'                e.g. "none", "medium", "high"
original_event->'properties'->'status'->>'errorCode'                Sign-in error code (integer)
original_event->'properties'->'status'->>'failureReason'            Failure description
original_event->>'durationMs'                               Sign-in duration in milliseconds
```

### enriched_anomalies.raw_detection (jsonb)

DFP model detection output with z-scored features.

```bash
raw_detection->>'user_id'           Email — same as user_id column
raw_detection->>'anomaly_score'     Float — raw model score
raw_detection->>'max_abs_z'         Highest z-score across all features
raw_detection->>'threshold'         Decision threshold used (e.g. 2.0)
raw_detection->>'top_features'      Human-readable summary, e.g. "deviceDetailoperatingSystem=ChromeOS 120 (z=17.32)"
raw_detection->>'event_count'       Number of events in the detection window
raw_detection->>'feature_count'     Number of features evaluated
raw_detection->'features'           JSON array of {feature, value, z_score} objects
                                    Each feature name mirrors the original_event field path without dots,
                                    e.g. "deviceDetailoperatingSystem", "appDisplayName", "locincrement"
```

### enriched_anomalies.risk_factors (jsonb)

Structured risk factor breakdown (set by classification step).

### enriched_anomalies.ai_enrichment (jsonb)

Additional AI-generated enrichment data.

---

## monitored_users

Baseline behaviour profiles for all monitored employees.

| Column                                      | Type       | Notes                                                                |
| ------------------------------------------- | ---------- | -------------------------------------------------------------------- |
| id                                          | integer PK |                                                                      |
| username                                    | text       | Email address (matches enriched_anomalies.user_id)                   |
| display_name                                | text       | Full name                                                            |
| first_name / last_name                      | text       |                                                                      |
| email                                       | text       | Same as username                                                     |
| company                                     | text       | e.g. "TechSolutions"                                                 |
| department                                  | text       | e.g. "Engineering", "Finance", "HR", "Sales"                         |
| user_role                                   | text       | e.g. "employee", "admin", "contractor"                               |
| job_title                                   | text       | e.g. "Senior Engineer", "CFO"                                        |
| seniority                                   | text       | e.g. "senior", "junior", "manager"                                   |
| primary_location_city                       | text       | Normal working city                                                  |
| primary_location_country                    | text       | Normal working country                                               |
| home_location_lat / lon                     | numeric    | Lat/lon of primary location                                          |
| primary_os                                  | text       | Most common OS                                                       |
| primary_browser                             | text       | Most common browser                                                  |
| primary_device                              | text       | Most common device name                                              |
| work_hours_start                            | integer    | Hour of day (0–23) work typically starts                             |
| work_hours_end                              | integer    | Hour of day (0–23) work typically ends                               |
| active_days                                 | text[]     | Array of weekdays, e.g. `{Monday,Tuesday,Wednesday,Thursday,Friday}` |
| corp_vpn                                    | boolean    | Whether user typically uses corporate VPN                            |
| total_events                                | integer    | Total sign-in events in training window                              |
| apps                                        | jsonb      | Array of `{name, frequency}` — apps used and how often               |
| devices                                     | jsonb      | Device usage history                                                 |
| all_locations                               | jsonb      | All locations ever seen for this user                                |
| avatar_color / avatar_initials / avatar_url | text       | UI fields                                                            |

---

## llm_explanations

LLM-generated analytical explanation for each anomaly.

| Column                      | Type              | Notes                                                                      |
| --------------------------- | ----------------- | -------------------------------------------------------------------------- |
| id                          | integer PK        |                                                                            |
| detection_id                | uuid              | FK → enriched_anomalies.anomaly_id                                         |
| version                     | integer           | Explanation version (latest = max version)                                 |
| explanation_type            | varchar           | Type of explanation generated                                              |
| context_analysis            | text              | What happened — narrative context                                          |
| pattern_analysis            | text              | Behavioural pattern identified                                             |
| risk_assessment             | text              | Risk narrative                                                             |
| recommendations             | text              | Recommended actions                                                        |
| reasoning_process           | text              | Step-by-step LLM reasoning                                                 |
| confidence_score            | numeric           | 0–1 confidence                                                             |
| hallucination_risk          | varchar           | `low` / `medium` / `high`                                                  |
| cold_start                  | boolean           | True if generated without historical context                               |
| model_name                  | varchar           | LLM model used                                                             |
| total_tokens                | integer           | Total tokens consumed                                                      |
| cost_usd                    | numeric           | API cost for this explanation                                              |
| latency_ms                  | numeric           | Generation latency                                                         |
| human_feedback              | varchar           | Analyst feedback on explanation quality                                    |
| human_rating                | integer           | 1–5 rating                                                                 |
| validated_by / validated_at | varchar/timestamp |                                                                            |
| anomaly_classification      | jsonb             | `{label: "true_positive"/"false_positive"/"uncertain", confidence: float}` |
| evidence_summary            | jsonb             | Structured evidence references                                             |
| similar_cases_cited         | jsonb             | Similar past cases referenced                                              |
| graph_insights_used         | jsonb             | Neo4j graph data used in analysis                                          |
| entities_referenced         | jsonb             | Entities mentioned in explanation                                          |
| severity_level              | varchar           | CRITICAL / HIGH / MEDIUM / LOW                                             |
| created_at                  | timestamp         |                                                                            |

---

## agent_investigations

AI agent investigation runs triggered per anomaly.

| Column                 | Type        | Notes                                                          |
| ---------------------- | ----------- | -------------------------------------------------------------- |
| investigation_id       | uuid PK     |                                                                |
| anomaly_id             | uuid        | FK → enriched_anomalies.anomaly_id                             |
| triggered_at           | timestamptz | When the investigation started                                 |
| completed_at           | timestamptz | When it finished                                               |
| status                 | text        | `pending` / `running` / `completed` / `failed`                 |
| severity_at_trigger    | text        | Severity when investigation was triggered                      |
| agents_invoked         | text[]      | Which agents ran, e.g. `{forensics,investigation,remediation}` |
| confidence_score       | float       | Overall investigation confidence                               |
| overall_recommendation | text        | Top-line recommendation                                        |
| raw_report             | jsonb       | Full structured report                                         |

---

## agent_findings

Individual agent outputs within an investigation.

| Column                    | Type        | Notes                                                                                                                     |
| ------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| finding_id                | uuid PK     |                                                                                                                           |
| investigation_id          | uuid        | FK → agent_investigations.investigation_id                                                                                |
| agent_type                | text        | `forensics` / `investigation` / `remediation`                                                                             |
| started_at / completed_at | timestamptz |                                                                                                                           |
| status                    | text        | `completed` / `failed` / `running`                                                                                        |
| result                    | jsonb       | Agent-specific output: narrative, attack_chain[], entry_point, entities_involved[], lateral_movement_detected, confidence |
| llm_tokens_used           | integer     |                                                                                                                           |
| latency_ms                | integer     |                                                                                                                           |

---

## analyst_users

Platform analysts who investigate and resolve anomalies.

| Column                 | Type       | Notes                                                 |
| ---------------------- | ---------- | ----------------------------------------------------- |
| id                     | integer PK |                                                       |
| username               | text       | Matches enriched_anomalies.assigned_to / validated_by |
| display_name           | text       |                                                       |
| first_name / last_name | text       |                                                       |
| email                  | text       |                                                       |
| analyst_role           | text       | e.g. "analyst", "senior_analyst", "manager"           |
| level                  | integer    | Seniority level                                       |
| is_active              | boolean    |                                                       |

---

## Key JOIN patterns

```sql
-- Anomalies with their LLM explanation
enriched_anomalies ea
JOIN llm_explanations le ON le.detection_id = ea.anomaly_id

-- Anomalies with investigation findings
enriched_anomalies ea
JOIN agent_investigations ai ON ai.anomaly_id = ea.anomaly_id
JOIN agent_findings af ON af.investigation_id = ai.investigation_id

-- Anomaly with analyst who owns it
enriched_anomalies ea
JOIN analyst_users au ON au.id = ea.assigned_to

-- Anomaly with monitored user baseline
enriched_anomalies ea
JOIN monitored_users mu ON mu.username = ea.user_id
```

---

## Notes on JSONB querying

- Use `->>` to extract as text (for WHERE, comparisons, display)
- Use `->` to extract as jsonb (for nested access)
- Cast to numeric for math: `(original_event->'location'->'geoCoordinates'->>'latitude')::numeric`
- Array containment for active_days: `'Monday' = ANY(active_days)`
- JSONB array elements: `jsonb_array_elements(raw_detection->'features')` returns one row per feature

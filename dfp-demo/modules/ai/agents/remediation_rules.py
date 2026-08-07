"""
Remediation rules — static lookup of response actions per threat category.

No external dependencies; pure data used by RemediationAgent.

Usage:
    from modules.ai.agents.remediation_rules import get_actions

    actions, compliance_flags = get_actions("Account Takeover", "CRITICAL")
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RemediationAction:
    """A single recommended response action."""

    priority: int  # 1 = highest priority
    action: str
    rationale: str = field(default="")  # populated by the LLM at runtime
    auto_actionable: bool = False  # True → can be executed without human approval


# ------------------------------------------------------------------
# Static rule catalogue
# Each value is a list of (action_text, auto_actionable) tuples.
# Priority is assigned by position (index 0 → priority 1).
# ------------------------------------------------------------------

RULES: dict[str, list[tuple[str, bool]]] = {
    "Account Takeover": [
        ("Disable user account immediately", False),
        ("Revoke all active OAuth tokens and sessions", True),
        ("Force MFA re-enrolment on next login", False),
        ("Notify user's line manager", False),
    ],
    "Privilege Escalation": [
        ("Revert all permission grants made in the last 24 hours", False),
        ("Audit recent permission grant history in PAM system", False),
        ("Review role assignment logs for approver chain", False),
        ("Alert identity governance team", False),
    ],
    "Data Exfiltration": [
        ("Block egress to destination IP/domain", True),
        ("Quarantine device from corporate network", False),
        ("Trigger DLP scan on all OneDrive/SharePoint activity last 24h", False),
        ("Initiate GDPR Art.33 notification assessment", False),
        ("Preserve full audit trail for legal hold", False),
    ],
    "Insider Threat": [
        ("Restrict account to read-only access immediately", False),
        ("Notify HR and Legal simultaneously", False),
        ("Preserve all audit logs (legal hold — do not delete)", False),
        ("Escalate to CISO", False),
    ],
    "Brute Force": [
        ("Block source IP on perimeter firewall", True),
        ("Rate-limit login endpoint for affected account", True),
        ("Enable step-up MFA for all logins from this IP range", False),
    ],
    "Credential Stuffing": [
        ("Force password reset for affected account", False),
        ("Prompt MFA on next login", False),
        ("Monitor all logins from same IP /24 subnet for 48h", False),
    ],
    "Anomalous Access": [
        ("Flag anomaly for manual SOC review", False),
        ("Temporarily restrict access scope to core applications only", False),
    ],
    # --- Root causes produced by the classifier's ROOT_CAUSE_MAP ---
    "Geographic Anomaly": [
        ("Verify legitimacy of login with the user out-of-band", False),
        ("Temporarily block sign-in from the anomalous location", True),
        ("Check for concurrent active sessions from different geographies", True),
        ("Request travel confirmation or escalate to SOC if unconfirmed", False),
    ],
    "Unmanaged Device": [
        ("Block Conditional Access for non-compliant device immediately", True),
        ("Prompt user to enrol device in MDM or switch to managed device", False),
        ("Review Intune / Endpoint Manager for recent device registrations", False),
        ("Restrict session to read-only until device compliance confirmed", False),
    ],
    "Unauthorized Application Access": [
        ("Revoke OAuth consent grant for the accessed application", True),
        ("Audit all application permissions granted by the user in the last 7 days", False),
        ("Alert application owner and security team", False),
        ("Review conditional access policies for this application", False),
    ],
    "Browser Anomaly": [
        ("Flag session for SOC review", False),
        ("Prompt step-up MFA for the current session", True),
        ("Check for known malicious browser extensions or user-agent spoofing", False),
    ],
    "OS Anomaly": [
        ("Prompt step-up MFA for the current session", True),
        ("Verify device integrity via EDR telemetry", False),
        ("Restrict access until OS version is confirmed legitimate", False),
    ],
    # --- Multi-feature catch-all root causes (formerly mapped to "Account Takeover") ---
    "Multi-Factor Incident": [
        ("Flag for SOC review — multiple behavioural deviations detected simultaneously", False),
        ("Prompt step-up MFA for the current session", True),
        ("Verify device enrolment status and OS compliance", False),
        ("Check for concurrent active sessions and recent credential changes", False),
    ],
    "Behavioral Anomaly": [
        ("Flag for SOC review — broad statistical deviation from user baseline", False),
        ("Collect additional telemetry (endpoint logs, network flow, email activity)", False),
        ("Do not remediate automatically until root cause confirmed via human investigation", False),
    ],
    "Unknown": [
        ("Escalate to SOC for manual investigation", False),
        ("Collect additional telemetry (endpoint logs, network flow)", False),
        ("Do not remediate automatically until root cause confirmed", False),
    ],
}

# Compliance obligations raised by threat category.
COMPLIANCE_FLAGS: dict[str, list[str]] = {
    "Data Exfiltration": [
        "UK GDPR Art.33||potential personal data breach: notification to ICO required within 72 hours",
        "UK GDPR Art.32||technical and organisational measures to ensure data confidentiality must be reviewed",
        "PCI-DSS v4.0 Req.12.10||incident response procedure must be activated",
        "PCI-DSS v4.0 Req.9.4||data access controls and audit trail must be preserved",
        "NIS Regulations 2018, Reg.10||operator must apply appropriate and proportionate security measures",
    ],
    "Account Takeover": [
        "PCI-DSS v4.0 Req.12.10||incident response procedure must be activated",
        "PCI-DSS v4.0 Req.8.2||all user IDs and authentication must be managed to prevent unauthorised access",
        "UK GDPR Art.32||appropriate technical measures to ensure authorised access to personal data only",
        "NCSC Cyber Essentials||Req.4: user access control; compromised account must be reviewed immediately",
    ],
    "Privilege Escalation": [
        "PCI-DSS v4.0 Req.7.1||access control policy and least-privilege principle review required",
        "PCI-DSS v4.0 Req.12.10||incident response procedure must be activated",
        "ISO 27001:2022 A.9.2||user access provisioning must be reviewed and revoked where appropriate",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security of network and information systems",
    ],
    "Insider Threat": [
        "UK GDPR Art.32||technical measures for data protection and access monitoring must be reviewed",
        "PCI-DSS v4.0 Req.12.10||incident response procedure must be activated",
        "PCI-DSS v4.0 Req.12.3||security policies and employee acceptable-use procedures review required",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security measures must be applied",
    ],
    "Brute Force": [
        "PCI-DSS v4.0 Req.8.3||account lockout and authentication controls must be enforced",
        "NCSC Cyber Essentials||Req.4: user access control; accounts must lock after repeated failed attempts",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security measures against authentication attacks",
    ],
    "Credential Stuffing": [
        "PCI-DSS v4.0 Req.8.2||user authentication policies and credential management must be enforced",
        "NCSC Cyber Essentials||Req.4: user access control; accounts must be protected against credential-based attacks",
        "UK GDPR Art.32||technical measures to prevent unauthorised access using compromised credentials",
    ],
    "Geographic Anomaly": [
        "UK GDPR Art.32||technical measures to ensure ongoing confidentiality and integrity of processing systems",
        "NIS Regulations 2018, Reg.10||operator must take appropriate and proportionate technical security measures; unexpected geography may indicate a security incident",
        "NCSC Cyber Essentials||Req.1: boundary firewalls and internet gateways should restrict access to authorised locations",
    ],
    "Unmanaged Device": [
        "NCSC Cyber Essentials||Req.3: all devices must run supported, updated software and be securely configured before accessing corporate resources",
        "UK GDPR Art.32||data accessed from unmanaged devices may breach technical security requirements",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security of network and information systems; unmanaged endpoints represent security risk",
        "FCA SYSC 13.7||operational risk controls must include device security and endpoint management",
    ],
    "Unauthorized Application Access": [
        "UK GDPR Art.5(1)(b)||purpose limitation: access to applications beyond authorised business purpose is prohibited",
        "UK GDPR Art.32||appropriate technical measures to ensure only authorised access to systems processing personal data",
        "NCSC Cyber Essentials||Req.4: user access control; users must only access applications for which they are authorised",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security measures against unauthorised application access",
    ],
    "Browser Anomaly": [
        "NCSC Cyber Essentials||Req.4 (malware protection): browser security configuration must be maintained; unknown browsers indicate potential policy bypass",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate measures against attacks exploiting unknown or misconfigured browser software",
        "UK GDPR Art.32||technical measures to ensure integrity of processing; unrecognised browser agent indicates potential session compromise",
    ],
    "OS Anomaly": [
        "NCSC Cyber Essentials||Req.3: patch management; access from unrecognised or unsupported OS violates the supported software requirement",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate security measures; unknown OS represents an uncontrolled access vector",
        "UK GDPR Art.32||technical measures to ensure integrity of systems; unrecognised OS indicates potential endpoint compromise",
    ],
    "Multi-Factor Incident": [
        "ISO 27001:2022 A.16.1||information security incident management: multiple simultaneous deviations must be treated as a compound incident requiring coordinated response",
        "NIS Regulations 2018, Reg.10||operator must take appropriate and proportionate security measures; compound events carry elevated breach risk",
        "UK GDPR Art.32||technical and organisational measures to ensure security; multiple concurrent anomalies require immediate assessment",
    ],
    "Behavioral Anomaly": [
        "UK GDPR Art.32||requirement for ongoing monitoring of effectiveness of technical and organisational measures",
        "NIS Regulations 2018, Reg.10||continuous monitoring is required; broad statistical deviation from baseline indicates potential security event",
        "ISO 27001:2022 A.12.4||logging and monitoring: anomalous behaviour must be logged, retained, and reviewed",
    ],
    "Anomalous Access": [
        "UK GDPR Art.32||appropriate technical measures to ensure only authorised processing of personal data",
        "NCSC Cyber Essentials||Req.4: user access control; access outside expected patterns must be reviewed",
        "NIS Regulations 2018, Reg.10||appropriate and proportionate measures required; anomalous access warrants investigation as potential incident",
    ],
}

# Compliance obligations raised by severity level (generic, not threat-specific).
SEVERITY_FLAGS: dict[str, list[str]] = {
    "CRITICAL": [
        "ISO 27001 A.16||information security incident management procedure must be followed",
    ],
    "HIGH": [
        "ISO 27001 A.16||incident must be logged and reviewed within 24h",
    ],
}


def get_actions(
    root_cause: str,
    severity: str,
) -> tuple[list[RemediationAction], list[str]]:
    """Return recommended actions and compliance flags for *root_cause* / *severity*.

    Unknown root cause categories fall back to the "Unknown" rule set.

    Args:
        root_cause: Threat category (e.g. ``"Account Takeover"``).
        severity:   ``"CRITICAL"`` | ``"HIGH"`` | ``"MEDIUM"`` | ``"LOW"``.

    Returns:
        actions:          List of :class:`RemediationAction` (rationale empty).
        compliance_flags: Combined list of applicable compliance obligations.
    """
    rule_key = root_cause if root_cause in RULES else "Unknown"
    raw = RULES[rule_key]

    actions = [
        RemediationAction(priority=i + 1, action=action, auto_actionable=auto) for i, (action, auto) in enumerate(raw)
    ]

    flags: list[str] = []
    flags.extend(COMPLIANCE_FLAGS.get(root_cause, []))
    flags.extend(SEVERITY_FLAGS.get(severity, []))

    return actions, flags

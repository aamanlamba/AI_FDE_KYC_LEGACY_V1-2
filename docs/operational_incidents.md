# Synthetic Operational Incident History

These incidents are fictional but representative of issues reported against the inherited service.

| Ref | Severity | Symptom | Operational impact | Current status |
|---|---|---|---|---|
| INC-101 | High | Rotated document produced incomplete extraction | Applicant referred to manual review | Reproducible in synthetic case CASE-003 |
| INC-117 | Medium | OCR corruption changed applicant surname characters | Duplicate identity investigation triggered | Reproducible in CASE-005 |
| INC-124 | High | Expired document required consistent rejection | Compliance escalation | Reproducible in CASE-004 |
| INC-139 | High | Suspicious text alteration was not visible in ordinary parsed fields | Manual fraud investigation required | Reproducible in CASE-006 |
| INC-151 | Medium | Similar documents produced different completeness scores | Analyst confusion and rework | Under investigation |
| INC-163 | Medium | Parser required code change after upstream format variation | Release delay | Known recurring issue |

## Investigation expectation
Participants should reproduce the documented scenarios from the repository and determine which failures originate in ingestion, OCR assumptions, parsing, validation, identity consistency, decision logic, or operational controls.

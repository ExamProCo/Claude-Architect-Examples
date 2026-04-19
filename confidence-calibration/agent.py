"""
Contract clause extraction agent with field-level confidence scoring.

Each field gets an independent confidence score. Items below the threshold
are routed to the human review queue instead of auto-approved.
"""

import json
import os
import anthropic
from dataclasses import dataclass
from typing import Optional

MODEL = "claude-haiku-4-5-20251001"

# Thresholds for routing decisions
AUTO_APPROVE_THRESHOLD = 0.80
HUMAN_REVIEW_THRESHOLD = 0.55  # below this → mandatory review

# The 41 CUAD clause types, trimmed to short names for prompting
CLAUSE_TYPES = [
    "Document Name",
    "Parties",
    "Agreement Date",
    "Effective Date",
    "Expiration Date",
    "Renewal Term",
    "Governing Law",
    "Termination For Convenience",
    "Non-Compete",
    "Non-Solicitation Of Customers",
    "Non-Solicitation Of Employees",
    "Exclusivity",
    "No-Assign",
    "Change Of Control",
    "License Grant",
    "IP Ownership Assignment",
    "Limitation Of Liability",
    "Cap On Liability",
    "Liquidated Damages",
    "Warranty Duration",
    "Audit Rights",
    "Most Favored Nation",
    "Minimum Commitment",
    "Revenue/Profit Sharing",
    "Price Restrictions",
    "Covenant Not To Sue",
    "Post-Termination Services",
    "Indemnification",
    "Insurance",
    "Confidentiality",
]


@dataclass
class FieldExtraction:
    field_name: str
    extracted_value: Optional[str]
    confidence: float  # 0.0–1.0 self-reported by Claude
    reasoning: str
    routing: str  # "auto_approve" | "quick_review" | "full_review"


@dataclass
class ContractAnalysis:
    document_id: str
    document_title: str
    contract_type: str
    extractions: list[FieldExtraction]

    def flagged_fields(self) -> list[FieldExtraction]:
        return [e for e in self.extractions if e.routing != "auto_approve"]

    def auto_approved_fields(self) -> list[FieldExtraction]:
        return [e for e in self.extractions if e.routing == "auto_approve"]

    def avg_confidence(self) -> float:
        if not self.extractions:
            return 0.0
        return sum(e.confidence for e in self.extractions) / len(self.extractions)


def _route(confidence: float) -> str:
    if confidence >= AUTO_APPROVE_THRESHOLD:
        return "auto_approve"
    if confidence >= HUMAN_REVIEW_THRESHOLD:
        return "quick_review"
    return "full_review"


def extract_contract_fields(
    contract_text: str,
    document_id: str,
    document_title: str,
    fields: list[str] = None,
) -> ContractAnalysis:
    """
    Run Claude on a contract excerpt and return per-field extractions with confidence.
    Uses the first 4000 chars to keep token costs low for the demo.
    """
    client = anthropic.Anthropic()
    target_fields = fields or CLAUSE_TYPES
    excerpt = contract_text[:4000]

    prompt = f"""You are a legal contract analyst at a law firm.
Extract the following fields from this contract excerpt. For each field:
- extracted_value: the relevant text span, or null if absent
- confidence: your confidence that the extraction is correct (0.0–1.0)
- reasoning: one short sentence explaining your confidence

Be honest about uncertainty — low confidence is better than false confidence.

CONTRACT EXCERPT:
{excerpt}

FIELDS TO EXTRACT:
{json.dumps(target_fields)}

Respond with valid JSON only:
{{
  "contract_type": "<type of contract>",
  "fields": [
    {{
      "field_name": "<field>",
      "extracted_value": "<value or null>",
      "confidence": <0.0–1.0>,
      "reasoning": "<one sentence>"
    }}
  ]
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text
    start = raw.find("{")
    end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])

    extractions = []
    for fd in data.get("fields", []):
        confidence = max(0.0, min(1.0, float(fd.get("confidence", 0.5))))
        extractions.append(
            FieldExtraction(
                field_name=fd.get("field_name", ""),
                extracted_value=fd.get("extracted_value") or None,
                confidence=confidence,
                reasoning=fd.get("reasoning", ""),
                routing=_route(confidence),
            )
        )

    return ContractAnalysis(
        document_id=document_id,
        document_title=document_title,
        contract_type=data.get("contract_type", "Unknown"),
        extractions=extractions,
    )

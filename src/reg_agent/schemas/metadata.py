# src/reg_agent/schemas/metadata.py
from typing import List

from pydantic import BaseModel, Field


class RegulationDocumentMetadata(BaseModel):
    """
    Structured metadata extracted from regulatory documents like Consent Orders or Letters.
    Designed for flexibility in the MVP stage.
    All fields are required. Return 'N/A' for missing string fields and [] for missing list fields.
    """

    document_type: str = Field(
        description="Inferred type of document (e.g., 'Consent Order', 'Supervisory Letter', 'Examination Report'). Return 'N/A' if not found.",
    )
    issuing_agency: str = Field(
        description="Name of the federal agency issuing the document (e.g., OCC, FRB, CFPB, FDIC). Return 'N/A' if not found.",
    )
    subject_institution: str = Field(
        description="Name of the bank or financial institution subject to the document. Return 'N/A' if not found.",
    )
    document_identifier: str = Field(
        description="Official identifier or number for the document, if available (e.g., Order number). Return 'N/A' if not found.",
    )
    key_topics: List[str] = Field(
        default_factory=list,
        description="List of key topics, regulations, or areas of concern mentioned (e.g., BSA/AML, IT Security, Fair Lending, UDAAP). Extract the most relevant terms. Return [] if none found.",
    )
    summary: str = Field(
        ...,
        description="A concise summary of the document's purpose and main points, capturing the essence of the regulatory action or communication.",
    )
    action_items: List[str] = Field(
        default_factory=list,
        description="List of strings, where each string is a specific, discrete action or remediation step required by the institution, if explicitly mentioned. Return [] if none found.",
    )
    # Future: Add fields for related documents, severity rating, etc.

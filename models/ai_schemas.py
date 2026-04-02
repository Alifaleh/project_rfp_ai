try:
    from google.genai import types
except ImportError:
    types = None

def get_interviewer_schema():
    if not types:
        return None
        
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "is_gathering_complete": types.Schema(
                type=types.Type.BOOLEAN,
                description="REQUIRED: Set to true ONLY when you have analyzed the gap and gathered ALL necessary requirements to write a detailed RFP. If you need more info to be professional, set false."
            ),
            "analysis_meta": types.Schema(
                type=types.Type.OBJECT,
                required=["status", "completeness_score"],
                properties={
                    "status": types.Schema(type=types.Type.STRING),
                    "completeness_score": types.Schema(
                        type=types.Type.NUMBER,
                        description="REQUIRED: Percentage (0-100) of completion. Be realistic."
                    ),
                }
            ),
            "research_notes": types.Schema(
                type=types.Type.STRING,
                description="Internal notes on what is missing or analyzed."
            ),
            "form_fields": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["field_key", "label", "component_type"],
                    properties={
                        "field_key": types.Schema(type=types.Type.STRING),
                        "label": types.Schema(type=types.Type.STRING),
                        "component_type": types.Schema(
                            type=types.Type.STRING, 
                            enum=["text_input", "number_input", "textarea", "select", "boolean", "multiselect", "radio"]
                        ),
                        "data_type_validation": types.Schema(type=types.Type.STRING, enum=["string", "integer", "float", "email"]),
                        "options": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
                        "description_tooltip": types.Schema(type=types.Type.STRING),
                        "question_rationale": types.Schema(
                            type=types.Type.STRING,
                            description="A detailed explanation of WHY the AI is asking this question, what it means for the project, and clarification if the question is complex."
                        ),
                        "suggested_answers": types.Schema(
                            type=types.Type.ARRAY, 
                            items=types.Schema(type=types.Type.STRING),
                            description="List of AI-suggested answers for the user to pick from."
                        ),
                        "depends_on": types.Schema(
                            type=types.Type.OBJECT,
                            description="Conditional visibility logic: show this field ONLY IF the target field has the specified value.",
                            properties={
                                "field_key": types.Schema(type=types.Type.STRING, description="The key of the parent field"),
                                "value": types.Schema(type=types.Type.STRING, description="The value that triggers visibility"),
                            },
                             required=["field_key", "value"] 
                        ),
                        "specify_triggers": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                            description="List of options (from 'options' or 'suggested_answers') that require specific user text input (e.g. 'Other')."
                        ),
                    }
                )
            )
        },
        required=["is_gathering_complete", "form_fields", "analysis_meta"]
    )

def get_toc_structure_schema():
    """
    Schema for the Table of Contents Architect.
    Simple recursive structure for Sections -> Subsections.
    """
    if not types:
        return None
        
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "document_title": types.Schema(type=types.Type.STRING),
            "table_of_contents": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["title", "subsections"],
                    properties={
                        "title": types.Schema(type=types.Type.STRING, description="Main Section Title (e.g. '1. Introduction')"),
                        "description_intent": types.Schema(type=types.Type.STRING, description="Brief instruction on what this section should contain."),
                        "subsections": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(
                                type=types.Type.OBJECT,
                                properties={
                                    "title": types.Schema(type=types.Type.STRING, description="Subsection Title (e.g. '1.1 Purpose')"),
                                    "description_intent": types.Schema(type=types.Type.STRING, description="Specific content instruction.")
                                },
                                required=["title"]
                            )
                        )
                    }
                )
            )
        },
        required=["document_title", "table_of_contents"]
    )

def get_section_content_schema():
    """
    Schema for the Section Writer.
    Returns markdown content + list of diagrams.
    """
    if not types:
        return None
        
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "content_html": types.Schema(
                type=types.Type.STRING, 
                description="The full content of the section in semantic HTML5 format (h3, p, ul, li). Do NOT use h1 or h2. Do NOT use markdown. Do NOT use <html>/<body> tags."
            ),
            "diagrams": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING, description="Title of the diagram"),
                        "diagram_type": types.Schema(type=types.Type.STRING, description="Either 'mermaid' for flowcharts/architecture/sequence/data-flow diagrams (rendered as code), or 'illustration' for physical/engineering drawings that need a generated image."),
                        "mermaid_code": types.Schema(type=types.Type.STRING, description="Valid Mermaid.js diagram code. REQUIRED when diagram_type is 'mermaid'. Must be empty string when diagram_type is 'illustration'."),
                        "description": types.Schema(type=types.Type.STRING, description="For 'illustration' type: exhaustive visual specification for image generation. For 'mermaid' type: brief plain-text summary of what the diagram shows.")
                    },
                    required=["title", "diagram_type", "mermaid_code", "description"]
                ),
                description="List of diagrams ONLY if this section genuinely needs a visual. Return empty array [] for text-only sections."
            )
        },
        required=["content_html"]
    )

def get_domain_identification_schema():
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'suggested_domain_name': types.Schema(
                type=types.Type.STRING,
                description='The name of the domain best matching the project.',
                nullable=False
            ),
            'refined_description': types.Schema(
                type=types.Type.STRING,
                description='A refined, professional version of the project description, strictly adhering to provided facts.',
                nullable=False
            )
        },
        required=['suggested_domain_name', 'refined_description']
    )

def get_kb_analysis_schema():
    """Legacy schema kept for backward compatibility."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'suggested_domain_name': types.Schema(
                type=types.Type.STRING,
                description='The best fitting Domain for this document (e.g., "Healthcare", "Logistics", "Software Development").',
                nullable=False
            ),
            'extracted_practices': types.Schema(
                type=types.Type.STRING,
                description='A generalized, structured guide of Best Practices, Standard RFP Sections, and Compliance Standards derived from the document. Must not contain specific client names.',
                nullable=False
            )
        },
        required=['suggested_domain_name', 'extracted_practices']
    )


def get_kb_structure_extraction_schema():
    """Step 1: Extract section structure + summary from KB document."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'suggested_domain_name': types.Schema(
                type=types.Type.STRING,
                description='The best fitting vendor expertise domain for this document '
                            '(e.g., "Healthcare", "Logistics", "Software Development").',
            ),
            'summary': types.Schema(
                type=types.Type.STRING,
                description='A concise 2-4 sentence summary of what this document covers, '
                            'including domain expertise areas, key focus areas, and compliance standards.',
            ),
            'sections': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=['title', 'section_type'],
                    properties={
                        'title': types.Schema(
                            type=types.Type.STRING,
                            description='Section title as found or inferred from the document.',
                        ),
                        'section_type': types.Schema(
                            type=types.Type.STRING,
                            enum=['introduction', 'functional', 'technical', 'compliance',
                                  'security', 'timeline', 'budget', 'evaluation',
                                  'support', 'appendix'],
                            description='Category of this section.',
                        ),
                    }
                ),
            ),
        },
        required=['suggested_domain_name', 'summary', 'sections']
    )


def get_kb_content_extraction_schema():
    """Step 2: Extract content descriptions and best practices per section."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'sections': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=['title', 'description'],
                    properties={
                        'title': types.Schema(
                            type=types.Type.STRING,
                            description='Section title (must match the titles from Step 1).',
                        ),
                        'description': types.Schema(
                            type=types.Type.STRING,
                            description='Generalized best practices, standard content patterns, and guidance '
                                        'for writing this section. Do NOT include client-specific details or names.',
                        ),
                        'key_topics': types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                            description='List of key topics and subjects covered in this section.',
                        ),
                    }
                ),
            ),
        },
        required=['sections']
    )


def get_kb_project_generalization_schema():
    """Schema for generalizing sections from a completed project into KB content."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'summary': types.Schema(
                type=types.Type.STRING,
                description='A concise 2-4 sentence summary of what this knowledge base covers.',
            ),
            'sections': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=['title', 'section_type', 'description'],
                    properties={
                        'title': types.Schema(
                            type=types.Type.STRING,
                            description='Section title (match the original section title).',
                        ),
                        'section_type': types.Schema(
                            type=types.Type.STRING,
                            enum=['introduction', 'functional', 'technical', 'compliance',
                                  'security', 'timeline', 'budget', 'evaluation',
                                  'support', 'appendix'],
                            description='Category of this section.',
                        ),
                        'description': types.Schema(
                            type=types.Type.STRING,
                            description='Generalized best practices extracted from this section content. '
                                        'Remove all client-specific details, names, and dates. '
                                        'Focus on reusable patterns and standards.',
                        ),
                        'key_topics': types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                            description='List of key topics covered in this section.',
                        ),
                    }
                ),
            ),
        },
        required=['summary', 'sections']
    )


def get_kb_selection_schema():
    """Schema for AI-based KB selection/ranking."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            'selected_kb_ids': types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.INTEGER),
                description='List of Knowledge Base IDs most relevant to this project, '
                            'ordered by relevance. Select 1-3 KBs maximum.',
            ),
            'reasoning': types.Schema(
                type=types.Type.STRING,
                description='Brief explanation of why these KBs were selected and how they relate to the project.',
            ),
        },
        required=['selected_kb_ids', 'reasoning']
    )

def get_document_extraction_schema():
    """Schema for extracting structured data from an uploaded RFP document."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "suggested_name": types.Schema(
                type=types.Type.STRING,
                description="A concise project name extracted or derived from the document."
            ),
            "refined_description": types.Schema(
                type=types.Type.STRING,
                description="A professional 2-4 sentence summary of the RFP's purpose and scope. Preserve ALL specific facts, dates, numbers, and constraints."
            ),
            "suggested_domain_name": types.Schema(
                type=types.Type.STRING,
                description="The vendor expertise domain best matching this RFP (e.g. 'Software Development', not the client's industry)."
            ),
            "field_extractions": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["field_key", "extracted_value"],
                    properties={
                        "field_key": types.Schema(
                            type=types.Type.STRING,
                            description="The exact field_key from the provided field list."
                        ),
                        "extracted_value": types.Schema(
                            type=types.Type.STRING,
                            description="The value extracted or inferred from the document for this field."
                        ),
                    }
                ),
                description="Extracted values for each field where information was found in the document. Only include fields with meaningful data."
            ),
        },
        required=["suggested_name", "refined_description", "suggested_domain_name", "field_extractions"]
    )

def get_auto_fill_schema():
    """Schema for auto-filling form inputs from source text with confidence levels."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "auto_filled_fields": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["field_key", "answer", "confidence"],
                    properties={
                        "field_key": types.Schema(
                            type=types.Type.STRING,
                            description="The exact field_key from the question list."
                        ),
                        "answer": types.Schema(
                            type=types.Type.STRING,
                            description="The answer text. For select/radio fields: must be the exact option value. For multiselect: comma-separated option values. For boolean: 'yes' or 'no'."
                        ),
                        "confidence": types.Schema(
                            type=types.Type.STRING,
                            enum=["high", "medium", "low"],
                            description="high: explicitly stated in source (auto-fill). medium: reasonably inferred (suggest). low: insufficient info (omit)."
                        ),
                        "source_excerpt": types.Schema(
                            type=types.Type.STRING,
                            description="Brief 1-2 sentence quote from the source text supporting this answer."
                        ),
                    }
                ),
                description="Answers extracted from source text. Only include high and medium confidence entries. Omit low-confidence fields entirely."
            )
        },
        required=["auto_filled_fields"]
    )
def get_proposal_extraction_schema():
    """Schema for extracting vendor info from uploaded proposal."""
    if not types:
        return None
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "company_name": types.Schema(
                type=types.Type.STRING,
                description="Vendor company name extracted from proposal"
            ),
            "contact_person": types.Schema(
                type=types.Type.STRING,
                description="Contact person name"
            ),
            "email": types.Schema(
                type=types.Type.STRING,
                description="Email address"
            ),
            "phone": types.Schema(
                type=types.Type.STRING,
                description="Phone number (optional)"
            ),
            "website": types.Schema(
                type=types.Type.STRING,
                description="Company website (optional)"
            ),
        },
        required=["company_name", "contact_person", "email"]
    )

def get_proposal_analysis_schema():
    """
    Schema for AI Proposal Analysis.
    Comprehensive evaluation of vendor proposals against RFP requirements.
    """
    if not types:
        return None
        
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "coverage_score": types.Schema(
                type=types.Type.INTEGER,
                description="Percentage (0-100) of RFP requirements addressed by the proposal."
            ),
            "overall_rating": types.Schema(
                type=types.Type.STRING,
                enum=["Excellent", "Good", "Fair", "Poor"],
                description="Overall quality assessment of the proposal."
            ),
            "summary": types.Schema(
                type=types.Type.STRING,
                description="Executive summary of the proposal analysis (2-3 sentences)."
            ),
            "strengths": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING, description="Strength title"),
                        "description": types.Schema(type=types.Type.STRING, description="Detailed explanation of why this is a strength"),
                        "impact": types.Schema(type=types.Type.STRING, enum=["High", "Medium", "Low"])
                    },
                    required=["title", "description"]
                ),
                description="List of proposal strengths"
            ),
            "weaknesses": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING, description="Weakness title"),
                        "description": types.Schema(type=types.Type.STRING, description="Detailed explanation of the weakness or gap"),
                        "severity": types.Schema(type=types.Type.STRING, enum=["Critical", "Major", "Minor"])
                    },
                    required=["title", "description"]
                ),
                description="List of proposal weaknesses or gaps"
            ),
            "insights": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "category": types.Schema(type=types.Type.STRING, enum=["Technical", "Commercial", "Risk", "Compliance", "Experience", "Timeline"]),
                        "finding": types.Schema(type=types.Type.STRING, description="Key insight or observation")
                    },
                    required=["category", "finding"]
                ),
                description="Key insights categorized by area"
            ),
            "requirements_coverage": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "requirement": types.Schema(type=types.Type.STRING, description="RFP requirement being assessed"),
                        "status": types.Schema(type=types.Type.STRING, enum=["Fully Addressed", "Partially Addressed", "Not Addressed"]),
                        "notes": types.Schema(type=types.Type.STRING, description="Brief notes on how it was addressed or what's missing")
                    },
                    required=["requirement", "status"]
                ),
                description="How each major RFP requirement is addressed"
            ),
            "risk_assessment": types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "level": types.Schema(type=types.Type.STRING, enum=["Low", "Medium", "High"]),
                    "factors": types.Schema(
                        type=types.Type.ARRAY, 
                        items=types.Schema(type=types.Type.STRING),
                        description="List of risk factors identified"
                    )
                },
                required=["level", "factors"]
            ),
            "recommendation": types.Schema(
                type=types.Type.STRING,
                enum=["Shortlist", "Review", "Reject"],
                description="AI recommendation for this proposal"
            ),
            "recommendation_reason": types.Schema(
                type=types.Type.STRING,
                description="Explanation for the recommendation"
            ),
            "questions_for_vendor": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Suggested clarification questions to ask the vendor"
            )
        },
        required=["coverage_score", "overall_rating", "summary", "strengths", "weaknesses", "recommendation", "recommendation_reason"]
    )

def get_eval_criteria_schema():
    """
    Schema for generating evaluation criteria from interview answers.
    Returns structured criteria with weights summing to ~100.
    """
    if not types:
        return None

    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "criteria": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["name", "category", "weight", "is_must_have", "scoring_guidance"],
                    properties={
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="Short name for the criterion (e.g., 'Cloud Infrastructure Experience')"
                        ),
                        "description": types.Schema(
                            type=types.Type.STRING,
                            description="Detailed description of what this criterion evaluates"
                        ),
                        "category": types.Schema(
                            type=types.Type.STRING,
                            enum=["technical", "commercial", "experience", "compliance", "timeline", "methodology", "support", "innovation", "other"],
                            description="Category this criterion belongs to"
                        ),
                        "weight": types.Schema(
                            type=types.Type.INTEGER,
                            description="Relative importance weight (1-100). All weights across criteria should sum to approximately 100."
                        ),
                        "is_must_have": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="If true, failing this criterion means automatic rejection regardless of other scores."
                        ),
                        "scoring_guidance": types.Schema(
                            type=types.Type.STRING,
                            description="Guidance for scoring: what constitutes a high score (80-100), medium (50-79), and low (0-49) for this criterion."
                        ),
                    }
                ),
                description="List of evaluation criteria. Weights should sum to approximately 100."
            )
        },
        required=["criteria"]
    )

def get_criteria_proposal_analysis_schema():
    """
    Enhanced proposal analysis schema that includes per-criterion scoring.
    Used when project has finalized evaluation criteria.
    """
    if not types:
        return None

    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "coverage_score": types.Schema(
                type=types.Type.INTEGER,
                description="Percentage (0-100) of RFP requirements addressed by the proposal."
            ),
            "overall_rating": types.Schema(
                type=types.Type.STRING,
                enum=["Excellent", "Good", "Fair", "Poor"],
                description="Overall quality assessment of the proposal."
            ),
            "summary": types.Schema(
                type=types.Type.STRING,
                description="Executive summary of the proposal analysis (2-3 sentences)."
            ),
            "criteria_scores": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    required=["criterion_name", "score", "justification"],
                    properties={
                        "criterion_name": types.Schema(
                            type=types.Type.STRING,
                            description="Exact name of the evaluation criterion being scored."
                        ),
                        "score": types.Schema(
                            type=types.Type.INTEGER,
                            description="Score from 0-100 for this criterion."
                        ),
                        "justification": types.Schema(
                            type=types.Type.STRING,
                            description="Brief justification for the assigned score."
                        ),
                        "met": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="For must-have criteria: whether the minimum requirement is met."
                        ),
                    }
                ),
                description="Per-criterion evaluation scores."
            ),
            "weighted_total_score": types.Schema(
                type=types.Type.INTEGER,
                description="Weighted total score (0-100), calculated from individual criterion scores and their weights."
            ),
            "must_have_failures": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="List of must-have criterion names that were NOT met. Empty if all must-haves passed."
            ),
            "strengths": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING),
                        "description": types.Schema(type=types.Type.STRING),
                        "impact": types.Schema(type=types.Type.STRING, enum=["High", "Medium", "Low"])
                    },
                    required=["title", "description"]
                )
            ),
            "weaknesses": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING),
                        "description": types.Schema(type=types.Type.STRING),
                        "severity": types.Schema(type=types.Type.STRING, enum=["Critical", "Major", "Minor"])
                    },
                    required=["title", "description"]
                )
            ),
            "recommendation": types.Schema(
                type=types.Type.STRING,
                enum=["Shortlist", "Review", "Reject"],
                description="AI recommendation for this proposal."
            ),
            "recommendation_reason": types.Schema(
                type=types.Type.STRING,
                description="Explanation for the recommendation."
            ),
            "questions_for_vendor": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Suggested clarification questions to ask the vendor."
            )
        },
        required=["coverage_score", "overall_rating", "summary", "criteria_scores", "weighted_total_score", "must_have_failures", "recommendation", "recommendation_reason"]
    )

def get_scope_assessment_schema():
    """
    Schema for the Scope Assessment AI call.
    Analyzes budget + company size + project complexity to return
    recommended interview round limits.
    """
    if not types:
        return None

    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "complexity_rating": types.Schema(
                type=types.Type.STRING,
                enum=["low", "medium", "high", "very_high"],
                description="Overall project complexity assessment."
            ),
            "reasoning": types.Schema(
                type=types.Type.STRING,
                description="Brief explanation of the complexity assessment and how it maps to round limits."
            ),
            "warn_round": types.Schema(
                type=types.Type.INTEGER,
                description="Round number at which the interviewer should start winding down and only ask critical questions. Typically 8-20 depending on complexity."
            ),
            "max_round": types.Schema(
                type=types.Type.INTEGER,
                description="Round number at which the interviewer must aggressively wrap up. Typically 12-30 depending on complexity."
            ),
        },
        required=["complexity_rating", "reasoning", "warn_round", "max_round"]
    )

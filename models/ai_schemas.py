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

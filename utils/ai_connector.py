import json
import logging
import re
from odoo import http, fields

# Try import Google GenAI (SDK)
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

_logger = logging.getLogger(__name__)

# DEFAULT CONSTANTS (Fallback)
DEFAULT_GEMINI_MODEL = "gemini-3-pro-preview"
DEFAULT_GEMINI_KEY = ""

class RateLimitError(Exception):
    pass

def _call_gemini_api(system_instructions, user_content, env, response_mime_type="text/plain", response_schema=None):
    """
    Helper to call Google Gemini API using the SDK.
    Uses credentials from System Parameters.
    """
    if not genai:
        _logger.error("google-genai library not installed! Run pip install google-genai")
        return None

    # Fetch Config
    api_key = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.gemini_api_key', DEFAULT_GEMINI_KEY)
    model_name = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.gemini_model', DEFAULT_GEMINI_MODEL)
    
    if not api_key:
        _logger.error("Gemini API Key is not configured in Settings!")
        return None

    try:
        client = genai.Client(api_key=api_key)
        
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=user_content),
                ],
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
             thinking_config={
                 "thinking_level": "HIGH", 
             } if "thinking" in model_name else None,
            
            system_instruction=[
                types.Part.from_text(text=system_instructions)
            ],
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=0.4,
            max_output_tokens=8192,
        )

        # Non-streaming call for simplicity in Odoo backend (we wait anyway)
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            config=generate_content_config,
        )
        
        return response.text
        
    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
            _logger.warning(f"Gemini Rate Limit Exceeded: {error_msg}")
            raise RateLimitError("Rate Limit Exceeded")
            
        _logger.error(f"Gemini SDK Error: {error_msg}")
        return None

def generate_json_response(system_prompt_ignored, user_context_str, env=None, is_retry=False):
    """
    Live AI Connector for Interviewer (JSON).
    Fetches the 'interviewer_main' prompt from DB.
    """
    if not env:
        env = http.request.env
        
    prompt_record = env['rfp.prompt'].sudo().search([('code', '=', 'interviewer_main')], limit=1)
    
    if not prompt_record:
        _logger.error("Interviewer Prompt (interviewer_main) not found!")
        return json.dumps({"error": "Prompt configuration missing"})
        
    system_prompt = prompt_record.template_text
    
    from ..models.ai_schemas import get_interviewer_schema
    
    # Call Gemini
    _logger.info("Calling Gemini for Interviewer (SDK)...")
    
    try:
        response_text = _call_gemini_api(
            system_prompt, 
            user_context_str, 
            env, 
            response_mime_type="application/json",
            response_schema=get_interviewer_schema()
        )
    except RateLimitError:
        return json.dumps({
            "analysis_meta": {"status": "rate_limit", "completeness_score": 0},
            "research_notes": "High Traffic (Rate Limit). Please wait 30 seconds and retry.",
            "form_fields": []
        })

    if not response_text:
        return json.dumps({
            "analysis_meta": {"status": "error", "completeness_score": 0},
            "research_notes": "AI Service Unavailable (Check API Key/Quota).",
            "form_fields": []
        })

    # Sanitize JSON (remove markdown fences if present) in case usage didn't respect mimetype perfectly
    clean_json = re.sub(r"```json|```", "", response_text).strip()
    
    try:
        # Validate format
        json.loads(clean_json)
        return clean_json
    except json.JSONDecodeError as e:
        _logger.warning(f"Invalid JSON from AI (Attempt 1): {str(e)}")
        
        # Retry once if this wasn't already a retry
        if not is_retry:
            _logger.info("Retrying AI request due to invalid JSON...")
            return generate_json_response(system_prompt_ignored, user_context_str, env=env, is_retry=True)
            
        _logger.error(f"Invalid JSON from AI (Final Attempt): {response_text}")
        json_error_msg = json.dumps({"error": "Invalid JSON response"}) # fallback
        return json.dumps({
             "analysis_meta": {"status": "error", "completeness_score": 0},
             "research_notes": f"AI Parsing Error: {str(e)}. Please retry.",
             "form_fields": []
        })

def generate_text_response(section_name, context_str, env=None):
    """
    Live AI Connector for Writer (Markdown).
    Fetches 'writer_section_template' from DB.
    """
    if not env:
        env = http.request.env
        
    prompt_record = env['rfp.prompt'].sudo().search([('code', '=', 'writer_section_template')], limit=1)
    
    if not prompt_record:
        return f"Error: Writer prompt 'writer_section_template' not found."
        
    final_system_instruction = prompt_record.template_text.replace("{section_name}", section_name)
    user_message = f"Project Context:\n{context_str}\n\nPlease write the {section_name} section now."
    
    _logger.info(f"Calling Gemini for Writer ({section_name})...")
    
    try:
        response_text = _call_gemini_api(final_system_instruction, user_message, env, response_mime_type="text/plain")
    except RateLimitError:
        return "**Error: Rate Limit Exceeded. Please retry generation in ~30 seconds.**"
    
    if not response_text:
        return "**Error generating content. AI Service unavailable.**"
        
    return response_text

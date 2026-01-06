import json
import logging
import re

# Try import Google GenAI (SDK)
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

_logger = logging.getLogger(__name__)

# DEFAULT CONSTANTS (Fallback)
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
DEFAULT_GEMINI_KEY = ""

class RateLimitError(Exception):
    pass

def _call_gemini_api(system_instructions, user_content, env, response_mime_type="text/plain", response_schema=None, model_name=None, tools=None, attachments=None):
    """
    Helper to call Google Gemini API using the SDK.
    Uses credentials from System Parameters, but Model from arguments.
    """
    if not genai:
        _logger.error("google-genai library not installed! Run pip install google-genai")
        return None

    # Fetch Config
    api_key = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.gemini_api_key', DEFAULT_GEMINI_KEY)
    
    # Apply default if not provided
    if not model_name:
        model_name = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.gemini_model', DEFAULT_GEMINI_MODEL)
    
    if not api_key:
        _logger.error("Gemini API Key is not configured in Settings!")
        return None

    try:
        # Increase timeout to 60 minutes (3600 seconds * 1000 ms)
        # HTTP Options timeout is in milliseconds
        client = genai.Client(api_key=api_key, http_options={'timeout': 3600000})
        
        parts = [types.Part.from_text(text=user_content)]

        if attachments:
            for attach in attachments:
                parts.append(types.Part.from_bytes(data=attach['data'], mime_type=attach['mime_type']))

        contents = [
            types.Content(
                role="user",
                parts=parts,
            ),
        ]
        
        generate_content_config = types.GenerateContentConfig(
             thinking_config={
                 "thinking_level": "HIGH", 
                 "include_thoughts": False
             } if "thinking" in model_name else None,
            
            system_instruction=[
                types.Part.from_text(text=system_instructions)
            ],
            tools=tools,
            response_mime_type=response_mime_type,
            response_schema=response_schema,
            temperature=0.4,
            max_output_tokens=65536,
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
        raise e

def _generate_image_gemini(prompt, env, model_name='imagen-3.0-generate-001'):
    """
    Helper to generate images using Google Imagen 3 via GenAI SDK.
    Returns: Base64 string of the image or None.
    """
    if not genai:
        _logger.error("google-genai library not installed!")
        return None

    api_key = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.gemini_api_key', DEFAULT_GEMINI_KEY)
    if not api_key:
        _logger.error("Gemini API Key is not configured!")
        # We can raise here to be consistent
        raise ValueError("Gemini API Key is not configured")

    client = genai.Client(api_key=api_key)
    
    response = client.models.generate_images(
        model=model_name,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
        )
    )
    
    if response.generated_images:
        # Return the first image as base64 bytes (or string depending on SDK, usually bytes)
        return response.generated_images[0].image.image_bytes
        
    return None

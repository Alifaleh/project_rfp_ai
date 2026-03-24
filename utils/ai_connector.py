import json
import logging
import re
import base64

# Try import Google GenAI (SDK)
try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

# Try import OpenAI SDK
try:
    import openai as openai_lib
except ImportError:
    openai_lib = None

_logger = logging.getLogger(__name__)

# DEFAULT CONSTANTS (Fallback)
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
DEFAULT_GEMINI_KEY = ""
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_KEY = ""

# Google types.Type -> JSON Schema type mapping
_GTYPE_MAP = {
    'STRING': 'string',
    'NUMBER': 'number',
    'INTEGER': 'integer',
    'BOOLEAN': 'boolean',
    'ARRAY': 'array',
    'OBJECT': 'object',
}

class RateLimitError(Exception):
    pass


def _gemini_schema_to_json_schema(schema):
    """
    Convert a Google genai types.Schema object to a standard JSON Schema dict.
    This allows reusing the same schema definitions for OpenAI structured outputs.
    """
    if schema is None:
        return None

    result = {}

    # Get type name
    type_val = schema.type
    if type_val:
        type_str = type_val.name if hasattr(type_val, 'name') else str(type_val)
        # Strip prefix like "Type." if present
        type_str = type_str.replace('Type.', '')
        result['type'] = _GTYPE_MAP.get(type_str, type_str.lower())

    if schema.description:
        result['description'] = schema.description

    if schema.enum:
        result['enum'] = list(schema.enum)

    if hasattr(schema, 'nullable') and schema.nullable:
        # JSON Schema: use nullable or anyOf pattern
        pass  # OpenAI structured outputs handle nullable via required/optional

    # Properties (for objects)
    if schema.properties:
        result['properties'] = {}
        for key, sub_schema in schema.properties.items():
            result['properties'][key] = _gemini_schema_to_json_schema(sub_schema)

    # Required fields
    if schema.required:
        result['required'] = list(schema.required)

    # Items (for arrays)
    if schema.items:
        result['items'] = _gemini_schema_to_json_schema(schema.items)

    # OpenAI structured outputs require additionalProperties: false on objects
    if result.get('type') == 'object' and 'properties' in result:
        result['additionalProperties'] = False
        # OpenAI requires ALL properties in 'required' for strict mode
        if 'required' not in result:
            result['required'] = list(result['properties'].keys())

    return result

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


def _call_openai_api(system_instructions, user_content, env, response_mime_type="text/plain", response_schema=None, model_name=None, tools=None, attachments=None):
    """
    Helper to call OpenAI ChatGPT API using the OpenAI SDK.
    Mirrors the Gemini connector interface for drop-in routing.
    """
    if not openai_lib:
        _logger.error("openai library not installed! Run pip install openai")
        return None

    # Fetch Config
    api_key = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.openai_api_key', DEFAULT_OPENAI_KEY)

    if not model_name:
        model_name = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.openai_model', DEFAULT_OPENAI_MODEL)

    if not api_key:
        _logger.error("OpenAI API Key is not configured in Settings!")
        return None

    try:
        client = openai_lib.OpenAI(api_key=api_key, timeout=3600)

        # Build messages
        messages = [
            {"role": "system", "content": system_instructions},
        ]

        # Build user message content (text + optional attachments)
        if attachments:
            user_parts = [{"type": "text", "text": user_content}]
            for attach in attachments:
                mime = attach.get('mime_type', 'application/octet-stream')
                if mime.startswith('image/'):
                    b64_data = base64.b64encode(attach['data']).decode('utf-8')
                    user_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64_data}"}
                    })
                # For PDFs and other files, encode as base64 in text
                elif mime == 'application/pdf':
                    b64_data = base64.b64encode(attach['data']).decode('utf-8')
                    user_parts.append({
                        "type": "file",
                        "file": {"filename": "document.pdf", "file_data": f"data:{mime};base64,{b64_data}"}
                    })
                else:
                    # Fallback: include as base64 text block
                    b64_data = base64.b64encode(attach['data']).decode('utf-8')
                    user_parts.append({
                        "type": "text",
                        "text": f"[Attached file ({mime})]: {b64_data[:200]}..."
                    })
            messages.append({"role": "user", "content": user_parts})
        else:
            messages.append({"role": "user", "content": user_content})

        # Determine if this is a reasoning model (o-series)
        is_reasoning_model = model_name.startswith(('o1', 'o3', 'o4'))

        # Build kwargs
        kwargs = {
            "model": model_name,
            "messages": messages,
        }

        # Reasoning models don't support temperature or max_tokens in the same way
        if not is_reasoning_model:
            kwargs["temperature"] = 0.4
            kwargs["max_tokens"] = 65536

        # JSON structured output via response_format
        if response_mime_type == "application/json" and response_schema:
            json_schema = _gemini_schema_to_json_schema(response_schema)
            if json_schema:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "ai_response",
                        "strict": True,
                        "schema": json_schema,
                    }
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
        elif response_mime_type == "application/json":
            kwargs["response_format"] = {"type": "json_object"}

        response = client.chat.completions.create(**kwargs)

        if response.choices:
            return response.choices[0].message.content

        return None

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "rate_limit" in error_msg.lower():
            _logger.warning(f"OpenAI Rate Limit Exceeded: {error_msg}")
            raise RateLimitError("Rate Limit Exceeded")

        _logger.error(f"OpenAI SDK Error: {error_msg}")
        raise e


def _generate_image_openai(prompt, env, model_name='dall-e-3'):
    """
    Helper to generate images using OpenAI DALL-E.
    Returns: image bytes or None.
    """
    if not openai_lib:
        _logger.error("openai library not installed!")
        return None

    api_key = env['ir.config_parameter'].sudo().get_param('project_rfp_ai.openai_api_key', DEFAULT_OPENAI_KEY)
    if not api_key:
        raise ValueError("OpenAI API Key is not configured")

    client = openai_lib.OpenAI(api_key=api_key, timeout=3600)

    response = client.images.generate(
        model=model_name,
        prompt=prompt,
        n=1,
        size="1024x1024",
        quality="standard",
        style="natural",  # "natural" produces cleaner diagrams vs "vivid" (default) which over-stylizes
        response_format="b64_json",
    )

    if response.data:
        b64_str = response.data[0].b64_json
        return base64.b64decode(b64_str)

    return None

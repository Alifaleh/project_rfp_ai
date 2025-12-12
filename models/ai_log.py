from odoo import models, fields, api
from datetime import datetime
import time
import json
import logging

_logger = logging.getLogger(__name__)

class RfpAiLog(models.Model):
    _name = 'rfp.ai.log'
    _description = 'AI Request Log'
    _order = 'create_date desc'

    name = fields.Char(string="Request ID", required=True, copy=False, readonly=True, default='New')
    
    # Timing
    request_date = fields.Datetime(string="Request Timestamp", default=fields.Datetime.now, readonly=True)
    response_date = fields.Datetime(string="Response Timestamp", readonly=True)
    duration = fields.Float(string="Duration (s)", readonly=True)

    # Content
    prompt_used = fields.Text(string="System Prompt", readonly=True)
    input_context = fields.Text(string="User Context (Input)", readonly=True)
    request_body = fields.Text(string="Full Request Body", help="Debug: Full payload sent to API", readonly=True)
    
    response_raw = fields.Text(string="Raw Response", readonly=True)
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sending', 'Sending'),
        ('success', 'Success'),
        ('error', 'Error'),
        ('rate_limit', 'Rate Limit')
    ], string="Status", default='draft', readonly=True)
    
    error_message = fields.Text(string="Error Message", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rfp.ai.log') or 'LOG'
        return super().create(vals_list)

    @api.model
    def execute_request(self, system_prompt, user_context, env=None, mode='json', schema=None, tools=None):
        """
        Centralized method to execute AI requests with full logging.
        Args:
            system_prompt (str): The system instruction.
            user_context (str): The user message/context.
            env (Environment): Odoo environment.
            mode (str): 'json' or 'text'.
            schema (dict): Optional JSON schema for validation.
            tools (list): Optional list of tools (e.g. Google Search).
        Returns:
            str: The AI response text (or JSON string).
        """
        from odoo.addons.project_rfp_ai.utils import ai_connector

        if not env:
            env = self.env
        
        print(f"DEBUG: execute_request called. Mode={mode}, Tools={tools}")

        # 1. Create Log Record (Sending)
        log = self.create({
            'prompt_used': system_prompt,
            'input_context': user_context,
            'state': 'sending',
            'request_date': fields.Datetime.now(),
        })
        
        # Commit to ensure log exists even if crash occurs (Odoo atomic transaction might roll this back on crash, 
        # but useful for long running process visibility if running in checked env).
        # In standard Odoo, explicit commit is dangerous, so we rely on standard transaction. 
        # If it crashes hard, we might lose the log. But for handled exceptions, we are fine.

        start_time = time.time()
        response_text = None
        
        try:
            # 2. Call API
            # We need to route to the correct connector method based on mode
            # However, ai_connector methods (generate_json_response) handle their own prompt fetching usually.
            # Refactoring: we passed the RAW prompts here. We should call the low-level _call_gemini_api or 
            # modify the connector helpers to accept raw strings.
            # Looking at ai_connector.py, `_call_gemini_api` is internal but usable.
            # `generate_json_response` and `generate_text_response` fetch prompts inside themselves.
            # To avoid Duplicate Fetching, the caller (project.py) has already fetched the prompt to pass it here?
            # Let's see project.py... Yes, it fetches prompts.
            # So we should call `_call_gemini_api` directly from here to avoid double fetch?
            # OR we keep using the high level helpers but they need refactoring.
            
            # DECISION: To keep it clean, we will call `ai_connector._call_gemini_api` directly 
            # because this Log Model is now the "Manager".
            
            response_mime_type = "application/json" if mode == 'json' else "text/plain"
            
            # Using the internal helper from utils
            # We need to make sure we import it or access it.
            
            response_text = ai_connector._call_gemini_api(
                system_instructions=system_prompt,
                user_content=user_context,
                env=env,
                response_mime_type=response_mime_type,
                response_schema=schema,
                tools=tools
            )
            
            # Calculate duration
            duration = time.time() - start_time
            
            # 3. Handle Result
            if response_text:
                log.write({
                    'response_raw': response_text,
                    'response_date': fields.Datetime.now(),
                    'duration': duration,
                    'state': 'success'
                })
                return response_text
            else:
                 # None usually means error caught inside connector but returned None
                 # We assume connector logged it to console, but we want it here.
                 # Actually `_call_gemini_api` returns None on error or raises RateLimit.
                 log.write({
                    'state': 'error',
                    'error_message': 'Unknown API Error (Returned None)',
                    'duration': duration,
                    'response_date': fields.Datetime.now()
                 })
                 return None

        except ai_connector.RateLimitError:
            duration = time.time() - start_time
            log.write({
                'state': 'rate_limit',
                'error_message': 'Rate Limit Exceeded (429)',
                'duration': duration,
                'response_date': fields.Datetime.now()
            })
            # Re-raise so flow can handle it (e.g. show UI warning)
            raise

        except Exception as e:
            duration = time.time() - start_time
            log.write({
                'state': 'error',
                'error_message': str(e),
                'duration': duration,
                'response_date': fields.Datetime.now()
            })
            raise e

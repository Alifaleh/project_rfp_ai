from odoo import models, fields, api
from odoo.addons.project_rfp_ai.const import AI_STATUS_SENDING, AI_STATUS_SUCCESS, AI_STATUS_ERROR, AI_STATUS_RATE_LIMIT
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
        (AI_STATUS_SENDING, 'Sending'),
        (AI_STATUS_SUCCESS, 'Success'),
        (AI_STATUS_ERROR, 'Error'),
        (AI_STATUS_RATE_LIMIT, 'Rate Limit')
    ], string="Status", default='draft', readonly=True)
    
    error_message = fields.Text(string="Error Message", readonly=True)

    # Links
    prompt_id = fields.Many2one('rfp.prompt', string="Prompt Used", readonly=True)
    ai_model_id = fields.Many2one('rfp.ai.model', string="AI Model", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('rfp.ai.log') or 'LOG'
        return super().create(vals_list)

    @api.model
    def execute_request(self, system_prompt, user_context, env=None, mode='json', schema=None, tools=None, prompt_record=None):
        """
        Centralized method to execute AI requests with full logging.
        Args:
            system_prompt (str): The system instruction.
            user_context (str): The user message/context.
            env (Environment): Odoo environment.
            mode (str): 'json' or 'text'.
            schema (dict): Optional JSON schema for validation.
            tools (list): Optional list of tools (e.g. Google Search).
            prompt_record (recordset): Optional rfp.prompt record.
        Returns:
            str: The AI response text (or JSON string).
        """
        from odoo.addons.project_rfp_ai.utils import ai_connector

        if not env:
            env = self.env

        # 1. Create Log Record (Sending)
        vals = {
            'prompt_used': system_prompt,
            'input_context': user_context,
            'state': AI_STATUS_SENDING,
            'request_date': fields.Datetime.now(),
        }
        
        model_name = None
        if prompt_record:
            vals['prompt_id'] = prompt_record.id
            if prompt_record.ai_model_id:
                vals['ai_model_id'] = prompt_record.ai_model_id.id
                model_name = prompt_record.ai_model_id.technical_name
                
        log = self.create(vals)
        
        start_time = time.time()
        
        try:
            # 2. Call API via pure connector
            response_mime_type = "application/json" if mode == 'json' else "text/plain"
            
            response_text = ai_connector._call_gemini_api(
                system_instructions=system_prompt,
                user_content=user_context,
                env=env,
                response_mime_type=response_mime_type,
                response_schema=schema,
                model_name=model_name,
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
                    'state': AI_STATUS_SUCCESS
                })
                return response_text
            else:
                 log.write({
                    'state': AI_STATUS_ERROR,
                    'error_message': 'Unknown API Error (Returned None)',
                    'duration': duration,
                    'response_date': fields.Datetime.now()
                 })
                 return None

        except ai_connector.RateLimitError:
            duration = time.time() - start_time
            log.write({
                'state': AI_STATUS_RATE_LIMIT,
                'error_message': 'Rate Limit Exceeded (429)',
                'duration': duration,
                'response_date': fields.Datetime.now()
            })
            raise

        except Exception as e:
            duration = time.time() - start_time
            log.write({
                'state': AI_STATUS_ERROR,
                'error_message': str(e),
                'duration': duration,
                'response_date': fields.Datetime.now()
            })
            raise e

from odoo import models, fields

class RfpPrompt(models.Model):
    _name = 'rfp.prompt'
    _description = 'AI Prompts'
    _rec_name = 'code'

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Unique identifier used in code to fetch this prompt")
    template_text = fields.Text(required=True, help="The system prompt content. Can contain placeholders like {context}.")
    description = fields.Text(help="Internal notes about what this prompt does")
    ai_model_id = fields.Many2one('rfp.ai.model', string="AI Model", required=False, help="The specific AI model to use for this prompt.")

    _sql_constraints = [
        ('code_uniq', 'unique (code)', 'The code of the prompt must be unique!')
    ]

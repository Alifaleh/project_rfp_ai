from odoo import models, fields

class RfpAiModelTag(models.Model):
    _name = 'rfp.ai.model.tag'
    _description = 'AI Model Tags'

    name = fields.Char(required=True)
    color = fields.Integer(string='Color Index')

class RfpAiModel(models.Model):
    _name = 'rfp.ai.model'
    _description = 'AI Model Configuration'

    name = fields.Char(required=True, help="Human-readable name (e.g., Gemini Flash)")
    technical_name = fields.Char(required=True, help="API Model ID (e.g., gemini-1.5-flash)")
    provider = fields.Selection([
        ('google', 'Google Gemini'),
        # Future extensibility
        ('openai', 'OpenAI'),
        ('anthropic', 'Anthropic'),
    ], default='google', required=True)
    
    tag_ids = fields.Many2many('rfp.ai.model.tag', string="Tags")
    description = fields.Text()

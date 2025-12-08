from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rfp_gemini_api_key = fields.Char(string="Gemini API Key", config_parameter='project_rfp_ai.gemini_api_key', help="API Key for Google Gemini Service")
    rfp_gemini_model = fields.Char(string="Gemini Model Name", config_parameter='project_rfp_ai.gemini_model', default='gemini-3-pro-preview', help="e.g. gemini-2.0-flash, gemini-3-pro, gemini-3-pro-preview")

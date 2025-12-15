from odoo import models, fields

class RfpFieldSuggestion(models.Model):
    _name = 'rfp.field.suggestion'
    _description = 'RFP Custom Field Suggestion'
    _order = 'sequence, id'

    field_id = fields.Many2one('rfp.custom.field', string="Field", required=True, ondelete='cascade')
    name = fields.Char(string="Suggestion", required=True, help="Suggested value text")
    sequence = fields.Integer(string="Sequence", default=10)

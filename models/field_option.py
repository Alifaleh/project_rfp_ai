from odoo import models, fields

class RfpFieldOption(models.Model):
    _name = 'rfp.field.option'
    _description = 'RFP Custom Field Option'
    _order = 'sequence, id'

    field_id = fields.Many2one('rfp.custom.field', string="Field", required=True, ondelete='cascade')
    value = fields.Char(string="Value", required=True, help="The value stored in the database")
    label = fields.Char(string="Label", required=True, help="The value displayed to the user")
    group_name = fields.Char(string="Group Name", help="Category for grouping in dropdowns")
    sequence = fields.Integer(string="Sequence", default=10)

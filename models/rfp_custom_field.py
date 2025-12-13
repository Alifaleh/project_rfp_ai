from odoo import models, fields, api

class RfpCustomField(models.Model):
    _name = 'rfp.custom.field'
    _description = 'RFP Custom Field'
    _order = 'sequence, id'

    name = fields.Char(string="Label", required=True, help="Question label visible to user")
    code = fields.Char(string="Field Key", required=True, help="Unique identifier context key")
    
    phase = fields.Selection([
        ('init', 'Initialization (Start Screen)'),
        ('post_gathering', 'Post-Analysis (Before Architecture)')
    ], string="Phase", required=True, default='init')

    input_type = fields.Selection([
        ('text_input', 'Text Input'),
        ('textarea', 'Text Area'),
        ('select', 'Dropdown'),
        ('radio', 'Radio Button'),
        ('checkboxes', 'Multi-Select Checkboxes')
    ], string="Input Type", default='text_input', required=True)

    # Deprecated: usage migrated to option_ids
    options = fields.Text(string="Options (JSON)", default="[]") 
    
    option_ids = fields.One2many('rfp.field.option', 'field_id', string="Options")
    
    placeholder = fields.Char(string="Placeholder")
    default_value = fields.Char(string="Default Value")
    is_required = fields.Boolean(string="Is Required", default=False)
    help_text = fields.Char(string="Help Tooltip")
    
    sequence = fields.Integer(string="Sequence", default=10)
    
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code, phase)', 'Field Key must be unique per phase!')
    ]

from odoo import models, fields
import json


class RfpEvalInput(models.Model):
    _name = 'rfp.eval.input'
    _description = 'RFP Evaluation Criteria Input'
    _order = 'round_number, sequence, id'

    sequence = fields.Integer(string="Sequence", default=10)
    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    field_key = fields.Char(string="Field Key", required=True, help="Unique identifier from JSON schema")
    label = fields.Char(string="Question/Label")
    component_type = fields.Selection([
        ('text_input', 'Text Input'),
        ('number_input', 'Number Input'),
        ('textarea', 'Text Area'),
        ('select', 'Dropdown'),
        ('multiselect', 'Multi Select'),
        ('radio', 'Radio Button'),
        ('boolean', 'Checkbox')
    ], string="Component Type", default='text_input')
    options = fields.Text(string="Options JSON", help="JSON list of options for select fields")
    user_value = fields.Text(string="User Response")
    data_type = fields.Char(string="Data Type", help="Used for validation (e.g., integrity, string)")
    description_tooltip = fields.Char(string="Description Tooltip", help="Helper text for the user")
    question_rationale = fields.Text(string="Question Rationale", help="AI explanation of why this question is being asked")
    round_number = fields.Integer(string="Round Number", help="Iteration round used for tracking analysis depth")

    suggested_answers = fields.Text(string="Suggested Answers JSON", help="AI suggestions for auto-fill")
    depends_on = fields.Text(string="Dependency JSON", help="Visibility logic {field_key, value}")
    is_irrelevant = fields.Boolean(string="Marked Irrelevant", default=False)
    irrelevant_reason = fields.Char(string="Reason for Irrelevance")
    is_auto_filled = fields.Boolean(string="Auto-Filled by AI", default=False)
    specify_triggers = fields.Text(string="Specify Triggers JSON")

    def get_suggested_answers_parsed(self):
        if not self.suggested_answers:
            return []
        try:
            return json.loads(self.suggested_answers)
        except Exception:
            return []

    def get_depends_on_parsed(self):
        if not self.depends_on:
            return {}
        try:
            return json.loads(self.depends_on)
        except Exception:
            return {}

    def get_specify_triggers_parsed(self):
        if not self.specify_triggers:
            return []
        try:
            return json.loads(self.specify_triggers)
        except Exception:
            return []

    def get_options_parsed(self):
        options_data = []
        if self.options:
            try:
                options_data = json.loads(self.options)
            except Exception:
                pass

        if not options_data and self.suggested_answers:
            try:
                options_data = json.loads(self.suggested_answers)
            except Exception:
                pass

        return options_data

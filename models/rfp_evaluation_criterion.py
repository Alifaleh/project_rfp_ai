from odoo import models, fields


class RfpEvaluationCriterion(models.Model):
    _name = 'rfp.evaluation.criterion'
    _description = 'RFP Evaluation Criterion'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    name = fields.Char(string="Criterion Name", required=True, help="e.g. 'Cloud Infrastructure Experience'")
    description = fields.Text(string="Description", help="Detailed description of what this criterion evaluates")
    category = fields.Selection([
        ('technical', 'Technical'),
        ('commercial', 'Commercial'),
        ('experience', 'Experience'),
        ('compliance', 'Compliance'),
        ('timeline', 'Timeline'),
        ('methodology', 'Methodology'),
        ('support', 'Support & SLA'),
        ('innovation', 'Innovation'),
        ('other', 'Other'),
    ], string="Category", default='other')
    weight = fields.Integer(string="Weight", default=10, help="Relative importance weight (1-100)")
    is_must_have = fields.Boolean(string="Must-Have", default=False, help="If True, failure on this criterion means automatic rejection")
    scoring_guidance = fields.Text(string="Scoring Guidance", help="AI guidance for how to score this criterion")
    sequence = fields.Integer(string="Sequence", default=10)
    active = fields.Boolean(string="Active", default=True)

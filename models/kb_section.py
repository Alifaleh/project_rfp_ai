from odoo import models, fields, api


class RfpKbSection(models.Model):
    _name = 'rfp.kb.section'
    _description = 'Knowledge Base Section'
    _order = 'sequence, id'

    kb_id = fields.Many2one(
        'rfp.knowledge.base', string="Knowledge Base",
        required=True, ondelete='cascade')
    title = fields.Char(string="Section Title", required=True)
    section_type = fields.Selection([
        ('introduction', 'Introduction / Overview'),
        ('functional', 'Functional Requirements'),
        ('technical', 'Technical Requirements'),
        ('compliance', 'Compliance / Standards'),
        ('security', 'Security'),
        ('timeline', 'Timeline / Schedule'),
        ('budget', 'Budget / Commercial'),
        ('evaluation', 'Evaluation Criteria'),
        ('support', 'Support / SLA'),
        ('appendix', 'Appendix / Other'),
    ], string="Section Type", default='functional')
    sequence = fields.Integer(string="Sequence", default=10)
    description = fields.Text(
        string="Content Description",
        help="Generalized best practices and content guidance for this section type")
    key_topics = fields.Text(
        string="Key Topics (JSON)",
        help="JSON list of key topics covered in this section")

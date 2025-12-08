from odoo import models, fields

class RfpDocumentSection(models.Model):
    _name = 'rfp.document.section'
    _description = 'RFP Document Section'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    section_title = fields.Char(string="Title", required=True)
    content_markdown = fields.Text(string="Content (Markdown)")
    sequence = fields.Integer(string="Sequence", default=10)

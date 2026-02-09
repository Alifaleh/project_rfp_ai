from odoo import models, fields


class RfpRequiredDocument(models.Model):
    _name = 'rfp.required.document'
    _description = 'Required Document Type for RFP'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    name = fields.Char(string="Document Name", required=True, help="e.g. 'Technical Proposal', 'Financial Proposal'")
    description = fields.Text(string="Description", help="Instructions for the vendor about what to include")
    is_required = fields.Boolean(string="Required", default=True, help="If True, vendor must upload this document")
    accept_types = fields.Char(string="Accepted File Types", default=".pdf,.doc,.docx",
                               help="Comma-separated file extensions")
    sequence = fields.Integer(string="Sequence", default=10)

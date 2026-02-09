from odoo import models, fields


class RfpProposalDocument(models.Model):
    _name = 'rfp.proposal.document'
    _description = 'Proposal Uploaded Document'
    _order = 'sequence, id'

    proposal_id = fields.Many2one('rfp.proposal', string="Proposal", required=True, ondelete='cascade')
    required_document_id = fields.Many2one('rfp.required.document', string="Document Type",
                                           ondelete='set null',
                                           help="Links to the required document definition")
    name = fields.Char(string="Document Name", required=True)
    file_data = fields.Binary(string="File", attachment=True)
    filename = fields.Char(string="Filename")
    sequence = fields.Integer(string="Sequence", default=10)

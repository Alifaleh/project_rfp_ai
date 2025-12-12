from odoo import models, fields

class RfpProjectDomain(models.Model):
    _name = 'rfp.project.domain'
    _description = 'Project Domain'
    _order = 'name'

    name = fields.Char(string='Domain Name', required=True)
    description = fields.Text(string='Description', help="Description of this domain context for the AI")

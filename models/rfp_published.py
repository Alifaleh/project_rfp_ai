import uuid
from odoo import models, fields, api


class RfpPublished(models.Model):
    _name = 'rfp.published'
    _description = 'Published RFP'
    _order = 'published_date desc'

    uuid = fields.Char(string="Public Access Token", readonly=True, copy=False, index=True)
    project_id = fields.Many2one('rfp.project', string="Source Project", required=True, ondelete='cascade')
    title = fields.Char(string="Title", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Published", default=True)
    published_date = fields.Datetime(string="Published Date", readonly=True)
    last_updated = fields.Datetime(string="Last Updated", readonly=True)
    
    section_ids = fields.One2many('rfp.published.section', 'published_id', string="Sections")
    proposal_ids = fields.One2many('rfp.proposal', 'published_id', string="Proposals")
    proposal_count = fields.Integer(string="Proposals", compute='_compute_proposal_count')
    
    owner_id = fields.Many2one('res.users', string="Owner", default=lambda self: self.env.user)

    @api.depends('proposal_ids')
    def _compute_proposal_count(self):
        for rec in self:
            rec.proposal_count = len(rec.proposal_ids)

    @api.model
    def create(self, vals):
        if not vals.get('uuid'):
            vals['uuid'] = str(uuid.uuid4())
        if not vals.get('published_date'):
            vals['published_date'] = fields.Datetime.now()
        vals['last_updated'] = fields.Datetime.now()
        return super().create(vals)

    def write(self, vals):
        vals['last_updated'] = fields.Datetime.now()
        return super().write(vals)

    def get_public_url(self):
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/rfp/public/{self.uuid}"

    def copy_content_from_project(self):
        """Copy or update content from source project."""
        self.ensure_one()
        project = self.project_id
        
        # Update title and description
        self.write({
            'title': project.name,
            'description': project.description,
        })
        
        # Clear existing sections
        self.section_ids.unlink()
        
        # Copy sections from project
        for section in project.document_section_ids.sorted(lambda s: s.sequence):
            published_section = self.env['rfp.published.section'].create({
                'published_id': self.id,
                'title': section.section_title,
                'content_html': section.content_html,
                'sequence': section.sequence,
            })
            
            # Copy diagrams
            for diagram in section.diagram_ids:
                self.env['rfp.published.diagram'].create({
                    'section_id': published_section.id,
                    'title': diagram.title,
                    'image_file': diagram.image_file,
                })


class RfpPublishedSection(models.Model):
    _name = 'rfp.published.section'
    _description = 'Published RFP Section'
    _order = 'sequence, id'

    published_id = fields.Many2one('rfp.published', string="Published RFP", required=True, ondelete='cascade')
    title = fields.Char(string="Title", required=True)
    content_html = fields.Html(string="Content")
    sequence = fields.Integer(string="Sequence", default=10)
    diagram_ids = fields.One2many('rfp.published.diagram', 'section_id', string="Diagrams")


class RfpPublishedDiagram(models.Model):
    _name = 'rfp.published.diagram'
    _description = 'Published RFP Diagram'

    section_id = fields.Many2one('rfp.published.section', string="Section", required=True, ondelete='cascade')
    title = fields.Char(string="Title")
    image_file = fields.Binary(string="Image", attachment=True)


class RfpProposal(models.Model):
    _name = 'rfp.proposal'
    _description = 'Vendor Proposal'
    _order = 'submitted_date desc'

    published_id = fields.Many2one('rfp.published', string="RFP", required=True, ondelete='cascade')
    
    # Vendor Info
    company_name = fields.Char(string="Company Name", required=True)
    contact_person = fields.Char(string="Contact Person", required=True)
    email = fields.Char(string="Email", required=True)
    phone = fields.Char(string="Phone")
    website = fields.Char(string="Company Website")
    linkedin = fields.Char(string="LinkedIn URL")
    
    # Proposal
    proposal_file = fields.Binary(string="Proposal PDF", attachment=True)
    proposal_filename = fields.Char(string="Filename")
    notes = fields.Text(string="Additional Notes")
    
    # Meta
    submitted_date = fields.Datetime(string="Submitted", default=fields.Datetime.now, readonly=True)
    
    # Status
    status = fields.Selection([
        ('new', 'New'),
        ('reviewing', 'Under Review'),
        ('shortlisted', 'Shortlisted'),
        ('rejected', 'Rejected'),
        ('accepted', 'Accepted'),
    ], string="Status", default='new')

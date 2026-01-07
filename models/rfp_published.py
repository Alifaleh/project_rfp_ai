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
    
    # AI Analysis Fields
    analysis_status = fields.Selection([
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string="Analysis Status", default='pending')
    analysis_job_id = fields.Many2one('queue.job', string="Analysis Job", readonly=True)
    analysis_result = fields.Text(string="Analysis Result (JSON)")
    coverage_score = fields.Integer(string="Coverage Score")
    overall_rating = fields.Char(string="Overall Rating")
    ai_recommendation = fields.Selection([
        ('shortlist', 'Shortlist'),
        ('review', 'Review'),
        ('reject', 'Reject'),
    ], string="AI Recommendation")
    
    @api.model
    def create(self, vals):
        record = super().create(vals)
        # Trigger AI analysis via queue job
        if record.proposal_file:
            record._trigger_analysis_job()
        return record
    
    def _trigger_analysis_job(self):
        """Queue the AI analysis job."""
        self.ensure_one()
        self.write({'analysis_status': 'pending'})
        
        # Get the prompt record
        prompt_record = self.env['rfp.prompt'].search([('code', '=', 'prompt_analyze_proposal')], limit=1)
        prompt_id = prompt_record.id if prompt_record else None
        
        # Create queue job
        job = self.with_delay(
            channel='root.rfp_ai',
            description=f"AI Analysis: {self.company_name}"
        ).analyze_proposal_job(prompt_id)
        
        # Store job reference
        if hasattr(job, 'db_record'):
            self.write({'analysis_job_id': job.db_record().id})
    
    def analyze_proposal_job(self, prompt_record_id=None):
        """Queue job: Analyze proposal against RFP content using AI."""
        import json
        import base64
        self.ensure_one()
        self.write({'analysis_status': 'processing'})
        
        try:
            # Get RFP content
            published = self.published_id
            rfp_content = f"# {published.title}\n\n{published.description or ''}\n\n"
            for section in published.section_ids.sorted(lambda s: s.sequence):
                rfp_content += f"## {section.title}\n{section.content_html or ''}\n\n"
            
            # Get proposal content
            proposal_content = f"Company: {self.company_name}\n"
            proposal_content += f"Contact: {self.contact_person} ({self.email})\n"
            if self.notes:
                proposal_content += f"Notes: {self.notes}\n"
            
            # If PDF, extract text (simplified - just use filename as indicator)
            if self.proposal_file and self.proposal_filename:
                proposal_content += f"\n[Attached file: {self.proposal_filename}]\n"
                # For PDF content extraction, we'd need a PDF library
                # For now, we pass the file info
            
            # Build the prompt
            prompt_record = self.env['rfp.prompt'].browse(prompt_record_id) if prompt_record_id else None
            
            if prompt_record and prompt_record.template_text:
                user_context = prompt_record.template_text.format(
                    rfp_content=rfp_content,
                    proposal_content=proposal_content,
                    company_name=self.company_name
                )
            else:
                user_context = f"""
Analyze this vendor proposal against the RFP requirements.

## RFP CONTENT:
{rfp_content}

## PROPOSAL:
{proposal_content}

Provide a comprehensive analysis in the required JSON format.
"""
            
            # Get schema
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_proposal_analysis_schema
            
            system_prompt = """You are an expert procurement analyst. Analyze vendor proposals against RFP requirements.
Provide objective, actionable insights to help decision-makers evaluate proposals effectively.
Be specific about what's covered, what's missing, and what risks exist."""
            
            # Call AI
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='json',
                schema=get_proposal_analysis_schema(),
                prompt_record=prompt_record
            )
            
            # Parse response
            try:
                data = json.loads(response_json_str)
            except json.JSONDecodeError:
                data = {}
            
            # Store results
            self.write({
                'analysis_status': 'done',
                'analysis_result': response_json_str,
                'coverage_score': data.get('coverage_score', 0),
                'overall_rating': data.get('overall_rating', 'Unknown'),
                'ai_recommendation': data.get('recommendation', '').lower() if data.get('recommendation') else None,
            })
            
        except Exception as e:
            self.write({
                'analysis_status': 'failed',
                'analysis_result': json.dumps({'error': str(e)})
            })
            raise e

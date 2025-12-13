import json
from odoo import models, fields, api

class RfpSectionDiagram(models.Model):
    _name = 'rfp.section.diagram'
    _description = 'RFP Section Diagram'

    section_id = fields.Many2one('rfp.document.section', string="Section", ondelete='cascade')
    title = fields.Char(string="Diagram Title", required=True)
    description = fields.Text(string="Description", required=True)

class RfpDocumentSection(models.Model):
    _name = 'rfp.document.section'
    _description = 'RFP Document Section'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    section_title = fields.Char(string="Title", required=True)
    content_html = fields.Html(string="Content (HTML)", sanitize=True, sanitize_tags=True, sanitize_attributes=True, sanitize_style=True, strip_style=True)
    sequence = fields.Integer(string="Sequence", default=10)

    diagram_ids = fields.One2many('rfp.section.diagram', 'section_id', string="Diagrams")
    
    job_id = fields.Many2one('queue.job', string="Generation Job", readonly=True)
    generation_status = fields.Selection([
        ('pending', 'Pending'),
        ('queued', 'Waiting for AI'),
        ('generating', 'Generating'),
        ('success', 'Content Generated'),
        ('failed', 'Generation Failed')
    ], string="Status", default='pending')

    def generate_content_job(self, system_prompt, user_context):
        self.ensure_one()
        self.write({'generation_status': 'generating'})
        
        try:
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_section_content_schema
            
            # We use the existing AI Log wrapper which handles API calls, retry, and logging.
            # Updated to request JSON schema for Diagrams + Content.
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='json',
                schema=get_section_content_schema()
            )
            
            try:
                data = json.loads(response_json_str)
            except json.JSONDecodeError:
                # Fallbck if AI returns generic text instead of JSON
                data = {"content_html": response_json_str, "diagrams": []}
            
            # Save Content
            self.write({
                'content_html': data.get('content_html', ''),
                'generation_status': 'success'
            })
            
            # Save Diagrams
            # Clear old diagrams first if re-running
            self.diagram_ids.unlink()
            
            diagrams = data.get('diagrams', [])
            if diagrams:
                self.env['rfp.section.diagram'].create([
                    {
                        'section_id': self.id,
                        'title': d.get('title'),
                        'description': d.get('description')
                    } for d in diagrams
                ])
            
        except Exception as e:
            self.write({'generation_status': 'failed'})
            raise e # Raise to let queue_job handle the retry/failure state on the job record too

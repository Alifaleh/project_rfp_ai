import json
from odoo import models, fields, api
import base64

class RfpSectionDiagram(models.Model):
    _name = 'rfp.section.diagram'
    _description = 'RFP Section Diagram'

    section_id = fields.Many2one('rfp.document.section', string="Section", ondelete='cascade')
    title = fields.Char(string="Diagram Title", required=True)
    description = fields.Text(string="Description", required=True)
    
    image_file = fields.Binary(string="Generated Image", attachment=True)
    image_filename = fields.Char(string="Image Filename")
    
    job_id = fields.Many2one('queue.job', string="Generation Job", readonly=True)

    def generate_image_job(self, prompt_record_id=None):
        self.ensure_one()
        try:
            prompt_record = self.env['rfp.prompt'].browse(prompt_record_id) if prompt_record_id else None
            
            # Fallback Prompt Construction
            project = self.section_id.project_id
            if prompt_record:
                prompt = prompt_record.template_text.format(
                    project_name=project.name,
                    domain=project.domain_id.name or 'General',
                    description=self.description
                )
            else:
                prompt = f" Generate a professional diagram based on this exact specification:\n\n{self.description}"
            
            image_bytes = self.env['rfp.ai.log'].execute_image_request(prompt=prompt, env=self.env, prompt_record=prompt_record)
            
            if image_bytes:
                self.write({
                    'image_file': base64.b64encode(image_bytes),
                    'image_filename': f"diagram_{self.id}.png"
                })
        except Exception as e:
            raise e # Queue Job handles retry/failure
            

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
            
            # Retrieve Prompt Record for Logging
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'writer_section_content')], limit=1)

            # We use the existing AI Log wrapper which handles API calls, retry, and logging.
            # Updated to request JSON schema for Diagrams + Content.
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='json',
                schema=get_section_content_schema(),
                prompt_record=prompt_record
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

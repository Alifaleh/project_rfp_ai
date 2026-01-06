from odoo import models, fields, api
import base64

class RfpKnowledgeBase(models.Model):
    _name = 'rfp.knowledge.base'
    _description = 'RFP Knowledge Base'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    domain_id = fields.Many2one('rfp.project.domain', string="Domain", tracking=True)
    
    # Document
    document = fields.Binary(string="Document", required=True, attachment=True)
    filename = fields.Char(string="Filename")
    mimetype = fields.Char(string="Mime Type", default='application/pdf')
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('analyzing', 'Analyzing'),
        ('ready', 'Ready'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('failed', 'Failed')
    ], default='draft', string="Status", tracking=True)
    
    # Content
    extracted_practices = fields.Text(string="Extracted Best Practices", tracking=True)
    
    def action_analyze(self):
        """Triggers the analysis job."""
        self.ensure_one()
        self.state = 'analyzing'
        # Queue Job Trigger
        self.with_delay(channel='root.rfp_generation')._run_analysis_job()
            
    def _run_analysis_job(self):
        """Actual Analysis Logic (Async)."""
        self.ensure_one()
        try:
             # Logic to be implemented in ai_connector update
            from odoo.addons.project_rfp_ai.utils import ai_connector
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_kb_analysis_schema
            import json
            
            prompt_code = 'kb_analyzer'
            prompt_record = self.env['rfp.prompt'].search([('code', '=', prompt_code)], limit=1)
            
            # Fetch Available Domains
            existing_domains = self.env['rfp.project.domain'].search([])
            domain_list = "\n".join([f"- {d.name}" for d in existing_domains])

            if not prompt_record:
                system_prompt = "Analyze this document and extract best practices."
            else:
                system_prompt = prompt_record.template_text.format(available_domains=domain_list)

            # Prepare attachment
            file_content = base64.b64decode(self.document)
            
            attachments = [{
                'data': file_content,
                'mime_type': self.mimetype or 'application/pdf'
            }]

            response_text = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=f"Analyze the attached document: {self.filename}",
                env=self.env,
                mode='json', # Changed to JSON
                schema=get_kb_analysis_schema(),
                prompt_record=prompt_record,
                attachments=attachments 
            )
            
            if response_text:
                try:
                    data = json.loads(response_text)
                    self.extracted_practices = data.get('extracted_practices')
                    
                    suggested_domain = data.get('suggested_domain_name')
                    if suggested_domain:
                        match = next((d for d in existing_domains if d.name.lower() == suggested_domain.lower()), None)
                        if match:
                            self.domain_id = match.id
                        else:
                            new_domain = self.env['rfp.project.domain'].create({'name': suggested_domain})
                            self.domain_id = new_domain.id

                    self.state = 'ready'
                except json.JSONDecodeError:
                    self.message_post(body="Analysis failed: Invalid JSON response.")
                    self.state = 'failed'
            else:
                self.message_post(body="Analysis failed: No response from AI.")
                self.state = 'failed' 
                
        except Exception as e:
            self.env.cr.rollback()
            self.write({'state': 'failed'})
            self.message_post(body=f"Analysis failed: {str(e)}")
            self.env.cr.commit()
            raise e

    def action_activate(self):
        self.state = 'active'
        
    def action_deactivate(self):
        self.state = 'inactive'
        
    def action_set_draft(self):
        self.state = 'draft'

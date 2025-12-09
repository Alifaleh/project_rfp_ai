from odoo import models, fields, api

class RfpDocumentSection(models.Model):
    _name = 'rfp.document.section'
    _description = 'RFP Document Section'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    section_title = fields.Char(string="Title", required=True)
    content_markdown = fields.Text(string="Content (Markdown)")
    sequence = fields.Integer(string="Sequence", default=10)

    job_id = fields.Many2one('queue.job', string="Generation Job", readonly=True)
    generation_status = fields.Selection([
        ('pending', 'Pending'),
        ('queued', 'Waiting for AI'),
        ('generating', 'Generating'),
        ('success', 'Content Generated'),
        ('failed', 'Generation Failed')
    ], string="Status", default='pending')

    @api.model
    def generate_content_job(self, system_prompt, user_context):
        self.ensure_one()
        self.write({'generation_status': 'generating'})
        
        try:
            # We use the existing AI Log wrapper which handles API calls, retry, and logging.
            # Note: We must pass 'env=self.env' explicitly if calling from a job context? 
            # Usually self.env works fine in job context.
            content = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='text'
            )
            
            self.write({
                'content_markdown': content,
                'generation_status': 'success'
            })
            
        except Exception as e:
            self.write({'generation_status': 'failed'})
            raise e # Raise to let queue_job handle the retry/failure state on the job record too

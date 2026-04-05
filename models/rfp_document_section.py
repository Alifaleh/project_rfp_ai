import json
from odoo import models, fields, api
import base64

class RfpSectionDiagram(models.Model):
    _name = 'rfp.section.diagram'
    _description = 'RFP Section Diagram'

    section_id = fields.Many2one('rfp.document.section', string="Section", ondelete='cascade')
    title = fields.Char(string="Diagram Title", required=True)
    description = fields.Text(string="Description", required=True)
    diagram_type = fields.Selection([
        ('mermaid', 'Mermaid (Flowchart/Architecture)'),
        ('illustration', 'Illustration (Physical/Engineering)'),
    ], string="Diagram Type", default='mermaid')
    mermaid_code = fields.Text(string="Mermaid Code")

    image_file = fields.Binary(string="Generated Image", attachment=True)
    image_filename = fields.Char(string="Image Filename")

    job_id = fields.Many2one('queue.job', string="Generation Job", readonly=True)

    def generate_image_job(self, prompt_record_id=None):
        self.ensure_one()
        try:
            if self.diagram_type == 'mermaid' and self.mermaid_code:
                # Render Mermaid code to PNG via Kroki API
                from odoo.addons.project_rfp_ai.utils.ai_connector import _render_mermaid
                image_bytes = _render_mermaid(self.mermaid_code)
            else:
                # Illustration: use Imagen to generate image
                prompt_record = self.env['rfp.prompt'].browse(prompt_record_id) if prompt_record_id else None
                project = self.section_id.project_id
                if prompt_record:
                    prompt = prompt_record.template_text.format(
                        project_name=project.name,
                        domain=project.domain_id.name or 'General',
                        description=self.description
                    )
                else:
                    prompt = f"Generate a professional diagram based on this exact specification:\n\n{self.description}"

                image_bytes = self.env['rfp.ai.log'].execute_image_request(prompt=prompt, env=self.env, prompt_record=prompt_record)

            if image_bytes:
                self.write({
                    'image_file': base64.b64encode(image_bytes),
                    'image_filename': f"diagram_{self.id}.png"
                })
        except Exception as e:
            raise e
            

class RfpDocumentSection(models.Model):
    _name = 'rfp.document.section'
    _description = 'RFP Document Section'
    _order = 'sequence, id'

    project_id = fields.Many2one('rfp.project', string="Project", required=True, ondelete='cascade')
    section_title = fields.Char(string="Title", required=True)
    content_html = fields.Html(string="Content (HTML)", sanitize=True, sanitize_tags=True, sanitize_attributes=True, sanitize_style=True, strip_style=True)
    sequence = fields.Integer(string="Sequence", default=10)
    section_type = fields.Selection([
        ('narrative', 'Narrative'),
        ('boq', 'Bill of Quantities'),
    ], string="Section Type", default='narrative')
    structured_data = fields.Text(string="Structured Data (JSON)",
                                  help="JSON for structured sections like BOQ.")

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
            if self.section_type == 'boq':
                self._generate_boq_content(system_prompt, user_context)
            else:
                self._generate_narrative_content(system_prompt, user_context)
        except Exception as e:
            self.write({'generation_status': 'failed'})
            raise e

    def _generate_narrative_content(self, system_prompt, user_context):
        """Generate standard narrative section content."""
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_section_content_schema

        prompt_record = self.env['rfp.prompt'].search([('code', '=', 'writer_section_content')], limit=1)

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
            data = {"content_html": response_json_str, "diagrams": []}

        self.write({
            'content_html': data.get('content_html', ''),
            'generation_status': 'success'
        })

        self.diagram_ids.unlink()
        diagrams = data.get('diagrams', [])
        if diagrams:
            self.env['rfp.section.diagram'].create([
                {
                    'section_id': self.id,
                    'title': d.get('title'),
                    'description': d.get('description', ''),
                    'diagram_type': d.get('diagram_type', 'mermaid'),
                    'mermaid_code': d.get('mermaid_code', ''),
                } for d in diagrams
            ])

    def _generate_boq_content(self, system_prompt, user_context):
        """Generate BOQ structured data via AI, then render to HTML."""
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_boq_content_schema
        from odoo.addons.project_rfp_ai.const import PROMPT_WRITER_BOQ

        prompt_record = self.env['rfp.prompt'].search(
            [('code', '=', PROMPT_WRITER_BOQ)], limit=1)

        response_json_str = self.env['rfp.ai.log'].execute_request(
            system_prompt=system_prompt,
            user_context=user_context,
            env=self.env,
            mode='json',
            schema=get_boq_content_schema(),
            prompt_record=prompt_record
        )

        try:
            data = json.loads(response_json_str)
        except json.JSONDecodeError:
            data = {"introduction": "", "categories": []}

        self.write({
            'structured_data': json.dumps(data),
            'content_html': self._render_boq_html(data),
            'generation_status': 'success'
        })

    @staticmethod
    def _render_boq_html(data):
        """Render BOQ JSON data into an HTML table for content_html."""
        import html as html_mod
        categories = data.get('categories', [])
        if not categories:
            return '<p>No items generated.</p>'

        parts = []
        intro = data.get('introduction', '')
        if intro:
            parts.append(f'<p>{html_mod.escape(intro)}</p>')

        parts.append('<table class="table table-bordered">')
        parts.append('<thead><tr>'
                     '<th>#</th>'
                     '<th>Description</th>'
                     '<th>Unit</th>'
                     '<th>Quantity</th>'
                     '<th>Notes</th>'
                     '</tr></thead><tbody>')

        idx = 1
        for cat in categories:
            cat_name = html_mod.escape(cat.get('category', ''))
            parts.append(f'<tr><td colspan="5"><strong>{cat_name}</strong></td></tr>')
            for item in cat.get('items', []):
                desc = html_mod.escape(item.get('description', ''))
                unit = html_mod.escape(item.get('unit', ''))
                qty = html_mod.escape(str(item.get('quantity', '')))
                notes = html_mod.escape(item.get('notes', ''))
                parts.append(f'<tr><td>{idx}</td><td>{desc}</td>'
                             f'<td>{unit}</td><td>{qty}</td><td>{notes}</td></tr>')
                idx += 1

        parts.append('</tbody></table>')
        return ''.join(parts)

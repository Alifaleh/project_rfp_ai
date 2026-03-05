from odoo import models, fields, api
from odoo.addons.project_rfp_ai.const import (
    PROMPT_KB_STRUCTURE_EXTRACTOR,
    PROMPT_KB_CONTENT_EXTRACTOR,
    PROMPT_KB_PROJECT_GENERALIZER,
)
import base64
import json
import logging

_logger = logging.getLogger(__name__)


class RfpKnowledgeBase(models.Model):
    _name = 'rfp.knowledge.base'
    _description = 'RFP Knowledge Base'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(required=True, tracking=True)
    domain_id = fields.Many2one('rfp.project.domain', string="Domain", tracking=True)

    # Source
    source_type = fields.Selection([
        ('document', 'Uploaded Document'),
        ('project', 'Completed Project'),
    ], string="Source Type", default='document', tracking=True)
    source_project_id = fields.Many2one(
        'rfp.project', string="Source Project",
        help="If source is a completed project, link to it")

    # Document
    document = fields.Binary(string="Document", attachment=True)
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

    # Structured content
    summary = fields.Text(string="Summary",
        help="AI-generated concise summary of what this KB covers, used for smart selection")
    section_ids = fields.One2many('rfp.kb.section', 'kb_id', string="Sections")
    section_count = fields.Integer(
        string="Section Count", compute='_compute_section_count', store=True)

    # Legacy / backward-compat
    extracted_practices = fields.Text(string="Extracted Best Practices", tracking=True)

    @api.depends('section_ids')
    def _compute_section_count(self):
        for rec in self:
            rec.section_count = len(rec.section_ids)

    # ─── Actions ──────────────────────────────────────────────

    def action_analyze(self):
        """Triggers the document analysis job (2-step)."""
        self.ensure_one()
        self.state = 'analyzing'
        # Clear old sections if re-analyzing
        self.section_ids.unlink()
        self.with_delay(
            channel='root.rfp_generation',
            description=f"KB Analysis: {self.name}"
        )._run_analysis_job()

    def action_view_sections(self):
        """Open the list of sections for this KB."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Sections — {self.name}',
            'res_model': 'rfp.kb.section',
            'view_mode': 'list,form',
            'domain': [('kb_id', '=', self.id)],
            'context': {'default_kb_id': self.id},
        }

    def action_activate(self):
        self.state = 'active'

    def action_deactivate(self):
        self.state = 'inactive'

    def action_set_draft(self):
        self.state = 'draft'

    # ─── Domain helper ────────────────────────────────────────

    def _resolve_domain(self, suggested_domain_name):
        """Find or create domain from AI-suggested name. Returns domain record."""
        if not suggested_domain_name:
            return self.env['rfp.project.domain']
        existing = self.env['rfp.project.domain'].search([])
        match = next(
            (d for d in existing if d.name.lower() == suggested_domain_name.lower()),
            None
        )
        if match:
            return match
        return self.env['rfp.project.domain'].create({'name': suggested_domain_name})

    def _rebuild_extracted_practices(self):
        """Rebuild the legacy extracted_practices field from structured sections."""
        parts = []
        for section in self.section_ids.sorted('sequence'):
            parts.append(f"### {section.title}\n{section.description or ''}")
        self.extracted_practices = "\n\n".join(parts) if parts else ''

    # ─── Document Analysis (2-step) ──────────────────────────

    def _run_analysis_job(self):
        """Queue job: Two-step document analysis.
        Step 1: Extract section structure + summary + domain.
        Step 2: Extract content descriptions per section.
        """
        self.ensure_one()
        try:
            from odoo.addons.project_rfp_ai.models.ai_schemas import (
                get_kb_structure_extraction_schema,
                get_kb_content_extraction_schema,
            )

            existing_domains = self.env['rfp.project.domain'].search([])
            domain_list = "\n".join([f"- {d.name}" for d in existing_domains])

            file_content = base64.b64decode(self.document)
            attachments = [{
                'data': file_content,
                'mime_type': self.mimetype or 'application/pdf'
            }]

            # ── Step 1: Structure Extraction ──
            prompt1 = self.env['rfp.prompt'].search(
                [('code', '=', PROMPT_KB_STRUCTURE_EXTRACTOR)], limit=1)
            if not prompt1:
                raise ValueError("Prompt 'kb_structure_extractor' not found.")

            system_prompt1 = prompt1.template_text.replace(
                '{available_domains}', domain_list)

            response1 = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt1,
                user_context=f"Analyze the structure of: {self.filename}",
                env=self.env,
                mode='json',
                schema=get_kb_structure_extraction_schema(),
                prompt_record=prompt1,
                attachments=attachments,
            )

            if not response1:
                self.message_post(body="Analysis failed: No response from AI (Step 1).")
                self.state = 'failed'
                return

            data1 = json.loads(response1)

            # Set domain
            domain = self._resolve_domain(data1.get('suggested_domain_name'))
            if domain:
                self.domain_id = domain.id

            # Set summary
            self.summary = data1.get('summary', '')

            # Create section records
            sections_data = data1.get('sections', [])
            section_map = {}  # title -> record, for Step 2 matching
            for idx, sec in enumerate(sections_data):
                rec = self.env['rfp.kb.section'].create({
                    'kb_id': self.id,
                    'title': sec.get('title', f'Section {idx + 1}'),
                    'section_type': sec.get('section_type', 'functional'),
                    'sequence': (idx + 1) * 10,
                })
                section_map[sec.get('title', '').lower().strip()] = rec

            _logger.info("KB %s Step 1 complete: %d sections extracted", self.id, len(sections_data))

            # ── Step 2: Content Extraction ──
            prompt2 = self.env['rfp.prompt'].search(
                [('code', '=', PROMPT_KB_CONTENT_EXTRACTOR)], limit=1)
            if not prompt2:
                raise ValueError("Prompt 'kb_content_extractor' not found.")

            # Build section list for the prompt
            section_list_text = "\n".join(
                [f"- {sec.get('title', '')} [{sec.get('section_type', '')}]"
                 for sec in sections_data])

            system_prompt2 = prompt2.template_text.replace(
                '{section_list}', section_list_text)

            response2 = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt2,
                user_context=f"Extract best practices per section from: {self.filename}",
                env=self.env,
                mode='json',
                schema=get_kb_content_extraction_schema(),
                prompt_record=prompt2,
                attachments=attachments,
            )

            if not response2:
                self.message_post(body="Analysis partially complete: Step 2 returned no response.")
                self.state = 'ready'
                return

            data2 = json.loads(response2)

            # Update sections with content
            for sec_data in data2.get('sections', []):
                title_key = (sec_data.get('title', '') or '').lower().strip()
                rec = section_map.get(title_key)
                if not rec:
                    # Fuzzy match: find closest by substring
                    for key, candidate in section_map.items():
                        if title_key in key or key in title_key:
                            rec = candidate
                            break
                if rec:
                    vals = {'description': sec_data.get('description', '')}
                    key_topics = sec_data.get('key_topics')
                    if key_topics:
                        vals['key_topics'] = json.dumps(key_topics)
                    rec.write(vals)

            # Rebuild legacy field
            self._rebuild_extracted_practices()

            _logger.info("KB %s Step 2 complete: content extracted", self.id)
            self.state = 'ready'

        except json.JSONDecodeError as e:
            self.message_post(body=f"Analysis failed: Invalid JSON response. {str(e)}")
            self.state = 'failed'
        except Exception as e:
            self.env.cr.rollback()
            self.write({'state': 'failed'})
            self.message_post(body=f"Analysis failed: {str(e)}")
            self.env.cr.commit()
            raise e

    # ─── Project-based Analysis (1-step) ─────────────────────

    def _run_project_analysis_job(self):
        """Queue job: Generalize sections from a completed project.
        Sections already exist (created from document_section_ids).
        AI classifies types + generalizes content in a single call.
        """
        self.ensure_one()
        try:
            from odoo.addons.project_rfp_ai.models.ai_schemas import (
                get_kb_project_generalization_schema,
            )

            project = self.source_project_id
            if not project:
                raise ValueError("No source project linked.")

            # Build sections context from project's document sections
            sections_context = []
            for section in project.document_section_ids.sorted('sequence'):
                sections_context.append({
                    'title': section.section_title,
                    'content_preview': (section.content_html or '')[:2000],
                })

            prompt = self.env['rfp.prompt'].search(
                [('code', '=', PROMPT_KB_PROJECT_GENERALIZER)], limit=1)
            if not prompt:
                raise ValueError("Prompt 'kb_project_generalizer' not found.")

            system_prompt = prompt.template_text.replace(
                '{sections_context}', json.dumps(sections_context, indent=2))

            response = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=f"Generalize sections from completed project: {project.name}",
                env=self.env,
                mode='json',
                schema=get_kb_project_generalization_schema(),
                prompt_record=prompt,
            )

            if not response:
                self.message_post(body="Analysis failed: No response from AI.")
                self.state = 'failed'
                return

            data = json.loads(response)

            # Set summary
            self.summary = data.get('summary', '')

            # Update existing sections with AI results
            existing_sections = {
                s.title.lower().strip(): s for s in self.section_ids
            }

            for sec_data in data.get('sections', []):
                title_key = (sec_data.get('title', '') or '').lower().strip()
                rec = existing_sections.get(title_key)
                if not rec:
                    for key, candidate in existing_sections.items():
                        if title_key in key or key in title_key:
                            rec = candidate
                            break
                if rec:
                    vals = {
                        'section_type': sec_data.get('section_type', 'functional'),
                        'description': sec_data.get('description', ''),
                    }
                    key_topics = sec_data.get('key_topics')
                    if key_topics:
                        vals['key_topics'] = json.dumps(key_topics)
                    rec.write(vals)

            # Rebuild legacy field
            self._rebuild_extracted_practices()

            _logger.info("KB %s project analysis complete", self.id)
            self.state = 'ready'

        except json.JSONDecodeError as e:
            self.message_post(body=f"Analysis failed: Invalid JSON response. {str(e)}")
            self.state = 'failed'
        except Exception as e:
            self.env.cr.rollback()
            self.write({'state': 'failed'})
            self.message_post(body=f"Analysis failed: {str(e)}")
            self.env.cr.commit()
            raise e

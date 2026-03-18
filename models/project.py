from odoo import models, fields, api
from odoo.exceptions import ValidationError
from markupsafe import Markup
import json
import logging
import base64
import zipfile
import io
from xml.etree import ElementTree
from odoo.addons.project_rfp_ai.const import *

_logger = logging.getLogger(__name__)

class RfpProject(models.Model):
    _name = 'rfp.project'
    _description = 'RFP AI Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Project Name", required=True, tracking=True)
    description = fields.Text(string="Initial Description", required=True, tracking=True)
    
    domain_id = fields.Many2one('rfp.project.domain', string="Domain Context", tracking=True)

    visibility_type = fields.Selection([('public', 'Public'), ('internal', 'Internal'), ('private', 'Private')], default='private')
    
    user_id = fields.Many2one('res.users', string="Project Owner", default=lambda self: self.env.user, tracking=True)
    
    ai_context_blob = fields.Text(string="AI Context Blob", default="{}")
    
    # New Stages based on User Request + Constants
    current_stage = fields.Selection([
        (STAGE_DRAFT, 'Draft'),
        (STAGE_INITIALIZED, 'Initialized (Research Done)'),
        (STAGE_INFO_GATHERED, 'Information Gathered'),
        (STAGE_PRACTICES_REFINED, 'Best Practices Refined'),
        (STAGE_SPECIFICATIONS_GATHERED, 'Specifications Gathered'),
        (STAGE_PRACTICES_GAP_GATHERED, 'Best Practices Info Gap Gathered'),
        (STAGE_SECTIONS_GENERATED, 'Sections Generated'),
        (STAGE_GENERATING_CONTENT, 'Generating Content'),
        (STAGE_CONTENT_GENERATED, 'Content Generated'),
        (STAGE_GENERATING_IMAGES, 'Generating Images'),
        (STAGE_IMAGES_GENERATED, 'Images Generated'),
        (STAGE_DOCUMENT_LOCKED, 'Document Locked'),
        (STAGE_COMPLETED_WITH_ERRORS, 'Completed With Errors'),
        (STAGE_COMPLETED, 'Completed'),
    ], string="Current Stage", default=STAGE_DRAFT, tracking=False, group_expand='_expand_stages')

    image_generation_progress = fields.Integer(string="Image Gen Progress", default=0, help="Transient field for progress bar")

    active = fields.Boolean(default=True)

    form_input_ids = fields.One2many('rfp.form.input', 'project_id', string="Gathered Inputs")
    practice_input_ids = fields.One2many('rfp.practice.input', 'project_id', string="Practice Inputs")
    document_section_ids = fields.One2many('rfp.document.section', 'project_id', string="Generated Sections")

    # Evaluation Criteria
    eval_input_ids = fields.One2many('rfp.eval.input', 'project_id', string="Evaluation Inputs")
    evaluation_criterion_ids = fields.One2many('rfp.evaluation.criterion', 'project_id', string="Evaluation Criteria")
    eval_criteria_status = fields.Selection([
        ('not_started', 'Not Started'),
        ('gathering', 'Gathering'),
        ('generated', 'Generated'),
        ('finalized', 'Finalized'),
    ], string="Eval Criteria Status", default='not_started')

    # Required Document Types (for vendor submissions)
    required_document_ids = fields.One2many('rfp.required.document', 'project_id', string="Required Documents")

    # Source Document (for uploaded RFP imports)
    source_document = fields.Binary(string="Source Document", attachment=True)
    source_filename = fields.Char(string="Source Filename")
    source_mimetype = fields.Char(string="Source MIME Type")
    source_extracted_text = fields.Text(string="Source Extracted Text",
        help="Full text extracted from uploaded document or source project, used for auto-fill and interview context")

    # Research Fields
    initial_research = fields.Text(string="Initial Best Practices", readonly=True, help="Broad research before gathering.")
    refined_practices = fields.Text(string="Refined Best Practices", readonly=True, help="Specific research after gathering.")

    # Knowledge Base
    kb_ids = fields.Many2many('rfp.knowledge.base', string="Selected Knowledge Bases",
        help="Knowledge bases selected by AI as relevant for this project")
    has_kb_entry = fields.Boolean(
        string="Has KB Entry", compute='_compute_has_kb_entry')
    kb_count = fields.Integer(
        string="KB Count", compute='_compute_kb_count')

    # Export Fields
    published_id = fields.Many2one('rfp.published', string="Exported RFP", readonly=True, copy=False)
    is_published = fields.Boolean(string="Is Exported", compute='_compute_is_published')



    def action_initialize_project(self):
        """
        Phase 0: Project Initialization.
        1. Identify Domain & Refine Description.
        2. Perform Initial Research.
        3. Convert 'Init' Custom Fields to Gathered Inputs.
        4. Advance Stage.
        """
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_domain_identification_schema

        for project in self:
            # --- STEP 1: Domain & Description ---
            existing_domains = self.env['rfp.project.domain'].search([])
            domain_names = [d.name for d in existing_domains]
            available_domains_str = "\n".join([f"- {name}" for name in domain_names])
            
            prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_PROJECT_INITIALIZER)], limit=1)
            if not prompt_record:
                raise ValidationError(f"System Prompt '{PROMPT_PROJECT_INITIALIZER}' not found.")
            
            system_prompt = prompt_record.template_text.format(
                project_name=project.name,
                description=project.description,
                available_domains_str=available_domains_str
            )
            
            try:
                response_json_str = self.env['rfp.ai.log'].execute_request(
                    system_prompt=system_prompt,
                    user_context=f"Project: {project.name}\nDescription: {project.description}",
                    env=self.env,
                    mode='json',
                    schema=get_domain_identification_schema(),
                    prompt_record=prompt_record
                )
            except Exception as e:
                raise ValidationError(f"AI Initialization Failed: {str(e)}")

            if not response_json_str:
                raise ValidationError("AI returned no response.")

            try:
                data = json.loads(response_json_str)
            except json.JSONDecodeError:
                raise ValidationError("AI returned invalid JSON.")
            
            suggested_domain = data.get('suggested_domain_name')
            refined_desc = data.get('refined_description')
            
            if not suggested_domain or not refined_desc:
                 raise ValidationError("AI Response missing required fields.")
                
            # Domain Handing
            match = next((d for d in existing_domains if d.name.lower() == suggested_domain.lower()), None)
            if match:
                project.domain_id = match.id
            else:
                new_domain = self.env['rfp.project.domain'].create({'name': suggested_domain})
                project.domain_id = new_domain.id
                
            project.description = refined_desc
            
            # --- STEP 2: Initial Research ---
            project._run_initial_research()
            
            # --- STEP 3: Convert Start Screen Fields ---
            # We assume the controller or UI passed these values into the context or we read from transient?
            # Actually, the user fills them in the form, and the controller likely writes them to 'project'
            # IF they were fields on the model. But custom fields are dynamic.
            # The portal controller `portal_rfp_init` receives `**kwargs`.
            # We need to capture those values and save them as `rfp.form.input`.
            
            # LOGIC CHANGE: The CONTROLLER should have passed these values to `form_input_ids` or we do it here?
            # If `action_initialize_project` is called from Backend, we might not have them.
            # The "Custom Field" logic implies we need to generate `rfp.form.input` records for ALL init custom fields,
            # and populate them with values if available.
            
            init_custom_fields = self.env['rfp.custom.field'].search([('phase', '=', 'init')])
            
            # We assume values are stored in `ai_context_blob` or passed via context?
            # Let's check where the controller puts them.
            # Current controller (portal.py) just calls `project.create`.
            # We need to update controller to pass these inputs.
            # For now, we will CREATE the input records. Value population is up to the caller/controller.
            
            for cf in init_custom_fields:
                # Check if already exists (idempotency)
                existing = project.form_input_ids.filtered(lambda i: i.field_key == cf.code)
                if not existing:
                    self.env['rfp.form.input'].create({
                        'project_id': project.id,
                        'field_key': cf.code,
                        'label': cf.name,
                        'component_type': cf.input_type,
                        # Refactor Phase 4: Init Fields to Separate Stage
                        # We explicitly set user_value to False so they appear in the gathering UI
                        'user_value': False, 
                        'sequence': cf.sequence,
                        'suggested_answers': json.dumps(cf.suggestion_ids.mapped('name')),
                        'options': json.dumps([{'value': o.value, 'label': o.label} for o in cf.option_ids]),
                        'specify_triggers': cf.specify_triggers or '[]'
                    })
            
            project.current_stage = STAGE_INITIALIZED

    @staticmethod
    def _extract_text_from_docx(file_bytes):
        """Extract plain text from a DOCX file using built-in Python modules."""
        ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
        paragraphs = []
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            with zf.open('word/document.xml') as doc_xml:
                tree = ElementTree.parse(doc_xml)
                for p in tree.getroot().iter(f'{{{ns}}}p'):
                    texts = [t.text for t in p.iter(f'{{{ns}}}t') if t.text]
                    if texts:
                        paragraphs.append(''.join(texts))
        return '\n'.join(paragraphs)

    @staticmethod
    def _extract_text_from_pdf(file_bytes):
        """Extract plain text from a PDF file using PyPDF2."""
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    parts.append(text)
            return '\n'.join(parts)
        except Exception:
            return ''

    def _auto_fill_from_source(self):
        """
        Auto-fill form input answers from source_extracted_text.
        High-confidence answers → user_value (question disappears from form).
        Medium-confidence answers → prepended to suggested_answers.
        Non-fatal: if AI call fails, user answers manually.
        """
        self.ensure_one()
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_auto_fill_schema

        source_text = self.source_extracted_text
        if not source_text or len(source_text.strip()) < 50:
            _logger.info("Project %s: No meaningful source text for auto-fill", self.id)
            return

        # 1. Get all unanswered form_inputs
        unanswered = self.form_input_ids.filtered(
            lambda i: not i.user_value and not i.is_irrelevant
        )
        if not unanswered:
            _logger.info("Project %s: No unanswered form inputs for auto-fill", self.id)
            return

        # 2. Build question list for AI
        questions = []
        for inp in unanswered:
            q = {
                "field_key": inp.field_key,
                "label": inp.label,
                "component_type": inp.component_type,
            }
            if inp.options:
                try:
                    q["options"] = json.loads(inp.options)
                except Exception:
                    pass
            if inp.suggested_answers:
                try:
                    q["existing_suggestions"] = json.loads(inp.suggested_answers)
                except Exception:
                    pass
            questions.append(q)

        questions_json = json.dumps(questions, indent=2)

        # 3. Truncate source text if needed (context window safety)
        max_source_chars = 50000
        truncated_source = source_text[:max_source_chars]
        if len(source_text) > max_source_chars:
            truncated_source += "\n\n[... Source text truncated for length ...]"

        # 4. Build prompt
        prompt_record = self.env['rfp.prompt'].search(
            [('code', '=', PROMPT_DOCUMENT_AUTO_FILLER)], limit=1
        )
        if not prompt_record:
            _logger.warning("Auto-filler prompt not found. Skipping auto-fill for project %s.", self.id)
            return

        system_prompt = prompt_record.template_text.format(
            source_text=truncated_source,
            questions_json=questions_json
        )

        # 5. Call AI
        try:
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context="Auto-fill the above questions from the source text.",
                env=self.env,
                mode='json',
                schema=get_auto_fill_schema(),
                prompt_record=prompt_record
            )
        except Exception as e:
            _logger.warning("Auto-fill AI call failed for project %s: %s", self.id, e)
            return

        if not response_json_str:
            return

        try:
            data = json.loads(response_json_str)
        except json.JSONDecodeError:
            _logger.warning("Auto-fill AI returned invalid JSON for project %s", self.id)
            return

        # 6. Apply results
        auto_fill_count = 0
        suggestion_count = 0
        input_map = {inp.field_key: inp for inp in unanswered}

        for field_result in data.get('auto_filled_fields', []):
            field_key = field_result.get('field_key')
            answer = field_result.get('answer')
            confidence = field_result.get('confidence', 'low')

            if not field_key or not answer or field_key not in input_map:
                continue

            inp = input_map[field_key]

            # Validate select/radio answers against options
            if confidence == 'high' and inp.component_type in ('select', 'radio'):
                try:
                    options = json.loads(inp.options) if inp.options else []
                    valid_values = [
                        o['value'] if isinstance(o, dict) else o
                        for o in options
                    ]
                    if answer not in valid_values:
                        confidence = 'medium'  # Demote: doesn't match options
                except Exception:
                    confidence = 'medium'

            if confidence == 'high':
                inp.write({
                    'user_value': answer,
                    'is_auto_filled': True,
                })
                auto_fill_count += 1
            elif confidence == 'medium':
                try:
                    suggestions = json.loads(inp.suggested_answers) if inp.suggested_answers else []
                except Exception:
                    suggestions = []
                if answer not in suggestions:
                    suggestions.insert(0, answer)
                inp.write({
                    'suggested_answers': json.dumps(suggestions)
                })
                suggestion_count += 1

        _logger.info(
            "Auto-fill for project %s: %d high-confidence fills, %d medium-confidence suggestions",
            self.id, auto_fill_count, suggestion_count
        )

    def action_initialize_from_document(self):
        """
        Initialize project from an uploaded RFP document.
        Sends document to AI for extraction of project metadata and init field values.
        Creates form_input records with extracted values as suggested_answers.
        """
        self.ensure_one()
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_document_extraction_schema

        # 1. Build field definitions string from init custom fields
        init_fields = self.env['rfp.custom.field'].search([('phase', '=', 'init')])
        field_defs_lines = []
        for cf in init_fields:
            line = f"- `{cf.code}` ({cf.input_type}): {cf.name}"
            options = cf.option_ids
            if options:
                opts = ", ".join([o.label for o in options])
                line += f" [Options: {opts}]"
            suggestions = cf.suggestion_ids
            if suggestions:
                suggs = ", ".join([s.name for s in suggestions])
                line += f" [Examples: {suggs}]"
            field_defs_lines.append(line)
        field_definitions = "\n".join(field_defs_lines)

        # 2. Build prompt
        existing_domains = self.env['rfp.project.domain'].search([])
        available_domains_str = "\n".join([f"- {d.name}" for d in existing_domains])

        prompt_record = self.env['rfp.prompt'].search(
            [('code', '=', 'document_analyzer')], limit=1)
        if not prompt_record:
            raise ValidationError("System Prompt 'document_analyzer' not found.")

        system_prompt = prompt_record.template_text.format(
            available_domains_str=available_domains_str,
            field_definitions=field_definitions
        )

        # 3. Prepare file content (Support Multiple Documents)
        source_attachments = self.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'rfp.project'),
            ('res_id', '=', self.id)
        ])
        
        if not source_attachments and self.source_document:
            # Fallback if no attachments found but main binary exists
            source_attachments = self.env['ir.attachment'].sudo().new({
                'name': self.source_filename or 'document.pdf',
                'datas': self.source_document,
                'res_model': 'rfp.project',
                'res_id': self.id
            })

        all_text = []
        ai_attachments = []
        filenames = []

        for att in source_attachments:
            file_content = base64.b64decode(att.datas)
            mimetype = att.mimetype
            # Manually check extension if mimetype is generic or unknown
            if not mimetype or mimetype in ['application/octet-stream', 'binary/octet-stream']:
                ext = att.name.rsplit('.', 1)[-1].lower() if '.' in att.name else ''
                if ext == 'pdf': mimetype = 'application/pdf'
                elif ext == 'docx': mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

            filenames.append(att.name)
            
            if mimetype == 'application/pdf':
                ai_attachments.append({'data': file_content, 'mime_type': 'application/pdf'})
                try:
                    extracted = self._extract_text_from_pdf(file_content)
                    if extracted:
                        all_text.append(f"--- DOCUMENT: {att.name} ---\n{extracted}")
                except Exception:
                    pass
            else:
                try:
                    # DOCX or other
                    extracted = self._extract_text_from_docx(file_content)
                    if extracted:
                        all_text.append(f"--- DOCUMENT: {att.name} ---\n{extracted}")
                except Exception:
                    pass
        
        self.source_extracted_text = "\n\n".join(all_text)
        
        user_context = f"Analyze the following RFP document(s): {', '.join(filenames)}\n\n"
        if all_text:
            user_context += f"--- BEGIN EXTRACTED CONTENT ---\n{self.source_extracted_text}\n--- END EXTRACTED CONTENT ---"
        else:
            user_context += "(No text could be extracted from the documents. Please analyze standard metadata if possible.)"

        attachments = ai_attachments if ai_attachments else None

        # 4. Call AI
        try:
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='json',
                schema=get_document_extraction_schema(),
                prompt_record=prompt_record,
                attachments=attachments
            )
        except Exception as e:
            raise ValidationError(f"AI Document Analysis Failed: {str(e)}")

        if not response_json_str:
            raise ValidationError("AI returned no response for document analysis.")

        try:
            data = json.loads(response_json_str)
        except json.JSONDecodeError:
            raise ValidationError("AI returned invalid JSON for document analysis.")

        # 5. Apply project metadata
        suggested_name = data.get('suggested_name', '')
        # Only overwrite if name is still placeholder or empty
        if (not self.name or self.name == 'Untitled Upload' or self.name == 'New Project') and suggested_name:
            self.name = suggested_name

        refined_desc = data.get('refined_description', '')
        if refined_desc:
            self.description = refined_desc

        # Domain handling (same pattern as action_initialize_project)
        suggested_domain = data.get('suggested_domain_name')
        if suggested_domain:
            match = next((d for d in existing_domains
                          if d.name.lower() == suggested_domain.lower()), None)
            if match:
                self.domain_id = match.id
            else:
                new_domain = self.env['rfp.project.domain'].create(
                    {'name': suggested_domain})
                self.domain_id = new_domain.id

        # 6. Initial research (same as normal init)
        self._run_initial_research()

        # 7. Build extraction lookup: {field_key: extracted_value}
        extractions = {}
        for item in data.get('field_extractions', []):
            key = item.get('field_key')
            val = item.get('extracted_value')
            if key and val:
                extractions[key] = val

        # Fallback: if PDF text extraction was empty, build source text from AI extraction
        if not self.source_extracted_text:
            parts = [f"Project: {self.name}", f"Description: {self.description}"]
            for item in data.get('field_extractions', []):
                k, v = item.get('field_key', ''), item.get('extracted_value', '')
                if k and v:
                    parts.append(f"{k}: {v}")
            self.source_extracted_text = "\n\n".join(parts)

        # 8. Create form_input records with extracted values as suggestions
        for cf in init_fields:
            existing = self.form_input_ids.filtered(
                lambda i, code=cf.code: i.field_key == code)
            if existing:
                continue

            # Start with default suggestions from custom field
            suggestions = list(cf.suggestion_ids.mapped('name'))

            # Add extracted value at the top if found
            extracted_val = extractions.get(cf.code)
            if extracted_val and extracted_val not in suggestions:
                suggestions.insert(0, extracted_val)

            self.env['rfp.form.input'].create({
                'project_id': self.id,
                'field_key': cf.code,
                'label': cf.name,
                'component_type': cf.input_type,
                'user_value': False,
                'sequence': cf.sequence,
                'suggested_answers': json.dumps(suggestions),
                'options': json.dumps([{'value': o.value, 'label': o.label}
                                       for o in cf.option_ids]),
                'specify_triggers': cf.specify_triggers or '[]',
            })

        # 9. Auto-fill answers from source text
        self._auto_fill_from_source()

        self.current_stage = STAGE_INITIALIZED
        _logger.info("Initialized project %s from document '%s', "
                     "extracted %d field values",
                     self.id, self.source_filename, len(extractions))

    def _select_knowledge_bases(self):
        """Smart KB selection: domain filter + AI ranking.
        Returns selected KB recordset and stores in self.kb_ids.
        """
        self.ensure_one()
        KB = self.env['rfp.knowledge.base']

        # Stage A: Domain filter (free SQL query)
        candidates = KB.search([
            ('state', '=', 'active'),
            '|',
            ('domain_id', '=', self.domain_id.id),
            ('domain_id', '=', False),
        ])

        if not candidates:
            return KB  # Empty recordset

        if len(candidates) == 1:
            self.kb_ids = [(6, 0, candidates.ids)]
            return candidates

        # Stage B: AI ranking (only when 2+ candidates)
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_kb_selection_schema
        from odoo.addons.project_rfp_ai.const import PROMPT_KB_SELECTOR

        prompt = self.env['rfp.prompt'].search(
            [('code', '=', PROMPT_KB_SELECTOR)], limit=1)

        if not prompt:
            # Fallback: just use all domain-matching KBs
            self.kb_ids = [(6, 0, candidates.ids)]
            return candidates

        # Build candidate summaries for AI
        kb_summaries = []
        for kb in candidates:
            kb_summaries.append(
                f"ID: {kb.id} | Name: {kb.name} | "
                f"Domain: {kb.domain_id.name if kb.domain_id else 'General'} | "
                f"Sections: {kb.section_count} | "
                f"Summary: {kb.summary or (kb.extracted_practices or '')[:300]}"
            )

        system_prompt = prompt.template_text.replace(
            '{project_name}', self.name or ''
        ).replace(
            '{project_description}', self.description or ''
        ).replace(
            '{project_domain}', self.domain_id.name if self.domain_id else 'Unknown'
        ).replace(
            '{kb_candidates}', "\n".join(kb_summaries)
        )

        try:
            response = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=f"Select the best Knowledge Bases for project: {self.name}",
                env=self.env,
                mode='json',
                schema=get_kb_selection_schema(),
                prompt_record=prompt,
            )

            if response:
                data = json.loads(response)
                selected_ids = data.get('selected_kb_ids', [])
                # Validate IDs exist in candidates
                valid_ids = [kid for kid in selected_ids if kid in candidates.ids]
                if valid_ids:
                    self.kb_ids = [(6, 0, valid_ids)]
                    _logger.info("KB selection for project %s: %s (reason: %s)",
                                 self.id, valid_ids, data.get('reasoning', ''))
                    return KB.browse(valid_ids)
        except Exception as e:
            _logger.warning("KB selection AI call failed for project %s: %s", self.id, e)

        # Fallback: use all candidates
        self.kb_ids = [(6, 0, candidates.ids)]
        return candidates

    def _build_kb_context(self, selected_kbs):
        """Build structured KB context for downstream prompts."""
        kb_context = {'source': 'Knowledge Base', 'knowledge_bases': []}
        for kb in selected_kbs:
            kb_data = {
                'name': kb.name,
                'domain': kb.domain_id.name if kb.domain_id else 'General',
                'sections': []
            }
            for section in kb.section_ids.sorted('sequence'):
                sec_data = {
                    'title': section.title,
                    'type': section.section_type,
                    'description': section.description or '',
                }
                if section.key_topics:
                    try:
                        sec_data['key_topics'] = json.loads(section.key_topics)
                    except json.JSONDecodeError:
                        pass
                kb_data['sections'].append(sec_data)
            kb_context['knowledge_bases'].append(kb_data)
        return kb_context

    def _run_initial_research(self):
        self.ensure_one()

        # 1. Smart Knowledge Base Selection
        selected_kbs = self._select_knowledge_bases()

        if selected_kbs:
            # Build structured KB context (JSON)
            kb_context = self._build_kb_context(selected_kbs)
            self.initial_research = f"Source: Knowledge Base\n\n{json.dumps(kb_context, indent=2)}"

            # Log KB selection in chatter
            kb_names = ", ".join([f"<b>{kb.name}</b> ({kb.section_count} sections)" for kb in selected_kbs])
            self.message_post(
                body=Markup(
                    "Knowledge Base selected for this project: %s. "
                    "KB content will be used to guide TOC structure, section writing, and practices gap analysis."
                ) % Markup(kb_names),
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
            return

        # No KB found — log and fall back
        self.message_post(
            body="No active Knowledge Base found matching this project's domain. "
                 "Falling back to Google Search for initial research.",
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )

        # 2. Fallback: Google Search
        try:
            from google.genai import types
            search_tool = [types.Tool(google_search=types.GoogleSearch())]
        except ImportError:
            search_tool = None

        prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_RESEARCH_INITIAL)], limit=1)
        if not prompt_record:
            return

        system_prompt = prompt_record.template_text.format(domain=self.domain_id.name, project_name=self.name)

        response_text = self.env['rfp.ai.log'].execute_request(
            system_prompt=system_prompt,
            user_context=f"Project Description: {self.description}",
            env=self.env,
            mode='text',
            tools=search_tool,
            prompt_record=prompt_record
        )
        self.initial_research = response_text

    def _run_scope_assessment(self):
        """
        Run ONCE before the first interview round.
        Analyzes budget + company size + project complexity to determine
        dynamic round limits (warn_round, max_round).
        Stores results in ai_context_blob under 'scope_assessment'.
        """
        self.ensure_one()
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_scope_assessment_schema

        # Guard: Only run once
        blob = self.get_context_data()
        if blob.get('scope_assessment'):
            return

        # Gather init field values
        init_inputs = {inp.field_key: inp.user_value for inp in self.form_input_ids if inp.user_value}

        prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_SCOPE_ASSESSOR)], limit=1)
        if not prompt_record:
            _logger.warning("Scope assessor prompt not found. Using default limits.")
            blob['scope_assessment'] = {
                'complexity_rating': 'medium',
                'reasoning': 'Default limits (prompt not found).',
                'warn_round': 15,
                'max_round': 25,
            }
            self.ai_context_blob = json.dumps(blob, indent=4)
            return

        system_prompt = prompt_record.template_text.format(
            project_name=self.name,
            description=self.description,
            domain=self.domain_id.name or 'General',
            budget_range=init_inputs.get('budget_range', 'Unknown'),
            project_type=init_inputs.get('project_type', 'Unknown'),
            target_audience=init_inputs.get('target_audience', 'Unknown'),
            primary_goal=init_inputs.get('primary_goal', 'Unknown'),
            initial_research_summary=(self.initial_research or 'No research available.')[:2000],
        )

        user_context = f"Project: {self.name}\nAssess the interview depth required."

        try:
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=user_context,
                env=self.env,
                mode='json',
                schema=get_scope_assessment_schema(),
                prompt_record=prompt_record
            )
        except Exception as e:
            _logger.warning(f"Scope assessment AI call failed: {e}. Using defaults.")
            blob['scope_assessment'] = {
                'complexity_rating': 'medium',
                'reasoning': f'Default limits (AI call failed).',
                'warn_round': 15,
                'max_round': 25,
            }
            self.ai_context_blob = json.dumps(blob, indent=4)
            return

        if not response_json_str:
            blob['scope_assessment'] = {
                'complexity_rating': 'medium',
                'reasoning': 'Default limits (empty AI response).',
                'warn_round': 15,
                'max_round': 25,
            }
            self.ai_context_blob = json.dumps(blob, indent=4)
            return

        try:
            assessment = json.loads(response_json_str)
        except json.JSONDecodeError:
            assessment = {
                'complexity_rating': 'medium',
                'reasoning': 'Default limits (invalid JSON).',
                'warn_round': 15,
                'max_round': 25,
            }

        # Validate and enforce constraints
        warn_round = assessment.get('warn_round', 15)
        max_round = assessment.get('max_round', 25)
        warn_round = max(5, min(warn_round, 30))
        max_round = max(warn_round + 4, min(max_round, 40))

        assessment['warn_round'] = warn_round
        assessment['max_round'] = max_round

        blob['scope_assessment'] = assessment
        self.ai_context_blob = json.dumps(blob, indent=4)
        _logger.info(
            f"Scope assessment for project {self.id}: "
            f"complexity={assessment.get('complexity_rating')}, "
            f"warn={warn_round}, max={max_round}"
        )

    def _get_round_limits(self):
        """Retrieve dynamic round limits from ai_context_blob."""
        self.ensure_one()
        blob = self.get_context_data()
        assessment = blob.get('scope_assessment', {})
        return {
            'warn_round': assessment.get('warn_round', 15),
            'max_round': assessment.get('max_round', 25),
        }

    def action_refine_practices(self):
        """
        Phase 4: Refinement
        """
        for project in self:
             # Gather Q&A context
            qa_list = []
            for inp in project.form_input_ids:
                if inp.user_value:
                    qa_list.append(f"- {inp.label}: {inp.user_value}")
            qa_context = "\n".join(qa_list)

            try:
                from google.genai import types
                search_tool = [types.Tool(google_search=types.GoogleSearch())]
            except ImportError:
                search_tool = None 
            
            prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_RESEARCH_REFINEMENT)], limit=1)
            if not prompt_record:
                 system_prompt = "Refine the best practices based on user answers."
            else:
                 system_prompt = prompt_record.template_text

            final_context = f"Initial Research:\n{project.initial_research}\n\nUser Answers:\n{qa_context}"

            response_text = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=final_context,
                env=self.env,
                mode='text',
                tools=search_tool,
                prompt_record=prompt_record
            )
            
            project.refined_practices = response_text
        project.current_stage = STAGE_PRACTICES_REFINED

    def _execute_interview_round(self, prompt_code, input_model_name, context_data, scope_key='project'):
        """
        Generic Driver for Information Gathering Rounds.
        Args:
            scope_key (str): Key to separate analysis metadata (completeness) per phase.
        """
        self.ensure_one()
        project = self
        import json
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_interviewer_schema

        # 1. Call AI
        prompt_record = self.env['rfp.prompt'].search([('code', '=', prompt_code)], limit=1)
        if not prompt_record:
            raise ValueError(f"System Prompt '{prompt_code}' not found.")
        
        # Inject Round Count and Dynamic Limits
        limits = self._get_round_limits()
        prompt_template = prompt_record.template_text
        prompt_template = prompt_template.replace("{{round_count}}", str(context_data.get('current_round', 1)))
        prompt_template = prompt_template.replace("{{warn_round}}", str(limits['warn_round']))
        prompt_template = prompt_template.replace("{{max_round}}", str(limits['max_round']))
        context_str = json.dumps(context_data, indent=2)
        
        try:
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=prompt_template,
                user_context=context_str,
                env=self.env,
                mode='json',
                schema=get_interviewer_schema(),
                prompt_record=prompt_record
            )
        except Exception as e:
             # Basic Error Fallback
             return True # Keep stage open on error to retry? Or move on? usually retry.

        if not response_json_str:
            return True

        try:
            response_data = json.loads(response_json_str)
        except json.JSONDecodeError:
            return True

        # Update Metadata with Scoping
        blob = project.get_context_data()
        scoped_meta_key = f"analysis_meta_{scope_key}"
        
        # Monotonize Score
        old_score = blob.get(scoped_meta_key, {}).get('completeness_score', 0)
        new_meta = response_data.get('analysis_meta', {})
        new_score = new_meta.get('completeness_score', 0)
        
        if new_score < old_score:
            new_meta['completeness_score'] = old_score
            
        # Save Scoped Meta
        blob[scoped_meta_key] = new_meta
        
        # Save Global Analysis Meta (For backward compatibility with Portal UI which reads 'analysis_meta')
        # We overwrite the global key with the CURRENT phase's meta so UI shows correct progress.
        blob['analysis_meta'] = new_meta
        
        if 'last_input_context' not in response_data:
             response_data['last_input_context'] = context_data
             
        # Save Blob
        project.ai_context_blob = json.dumps(blob, indent=4)

        # Status Check
        status = new_meta.get('status')
        if status in [AI_STATUS_RATE_LIMIT, AI_STATUS_ERROR]:
            return True
                
        # Auto-Finalization
        is_complete = response_data.get('is_gathering_complete', False)
        if is_complete:
            return False # Completed

        # Process new questions
        new_fields = response_data.get('form_fields', [])
        
        # Calc Round Number
        current_input_count = self.env[input_model_name].search_count([('project_id', '=', project.id)])
        current_round_number = (current_input_count // 5) + 1
        
        batch_keys = set()
        new_inputs = []
        existing_inputs = self.env[input_model_name].search([('project_id', '=', project.id)])
        existing_keys = existing_inputs.mapped('field_key')

        for field in new_fields:
            key = field.get('field_key') or field.get('field_name')
            if key and key not in existing_keys and key not in batch_keys:
                batch_keys.add(key)
                vals = {
                    'project_id': project.id,
                    'field_key': key,
                    'label': field.get('label'),
                    'component_type': field.get('field_type') or field.get('component_type', 'text_input'),
                    'data_type': field.get('data_type_validation', 'string'),
                    'options': json.dumps(field.get('options', [])),
                    'description_tooltip': field.get('description') or field.get('description_tooltip'),
                    'question_rationale': field.get('question_rationale'),
                    'round_number': current_round_number,
                    'suggested_answers': json.dumps(field.get('suggested_answers', [])),
                    'depends_on': json.dumps(field.get('depends_on', {})),
                    'specify_triggers': json.dumps(field.get('specify_triggers', [])),
                }
                new_inputs.append(vals)
        
        if new_inputs:
            self.env[input_model_name].create(new_inputs)
            return True 
        else:
            return False

    def action_analyze_gap(self):
        """
        Phase 3: Information Gathering (Project Specifics)
        """
        for project in self:
            # Run scope assessment ONCE (before first interview round)
            project._run_scope_assessment()

            # Context Building
            previous_inputs = []
            for inp in project.form_input_ids.sorted('id'):
                if inp.user_value:
                    previous_inputs.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})
                elif inp.is_irrelevant:
                     previous_inputs.append({"reason": f"[REJECTED] {inp.irrelevant_reason}"})

            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "initial_best_practices": project.initial_research or "No research found.",
                "previous_inputs": previous_inputs,
                "current_round": (len(previous_inputs) // 4) + 1
            }

            # Include source document text to avoid redundant questions
            if project.source_extracted_text:
                context_data["source_document_excerpt"] = project.source_extracted_text[:5000]

            is_ongoing = project._execute_interview_round(PROMPT_INTERVIEWER_PROJECT, 'rfp.form.input', context_data, scope_key='project')
            
            if not is_ongoing:
                project.current_stage = STAGE_INFO_GATHERED
            return is_ongoing

    def action_check_specifications(self):
        """
        Phase 4b: Post-Analysis Custom Fields Check
        """
        for project in self:
            # 1. Find Post-Gathering Custom Fields
            post_fields = self.env['rfp.custom.field'].search([('phase', '=', 'post_gathering')])
            if not post_fields:
                project.current_stage = STAGE_SPECIFICATIONS_GATHERED # Skip
                return False
            
            # 2. Check if they exist as Practice Inputs (or Form Inputs?)
            # Plan said "Practice Input" or "Form Input". Since it's post-analysis, Practice Inputs is cleaner
            # as it separates from formatting/basics.
            new_inputs = []
            for cf in post_fields:
                existing = project.practice_input_ids.filtered(lambda i: i.field_key == cf.code)
                if not existing:
                     new_inputs.append({
                        'project_id': project.id,
                        'field_key': cf.code,
                        'label': cf.name,
                        'component_type': cf.input_type,
                        'suggested_answers': json.dumps(cf.suggestion_ids.mapped('name')),
                        'options': json.dumps([{'value': o.value, 'label': o.label} for o in cf.option_ids]),
                        'sequence': cf.sequence,
                        'specify_triggers': cf.specify_triggers or '[]'
                    })
            
            if new_inputs:
                self.env['rfp.practice.input'].create(new_inputs)
                
            project.current_stage = STAGE_SPECIFICATIONS_GATHERED
            return True # Require Interaction

    def action_analyze_practices_gap(self):
        """
        Phase 5: Best Practices Gathering
        """
        for project in self:
            # Gather Previous Inputs
            previous_inputs_context = []
            for inp in project.form_input_ids:
                 if inp.user_value:
                    previous_inputs_context.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})

            practice_inputs = []
            for inp in project.practice_input_ids.sorted('id'):
                if inp.user_value:
                    practice_inputs.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})
                elif inp.is_irrelevant:
                     practice_inputs.append({"reason": f"[REJECTED] {inp.irrelevant_reason}"})

            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "refined_best_practices": project.refined_practices or "No refined practices info.",
                "previous_inputs": previous_inputs_context,
                "practice_inputs": practice_inputs,
                "current_round": (len(practice_inputs) // 4) + 1
            }

            # Include source document text to avoid redundant questions
            if project.source_extracted_text:
                context_data["source_document_excerpt"] = project.source_extracted_text[:5000]

            # Include KB compliance checklist if KBs are selected
            if project.kb_ids:
                kb_checklist = []
                for kb in project.kb_ids:
                    for section in kb.section_ids.sorted('sequence'):
                        topics = []
                        if section.key_topics:
                            try:
                                topics = json.loads(section.key_topics)
                            except json.JSONDecodeError:
                                pass
                        kb_checklist.append({
                            'topic': section.title,
                            'type': section.section_type,
                            'required_coverage': topics,
                        })
                context_data['kb_compliance_checklist'] = kb_checklist

            # Scope Key = 'practices'
            is_ongoing = project._execute_interview_round(PROMPT_INTERVIEWER_PRACTICES, 'rfp.practice.input', context_data, scope_key='practices')
            
            if not is_ongoing:
                project.current_stage = STAGE_PRACTICES_GAP_GATHERED
            return is_ongoing

    def action_proceed_next_stage(self):
        """
        Automated Transition Handler.
        Called by Portal when stage is non-interactive but requires backend processing.
        """
        self.ensure_one()
        if self.current_stage == STAGE_INFO_GATHERED:
            self.action_refine_practices()
        elif self.current_stage == STAGE_PRACTICES_REFINED:
            self.action_check_specifications()
        elif self.current_stage == STAGE_PRACTICES_GAP_GATHERED:
            self.action_generate_structure()
        return True

    def action_generate_structure(self):
        """
        Phase 1: The Architect (Generate TOC)
        """
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_toc_structure_schema

        for project in self:
            # 1. Context Building
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "refined_best_practices": project.refined_practices or project.initial_research,
                "q_and_a": []
            }
            for inp in project.form_input_ids:
                if inp.user_value:
                    context_data["q_and_a"].append(f"- **{inp.label}**: {inp.user_value}")
            
            context_str = "\n".join(context_data["q_and_a"])

            # Inject KB reference structures for TOC guidance
            kb_reference_str = ""
            if project.kb_ids:
                kb_ref_parts = []
                for kb in project.kb_ids:
                    sections = kb.section_ids.sorted('sequence')
                    if sections:
                        sec_list = "\n".join([
                            f"  - {s.title} [{s.section_type}]" for s in sections
                        ])
                        kb_ref_parts.append(f"KB: {kb.name}\n{sec_list}")
                if kb_ref_parts:
                    kb_reference_str = (
                        "\n\n**Knowledge Base Reference Structures:**\n"
                        "Use these proven section structures as a TEMPLATE for your TOC. "
                        "Adapt to this project's needs but follow the proven ordering and coverage.\n\n"
                        + "\n\n".join(kb_ref_parts)
                    )

            # Clear existing logic
            project.document_section_ids.unlink()

            prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_WRITER_TOC_ARCHITECT)], limit=1)
            if not prompt_record:
                raise ValueError(f"System Prompt '{PROMPT_WRITER_TOC_ARCHITECT}' not found.")

            architect_prompt = prompt_record.template_text.format(
                 project_name=project.name,
                 domain=project.domain_id.name or 'General',
                 context_str=context_str
            )
            
            try:
                toc_json_str = self.env['rfp.ai.log'].execute_request(
                    system_prompt=architect_prompt,
                    user_context=context_str + kb_reference_str,
                    env=self.env,
                    mode='json',
                    schema=get_toc_structure_schema(),
                    prompt_record=prompt_record
                )
            except Exception:
                toc_json_str = "{}"
            
            try:
                toc_data = json.loads(toc_json_str)
            except json.JSONDecodeError:
                toc_data = {}

            # Save TOC
            current_blob = project.get_context_data()
            current_blob['toc_structure'] = toc_data
            project.ai_context_blob = json.dumps(current_blob, indent=4)
            
            # Create Sections
            sequence = 10
            for section in toc_data.get('table_of_contents', []):
                self.env['rfp.document.section'].create({
                    'project_id': project.id,
                    'section_title': section.get('title'),
                    'sequence': sequence
                })
                sequence += 10
                
                for sub in section.get('subsections', []):
                    self.env['rfp.document.section'].create({
                        'project_id': project.id,
                        'section_title': sub.get('title'),
                        'sequence': sequence
                    })
                    sequence += 10

            project.current_stage = STAGE_SECTIONS_GENERATED
            return True

    def action_generate_content(self):
        """
        Phase 2: The Writer
        """
        for project in self:
            project.current_stage = STAGE_GENERATING_CONTENT
            
             # 1. Context Building
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "q_and_a": []
            }
            for inp in project.form_input_ids:
                if inp.user_value:
                    context_data["q_and_a"].append(f"- **{inp.label}**: {inp.user_value}")

            context_str = "\n".join(context_data["q_and_a"])

            # Retrieve TOC Structure for context
            current_blob = project.get_context_data()
            toc_data = current_blob.get('toc_structure', {})
            toc_context_str = json.dumps(toc_data.get('table_of_contents', []), indent=2)

            section_writer_template = self.env['rfp.prompt'].search([('code', '=', PROMPT_WRITER_SECTION)], limit=1).template_text

            # Build KB reference for section writers
            kb_sections_ref = []
            if project.kb_ids:
                for kb in project.kb_ids:
                    for kb_sec in kb.section_ids.sorted('sequence'):
                        if kb_sec.description:
                            kb_sections_ref.append({
                                'kb_name': kb.name,
                                'section_title': kb_sec.title,
                                'section_type': kb_sec.section_type,
                                'best_practices': kb_sec.description,
                            })

            kb_reference_text = ""
            if kb_sections_ref:
                kb_reference_text = (
                    "\n\n**Knowledge Base Reference (Best Practices):**\n"
                    "Use the following reference material to ensure your content "
                    "follows established best practices and industry standards.\n\n"
                    + json.dumps(kb_sections_ref, indent=2)
                )

            for section_record in project.document_section_ids:
                if section_record.content_html:
                    continue

                section_title = section_record.section_title
                section_intent = "Write comprehensive details matching the project context."

                writer_prompt = section_writer_template.format(
                    project_name=project.name,
                    domain=project.domain_id.name or 'General',
                    toc_context=toc_context_str,
                    section_title=section_title,
                    section_intent=section_intent,
                    context_str=context_str
                )

                user_context = f"Project Context:\n{context_str}\n\nPlease write the {section_title} section now.{kb_reference_text}"
                
                job = section_record.with_delay(channel='root.rfp_generation').generate_content_job(
                    system_prompt=writer_prompt,
                    user_context=user_context
                )
                
                if job and hasattr(job, 'db_record'):
                    section_record.job_id = job.db_record()
                
                section_record.generation_status = STATUS_QUEUED
                
            return True
    
    def action_check_generation_status(self):
        """ Check completion """
        for project in self:
            # 1. Immediate Transitions (Start Chains)
            if project.current_stage == STAGE_SECTIONS_GENERATED:
                 # Structure is ready, start generating content immediately
                 project.action_generate_content()
                 return True

            # 2. Check Status of Running Jobs
            status_data = project.get_generation_status()
            
            # Auto-Advance Logic
            if status_data['status'] == 'completed':
                if project.current_stage == STAGE_GENERATING_CONTENT:
                     project.current_stage = STAGE_CONTENT_GENERATED
                     # Auto-Trigger Images
                     project.action_generate_diagram_images()
                     
                elif project.current_stage == STAGE_GENERATING_IMAGES:
                     project.current_stage = STAGE_IMAGES_GENERATED
                
                return True
        return False
        
    def action_lock_document(self):
        self.current_stage = STAGE_DOCUMENT_LOCKED
        return True

    def action_generate_diagram_images(self):
        """
        Phase 8: Image Generation (Imagen) 
        Now using Queue Jobs (Async)
        """
        for project in self:
            project.current_stage = STAGE_GENERATING_IMAGES
            
            # Find diagrams needing images
            diagrams = self.env['rfp.section.diagram'].search([
                ('section_id.project_id', '=', project.id),
                ('image_file', '=', False)
            ])
            
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'image_generator')], limit=1)
            prompt_id = prompt_record.id if prompt_record else None
            
            for diagram in diagrams:
                # Dispatch Job
                job = diagram.with_delay(channel='root.rfp_generation').generate_image_job(prompt_record_id=prompt_id)
                if job and hasattr(job, 'db_record'):
                    diagram.job_id = job.db_record()
                
            return True

    def action_mark_completed(self):
        for project in self:
            project.current_stage = 'completed'

    # ========== EVALUATION CRITERIA METHODS ==========

    def action_gather_eval_criteria(self):
        """AI interview loop to gather evaluation priorities from the user."""
        self.ensure_one()
        import json

        # Build context for the eval criteria interviewer
        previous_eval_inputs = []
        for inp in self.eval_input_ids.filtered(lambda i: i.user_value):
            previous_eval_inputs.append({
                'question': inp.label,
                'answer': inp.user_value,
            })

        section_titles = [s.section_title for s in self.document_section_ids] if self.document_section_ids else []

        current_input_count = len(self.eval_input_ids)
        current_round = (current_input_count // 5) + 1

        context_data = {
            'project_name': self.name,
            'description': self.description,
            'domain': self.domain_id.name if self.domain_id else 'General',
            'section_titles': json.dumps(section_titles),
            'previous_eval_inputs': json.dumps(previous_eval_inputs, indent=2),
            'current_round': current_round,
        }

        is_ongoing = self._execute_interview_round(
            PROMPT_INTERVIEWER_EVAL_CRITERIA,
            'rfp.eval.input',
            context_data,
            scope_key='eval_criteria'
        )

        if not is_ongoing:
            # Interview complete — generate criteria from answers
            self._generate_eval_criteria()
            self.eval_criteria_status = 'generated'
        else:
            self.eval_criteria_status = 'gathering'

        return is_ongoing

    def _generate_eval_criteria(self):
        """After eval interview completes, call AI to generate structured criteria."""
        self.ensure_one()
        import json
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_eval_criteria_schema

        # Collect all eval inputs with answers
        eval_qa = []
        for inp in self.eval_input_ids.filtered(lambda i: i.user_value and not i.is_irrelevant):
            eval_qa.append({'question': inp.label, 'answer': inp.user_value})

        section_titles = [s.section_title for s in self.document_section_ids] if self.document_section_ids else []

        context_data = {
            'project_name': self.name,
            'domain': self.domain_id.name if self.domain_id else 'General',
            'description': self.description,
            'eval_interview_answers': json.dumps(eval_qa, indent=2),
            'section_titles': json.dumps(section_titles),
        }

        prompt_record = self.env['rfp.prompt'].search([('code', '=', PROMPT_GENERATE_EVAL_CRITERIA)], limit=1)
        if not prompt_record:
            raise ValidationError(f"Prompt '{PROMPT_GENERATE_EVAL_CRITERIA}' not found.")

        try:
            response_json_str = self.env['rfp.ai.log'].execute_request(
                system_prompt=prompt_record.template_text,
                user_context=json.dumps(context_data, indent=2),
                env=self.env,
                mode='json',
                schema=get_eval_criteria_schema(),
                prompt_record=prompt_record
            )
        except Exception as e:
            raise ValidationError(f"AI criteria generation failed: {str(e)}")

        if not response_json_str:
            raise ValidationError("AI returned no response for criteria generation.")

        try:
            data = json.loads(response_json_str)
        except json.JSONDecodeError:
            raise ValidationError("AI returned invalid JSON for criteria generation.")

        # Clear existing criteria and create new ones
        self.evaluation_criterion_ids.unlink()

        for idx, c in enumerate(data.get('criteria', [])):
            category = c.get('category', 'other')
            valid_categories = ['technical', 'commercial', 'experience', 'compliance', 'timeline', 'methodology', 'support', 'innovation', 'other']
            if category not in valid_categories:
                category = 'other'

            self.env['rfp.evaluation.criterion'].create({
                'project_id': self.id,
                'name': c.get('name', f'Criterion {idx + 1}'),
                'description': c.get('description', ''),
                'category': category,
                'weight': max(1, min(100, c.get('weight', 10))),
                'is_must_have': c.get('is_must_have', False),
                'scoring_guidance': c.get('scoring_guidance', ''),
                'sequence': (idx + 1) * 10,
            })

    def action_finalize_eval_criteria(self):
        """Called after user reviews/edits criteria. Marks as finalized."""
        self.ensure_one()
        self.eval_criteria_status = 'finalized'

    def get_context_data(self):
        """Helper to parse the context blob (Text) back into a Dict for views."""
        import json
        self.ensure_one()
        try:
            if not self.ai_context_blob:
                return {}
            return json.loads(self.ai_context_blob)
        except Exception:
            return {}

    def action_update_structure(self, sections_data):
        """
        Updates the document structure (Rename, Resequence, Add, Delete) based on portal input.
        Args:
            sections_data (list): List of dicts [{'id': int|str, 'section_title': str, 'sequence': int}]
        Returns:
            dict: Mapping of temp IDs (str like 'new_123') to real section IDs (int).
        """
        self.ensure_one()
        current_ids = self.document_section_ids.ids
        incoming_ids = []
        id_map = {}  # Temp ID -> Real ID

        for data in sections_data:
            section_id = data.get('id')
            title = data.get('section_title')
            sequence = int(data.get('sequence', 10))

            if isinstance(section_id, int) and section_id in current_ids:
                # Update existing
                section = self.env['rfp.document.section'].browse(section_id)
                section.write({
                    'section_title': title,
                    'sequence': sequence
                })
                incoming_ids.append(section_id)
            elif isinstance(section_id, str) and section_id.startswith('new_'):
                # Create new
                new_section = self.env['rfp.document.section'].create({
                    'project_id': self.id,
                    'section_title': title,
                    'sequence': sequence,
                    'content_html': ''
                })
                incoming_ids.append(new_section.id)
                id_map[section_id] = new_section.id  # Map temp to real
        
        # Delete missing sections
        to_delete = list(set(current_ids) - set(incoming_ids))
        if to_delete:
            self.env['rfp.document.section'].browse(to_delete).unlink()
            
        return id_map

    def action_update_content_html(self, sections_content):
        """
        Updates the content of sections from portal review.
        Args:
            sections_content (dict): {str(section_id): str(html_content)}
        """
        self.ensure_one()
        for section_id_str, content in sections_content.items():
            if section_id_str.isdigit():
                section = self.env['rfp.document.section'].browse(int(section_id_str))
                if section.exists() and section.project_id == self:
                    section.content_html = content
        return True

    def get_generation_status(self):
        """
        Returns aggregate status of content generation jobs.
        """
        self.ensure_one()
        
        # Branch for Image Generation Phase
        # Branch for Image Generation Phase
        if self.current_stage == STAGE_GENERATING_IMAGES:
             # Count Diagram Jobs
             diagrams = self.env['rfp.section.diagram'].search([('section_id.project_id', '=', self.id)])
             total_diagrams = len(diagrams)
             
             if total_diagrams == 0:
                  return {'status': 'completed', 'progress': 100, 'completed': 0, 'total': 0}

             completed_diagrams = 0
             failed_diagrams = 0
             
             for d in diagrams:
                 if d.image_file:
                     completed_diagrams += 1
                 elif d.job_id: # Check job status
                     if d.job_id.state == 'done':
                         completed_diagrams += 1
                     elif d.job_id.state == 'failed':
                         failed_diagrams += 1
             
             progress = (completed_diagrams / total_diagrams) * 100 if total_diagrams > 0 else 0
             
             status = 'generating_images'
             if completed_diagrams == total_diagrams:
                 status = 'completed'
             elif failed_diagrams > 0 and (completed_diagrams + failed_diagrams == total_diagrams):
                 status = 'completed_with_errors' # Should we allow partial?
                 # If all done (success or fail), mark complete so user isn't stuck
                 status = 'completed' 
                 
             return {
                 'status': status, 
                 'progress': int(progress), 
                 'completed': completed_diagrams, 
                 'total': total_diagrams
             }
        
        total = len(self.document_section_ids)
        if total == 0:
            return {'status': 'completed', 'progress': 100}
        
        completed_count = 0
        failed_count = 0
        
        for section in self.document_section_ids:
            if section.job_id: # Check linked Job
                if section.job_id.state == 'done':
                    completed_count += 1
                elif section.job_id.state == 'failed':
                    failed_count += 1
            elif section.content_html:
                completed_count += 1
                
        progress = (completed_count / total) * 100 if total > 0 else 0
        
        status = 'generating'
        if completed_count == total:
            status = 'completed'
        elif failed_count > 0 and (completed_count + failed_count == total):
            status = 'completed_with_errors'
            
        return {'status': status, 'progress': int(progress), 'completed': completed_count, 'total': total}

    @api.depends('published_id', 'published_id.active')
    def _compute_is_published(self):
        for rec in self:
            rec.is_published = bool(rec.published_id and rec.published_id.active)

    def _compute_has_kb_entry(self):
        KB = self.env['rfp.knowledge.base']
        for rec in self:
            rec.has_kb_entry = bool(KB.search_count([
                ('source_project_id', '=', rec.id),
                ('source_type', '=', 'project'),
            ]))

    def _compute_kb_count(self):
        for rec in self:
            rec.kb_count = len(rec.kb_ids)

    def action_view_knowledge_bases(self):
        """Open the selected knowledge bases for this project."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Knowledge Bases — {self.name}',
            'res_model': 'rfp.knowledge.base',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.kb_ids.ids)],
        }

    def action_export_rfp(self):
        """Export the RFP for download (no public submission)."""
        self.ensure_one()

        if self.published_id:
            # Update existing export record
            self.published_id.copy_content_from_project()
            self.published_id.active = True
        else:
            # Create new export record
            published = self.env['rfp.published'].sudo().create({
                'project_id': self.id,
                'title': self.name,
                'description': self.description,
                'owner_id': self.user_id.id,
            })
            published.copy_content_from_project()
            self.published_id = published.id

        return self.published_id.get_public_url()

    def action_delete_export(self):
        """Delete the exported RFP."""
        self.ensure_one()
        if self.published_id:
            self.published_id.active = False
        return True

    def action_create_kb_from_project(self):
        """Create a Knowledge Base entry from this completed project's sections."""
        self.ensure_one()
        KnowledgeBase = self.env['rfp.knowledge.base']
        KbSection = self.env['rfp.kb.section']

        kb = KnowledgeBase.create({
            'name': f"KB: {self.name}",
            'domain_id': self.domain_id.id if self.domain_id else False,
            'source_type': 'project',
            'source_project_id': self.id,
            'state': 'analyzing',
        })

        # Pre-create sections from the project's document sections
        for section in self.document_section_ids.sorted('sequence'):
            KbSection.create({
                'kb_id': kb.id,
                'title': section.section_title,
                'section_type': 'functional',  # Will be classified by AI
                'sequence': section.sequence,
            })

        # Queue AI generalization job
        kb.with_delay(
            channel='root.rfp_generation',
            description=f"KB Generalization: {kb.name}"
        )._run_project_analysis_job()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rfp.knowledge.base',
            'res_id': kb.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_duplicate_for_adaptation(self, new_name=None):
        """
        Create a copy of this project for adaptation.
        Copies: interview answers, eval criteria, required docs, AI context.
        Clears: generated sections, published record, research, user_value on inputs.
        Resets stage to 'initialized' so user can review/modify answers.

        Note: Odoo 18 defaults One2many copy=False, so we must manually copy child records.
        """
        self.ensure_one()
        FormInput = self.env['rfp.form.input']
        PracticeInput = self.env['rfp.practice.input']
        EvalCriterion = self.env['rfp.evaluation.criterion']
        RequiredDoc = self.env['rfp.required.document']

        # Reset ai_context_blob: keep scope_assessment (interview limits), clear everything else
        old_blob = self.get_context_data() if self.ai_context_blob else {}
        new_blob = {}
        if 'scope_assessment' in old_blob:
            new_blob['scope_assessment'] = old_blob['scope_assessment']

        new_project = self.copy(default={
            'name': new_name or f"{self.name} - Copy",
            'current_stage': STAGE_INITIALIZED,
            'published_id': False,
            'initial_research': False,
            'refined_practices': False,
            'image_generation_progress': 0,
            'ai_context_blob': json.dumps(new_blob) if new_blob else '{}',
        })

        # Build source text from original project's answers for auto-fill
        source_parts = [f"Project: {self.name}", f"Description: {self.description}"]
        if self.domain_id:
            source_parts.append(f"Domain: {self.domain_id.name}")
        for inp in self.form_input_ids.filtered(lambda i: i.user_value):
            source_parts.append(f"Q: {inp.label}\nA: {inp.user_value}")
        for inp in self.practice_input_ids.filtered(lambda i: i.user_value):
            source_parts.append(f"Q: {inp.label}\nA: {inp.user_value}")
        new_project.source_extracted_text = "\n\n".join(source_parts)

        # Manually copy form_input_ids with cleared user_value
        for inp in self.form_input_ids:
            # Build suggested_answers: preserve original answer as a suggestion
            suggestions = []
            try:
                suggestions = json.loads(inp.suggested_answers) if inp.suggested_answers else []
            except Exception:
                suggestions = []
            if inp.user_value and inp.user_value not in suggestions:
                suggestions.insert(0, inp.user_value)

            FormInput.create({
                'project_id': new_project.id,
                'field_key': inp.field_key,
                'label': inp.label,
                'component_type': inp.component_type,
                'options': inp.options,
                'user_value': False,  # Cleared for re-interview
                'data_type': inp.data_type,
                'description_tooltip': inp.description_tooltip,
                'round_number': inp.round_number,
                'suggested_answers': json.dumps(suggestions) if suggestions else inp.suggested_answers,
                'depends_on': inp.depends_on,
                'is_irrelevant': False,
                'irrelevant_reason': False,
                'specify_triggers': inp.specify_triggers,
                'sequence': inp.sequence,
            })

        # Manually copy practice_input_ids with cleared user_value
        for inp in self.practice_input_ids:
            suggestions = []
            try:
                suggestions = json.loads(inp.suggested_answers) if inp.suggested_answers else []
            except Exception:
                suggestions = []
            if inp.user_value and inp.user_value not in suggestions:
                suggestions.insert(0, inp.user_value)

            PracticeInput.create({
                'project_id': new_project.id,
                'field_key': inp.field_key,
                'label': inp.label,
                'component_type': inp.component_type,
                'options': inp.options,
                'user_value': False,
                'data_type': inp.data_type,
                'description_tooltip': inp.description_tooltip,
                'round_number': inp.round_number,
                'suggested_answers': json.dumps(suggestions) if suggestions else inp.suggested_answers,
                'depends_on': inp.depends_on,
                'is_irrelevant': False,
                'irrelevant_reason': False,
                'specify_triggers': inp.specify_triggers,
                'sequence': inp.sequence,
            })

        # Copy evaluation criteria as-is
        for crit in self.evaluation_criterion_ids:
            crit.copy(default={'project_id': new_project.id})

        # Copy required documents as-is
        for doc in self.required_document_ids:
            doc.copy(default={'project_id': new_project.id})

        # Auto-fill from source text (original project's answers)
        new_project._auto_fill_from_source()

        _logger.info(f"Duplicated project {self.id} → new project {new_project.id} ({new_project.name}), "
                     f"copied {len(self.form_input_ids)} form inputs, {len(self.practice_input_ids)} practice inputs, "
                     f"{len(self.evaluation_criterion_ids)} eval criteria, {len(self.required_document_ids)} required docs")
        return new_project.id

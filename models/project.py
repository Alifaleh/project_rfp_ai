from odoo import models, fields, api
from odoo.exceptions import ValidationError
import json
import logging
import base64
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
        (STAGE_COMPLETED, 'Completed'),
    ], string="Current Stage", default=STAGE_DRAFT, tracking=False, group_expand='_expand_stages')

    image_generation_progress = fields.Integer(string="Image Gen Progress", default=0, help="Transient field for progress bar")

    active = fields.Boolean(default=True)

    form_input_ids = fields.One2many('rfp.form.input', 'project_id', string="Gathered Inputs")
    practice_input_ids = fields.One2many('rfp.practice.input', 'project_id', string="Practice Inputs")
    document_section_ids = fields.One2many('rfp.document.section', 'project_id', string="Generated Sections")

    # Research Fields
    initial_research = fields.Text(string="Initial Best Practices", readonly=True, help="Broad research before gathering.")
    refined_practices = fields.Text(string="Refined Best Practices", readonly=True, help="Specific research after gathering.")



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

    def _run_initial_research(self):
        self.ensure_one()
        
        # 1. Knowledge Base Check
        kb_records = self.env['rfp.knowledge.base'].search([
            ('domain_id', '=', self.domain_id.id),
            ('state', '=', 'active')
        ])
        
        if kb_records:
            # Use KB Material
            practices_text = "\n\n".join([kb.extracted_practices for kb in kb_records if kb.extracted_practices])
            self.initial_research = f"Source: Knowledge Base\n\n{practices_text}"
            return 

        # 2. Existing AI Search Logic (Fallback)
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
        
        # Inject Round Count
        prompt_template = prompt_record.template_text.replace("{{round_count}}", str(context_data.get('current_round', 1)))
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
                    user_context=context_str,
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

                user_context = f"Project Context:\n{context_str}\n\nPlease write the {section_title} section now."
                
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


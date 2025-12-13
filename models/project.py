from odoo import models, fields, api

class RfpProject(models.Model):
    _name = 'rfp.project'
    _description = 'RFP Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Project Name", required=True, tracking=True)
    description = fields.Text(string="Initial Idea", help="High-level description of the project idea", required=True, tracking=True)
    
    domain_id = fields.Many2one('rfp.project.domain', string="Domain Context", tracking=True)

    visibility_type = fields.Selection([('public', 'Public'), ('internal', 'Internal'), ('private', 'Private')], default='private')
    
    user_id = fields.Many2one('res.users', string="Project Owner", default=lambda self: self.env.user, tracking=True)
    
    ai_context_blob = fields.Text(string="AI Context Blob", default="{}")
    
    current_stage = fields.Selection([
        ('initialization', 'Initialization'),
        ('research_initial', 'Best Practices Research'),
        ('gathering', 'Information Gathering (Project)'),
        ('research_refinement', 'Best Practices Refinement'),
        ('gathering_practices', 'Information Gathering (Best Practices)'),
        ('structuring', 'Section Generation'),
        ('writing', 'Content Generation'),
        ('completed', 'Completed')
    ], string="Stage", default='initialization', tracking=True, group_expand='_expand_stages')

    form_input_ids = fields.One2many('rfp.form.input', 'project_id', string="Gathered Inputs")
    practice_input_ids = fields.One2many('rfp.practice.input', 'project_id', string="Practice Inputs")
    document_section_ids = fields.One2many('rfp.document.section', 'project_id', string="Generated Sections")

    # Research Fields
    initial_research = fields.Text(string="Initial Best Practices", readonly=True, help="Broad research before gathering.")
    refined_practices = fields.Text(string="Refined Best Practices", readonly=True, help="Specific research after gathering.")



    def action_initialize_project(self):
        """
        Phase 0: Project Initialization.
        Uses AI to:
        1. Select or Create a Domain.
        2. Refine the Project Description.
        """
        import json
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_domain_identification_schema

        for project in self:
            # 1. Gather Available Domains
            existing_domains = self.env['rfp.project.domain'].search([])
            domain_names = [d.name for d in existing_domains]
            available_domains_str = "\n".join([f"- {name}" for name in domain_names])
            
            # 2. Call AI
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'project_initializer')], limit=1)
            if not prompt_record:
                raise ValueError("System Prompt 'project_initializer' not found.")
            
            # Prepare Prompt
            system_prompt = prompt_record.template_text.format(
                project_name=project.name,
                description=project.description,
                available_domains_str=available_domains_str
            )
            
            # Call Log Execution
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
                # Log error and return (user sees error in chatter if tracking catches it, or UI error)
                raise models.ValidationError(f"AI Initialization Failed: {str(e)}")

            if not response_json_str:
                raise models.ValidationError("AI returned no response.")

            try:
                data = json.loads(response_json_str)
            except json.JSONDecodeError:
                raise models.ValidationError("AI returned invalid JSON.")
            
            # 3. Process Result
            suggested_domain = data.get('suggested_domain_name')
            refined_desc = data.get('refined_description')
            standard_reqs = data.get('standard_rfp_requirements', [])
            
            if not suggested_domain or not refined_desc:
                # Fallback if schema violated
                raise models.ValidationError("AI Response missing required fields.")
                
            # Domain Handing (Case Insensitive Match)
            # Normalize to lower for comparison
            match = next((d for d in existing_domains if d.name.lower() == suggested_domain.lower()), None)
            
            if match:
                project.domain_id = match.id
            else:
                # Create New Domain
                new_domain = self.env['rfp.project.domain'].create({'name': suggested_domain})
                project.domain_id = new_domain.id
                
            # Update Description
            project.description = refined_desc
            
            # Move Stage
            project.current_stage = 'research_initial'
            
            # NOTE: Research is now triggered explicitly by the controller to ensure ordering.
            # project.action_research_initial()

    def action_research_initial(self):
        """
        Phase 2: Initial Research (Text Mode + Search)
        """
        for project in self:
            print(f"DEBUG: Starting action_research_initial for {project.name}")
            try:
                from google.genai import types # type: ignore
                search_tool = [types.Tool(google_search=types.GoogleSearch())]
            except ImportError:
                search_tool = None 
            
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'research_initial')], limit=1)
            if not prompt_record:
                # Create default on fly if missing (for safety, though we should load via XML)
                # Or just raise error.
                system_prompt = "You are a Research Assistant. Search for best practices and standard RFP sections for: {domain}. Output a concise summary."
            else:
                 system_prompt = prompt_record.template_text.format(domain=project.domain_id.name, project_name=project.name)

            response_text = self.env['rfp.ai.log'].execute_request(
                system_prompt=system_prompt,
                user_context=f"Project Description: {project.description}",
                env=self.env,
                mode='text',
                tools=search_tool,
                prompt_record=prompt_record
            )
            
            print(f"DEBUG: Research output: {response_text[:100]}...")
            print(f"DEBUG: Research output: {response_text[:100]}...")
            project.initial_research = response_text
            project.current_stage = 'gathering'

    def action_refine_practices(self):
        """
        Phase 4: Refinement (Text Mode + Search)
        """
        for project in self:
             # Gather Q&A context
            qa_list = []
            for inp in project.form_input_ids:
                if inp.user_value:
                    qa_list.append(f"- {inp.label}: {inp.user_value}")
            qa_context = "\n".join(qa_list)

            try:
                from google.genai import types # type: ignore
                search_tool = [types.Tool(google_search=types.GoogleSearch())]
            except ImportError:
                search_tool = None 
            
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'research_refinement')], limit=1)
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
        project.current_stage = 'gathering_practices'

    def _execute_interview_round(self, prompt_code, input_model_name, context_data):
        """
        Generic Driver for Information Gathering Rounds.
        """
        self.ensure_one()
        project = self
        import json

        # 1. Call AI
        prompt_record = self.env['rfp.prompt'].search([('code', '=', prompt_code)], limit=1)
        if not prompt_record:
            raise ValueError(f"System Prompt '{prompt_code}' not found.")
        
        # Inject Round Count into Prompt Text
        prompt_template = prompt_record.template_text.replace("{{round_count}}", str(context_data.get('current_round', 1)))
        
        context_str = json.dumps(context_data, indent=2)
        
        from odoo.addons.project_rfp_ai.models.ai_schemas import get_interviewer_schema

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
            if "Rate Limit" in str(e):
                    response_json_str = json.dumps({
                    "analysis_meta": {"status": "rate_limit", "completeness_score": 0},
                    "research_notes": "High Traffic (Rate Limit). Please wait 30 seconds and retry.",
                    "form_fields": []
                })
            else: 
                    response_json_str = json.dumps({
                    "analysis_meta": {"status": "error", "completeness_score": 0},
                    "research_notes": f"Error: {str(e)}",
                    "form_fields": []
                })
        
        # 2. Parse JSON
        if not response_json_str:
            response_json_str = json.dumps({
                "analysis_meta": {"status": "error", "completeness_score": 0},
                "research_notes": "The AI service is temporarily unavailable (503).",
                "form_fields": []
            })

        try:
            response_data = json.loads(response_json_str)
        except json.JSONDecodeError:
            response_data = {}

        # Update Metadata
        if 'last_input_context' not in response_data:
             response_data['last_input_context'] = context_data

        # Monotonize Score
        current_context = project.get_context_data()
        old_score = current_context.get('analysis_meta', {}).get('completeness_score', 0)
        new_score = response_data.get('analysis_meta', {}).get('completeness_score', 0)
        if new_score < old_score:
            if 'analysis_meta' not in response_data:
                response_data['analysis_meta'] = {}
            response_data['analysis_meta']['completeness_score'] = old_score

        project.ai_context_blob = json.dumps(response_data, indent=4)

        # CRITICAL FIX: Check for Status (Rate Limit / Error)
        analysis_meta = response_data.get('analysis_meta', {})
        status = analysis_meta.get('status')
        if status in ['rate_limit', 'error']:
            return True
                
        # Check for Auto-Finalization
        is_complete = response_data.get('is_gathering_complete', False)
        if is_complete:
            return False # INDICATES COMPLETION TO CALLER

        # Process new questions
        new_fields = response_data.get('form_fields', [])
        
        # Simple way to increment round number
        try:
            current_input_count = self.env[input_model_name].search_count([('project_id', '=', project.id)])
            current_round_number = (current_input_count // 5) + 1
        except:
            current_round_number = 1
        
        # Track new keys in this batch to prevent duplicates
        batch_keys = set()
        new_inputs = []
        
        # Get existing keys for this specific model
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
            return True # INDICATES MORE QUESTIONS ADDED
        else:
            return False # INDICATES EMPTY BATCH (COMPLETED)

    def action_analyze_gap(self):
        """
        Phase 3: Project Information Gathering (Project Specifics)
        Uses _execute_interview_round with 'interviewer_project' prompt and 'rfp.form.input' model.
        """
        import json
        for project in self:
            # Context Building
            blob_context = json.loads(project.ai_context_blob or '{}')
            
            # Gather Previous Inputs (Project Specifics)
            previous_inputs = []
            # Ensure chronological order
            sorted_inputs = project.form_input_ids.sorted(key=lambda r: r.create_date or r.id)
            for inp in sorted_inputs:
                if inp.user_value:
                    previous_inputs.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})
                elif inp.is_irrelevant:
                     previous_inputs.append({"key": inp.field_key, "question": inp.label, "reason": f"[REJECTED] {inp.irrelevant_reason}"})

            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "initial_best_practices": project.initial_research or "No research found.", 
                "previous_inputs": previous_inputs,
                "rejected_topics": [], # TODO: Implement separate rejected list storage if needed
                "current_round": (len(previous_inputs) // 4) + 1
            }

            # Execute Round
            is_ongoing = project._execute_interview_round('interviewer_project', 'rfp.form.input', context_data)
            
            if not is_ongoing:
                # Phase Completed -> Move to Refinement
                project.current_stage = 'research_refinement'
            
            return True

    def action_analyze_practices_gap(self):
        """
        Phase 5: Best Practices Gathering (Gap Analysis)
        Uses _execute_interview_round with 'interviewer_practices' prompt and 'rfp.practice.input' model.
        """
        import json
        for project in self:
            # Context Building
            # Gather Previous Inputs (Project Specifics - Read Only Context)
            previous_inputs_context = []
            for inp in project.form_input_ids:
                 if inp.user_value:
                    previous_inputs_context.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})

            # Gather Current Phase Inputs (Practices)
            practice_inputs = []
            sorted_practices = project.practice_input_ids.sorted(key=lambda r: r.create_date or r.id)
            for inp in sorted_practices:
                if inp.user_value:
                    practice_inputs.append({"key": inp.field_key, "question": inp.label, "answer": inp.user_value})
                elif inp.is_irrelevant:
                     practice_inputs.append({"key": inp.field_key, "question": inp.label, "reason": f"[REJECTED] {inp.irrelevant_reason}"})

            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "refined_best_practices": project.refined_practices or "No refined practices key found.",
                "previous_inputs": previous_inputs_context, # Context from Phase 3
                "practice_inputs": practice_inputs,         # Active Context for Phase 5
                "current_round": (len(practice_inputs) // 4) + 1
            }

            # Execute Round
            is_ongoing = project._execute_interview_round('interviewer_practices', 'rfp.practice.input', context_data)
            
            if not is_ongoing:
                # Phase Completed -> Move to Structuring
                project.current_stage = 'structuring'
            
            return True

    def action_generate_structure(self):
        """
        Phase 1: The Architect (Generate TOC)
        Moves stage to 'structuring'.
        """
        import json
        
        for project in self:
            # 1. Context Building
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "refined_best_practices": project.refined_practices or project.initial_research or "No research.",
                "q_and_a": []
            }
            for inp in project.form_input_ids:
                if inp.user_value:
                    context_data["q_and_a"].append(f"- **{inp.label}**: {inp.user_value}")
                elif inp.is_irrelevant:
                     context_data["q_and_a"].append(f"- {inp.label}: [IRRELEVANT - {inp.irrelevant_reason}]")
            
            context_str = "\n".join(context_data["q_and_a"])

            # Clear existing sections to avoid duplicates on re-run
            project.document_section_ids.unlink()

            # --- PHASE 1: THE ARCHITECT (Generate TOC) ---
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'writer_toc_architect')], limit=1)
            if not prompt_record:
                raise ValueError("System Prompt 'writer_toc_architect' not found.")
            
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_toc_structure_schema

            architect_prompt = prompt_record.template_text.format(
                 project_name=project.name,
                 domain=project.domain_id.name or 'General',
                 context_str=context_str
            )
            
            # 2. Call AI (No Tools - relying on Refined Practices text)

            try:
                toc_json_str = self.env['rfp.ai.log'].execute_request(
                    system_prompt=architect_prompt,
                    user_context=context_str,
                    env=self.env,
                    mode='json',
                    schema=get_toc_structure_schema(),
                    prompt_record=prompt_record
                )
            except Exception as e:
                toc_json_str = json.dumps({"table_of_contents": [{"title": "Error Generating Structure", "subsections": []}]})
            
            try:
                toc_data = json.loads(toc_json_str)
            except json.JSONDecodeError:
                toc_data = {"table_of_contents": [{"title": "Executive Summary", "subsections": []}]}

            # Save TOC meta
            current_blob_str = project.ai_context_blob or "{}"
            try:
                current_blob = json.loads(current_blob_str)
            except:
                current_blob = {}
            
            current_blob['toc_structure'] = toc_data
            # current_blob['debug_architect_context'] = context_data
            project.ai_context_blob = json.dumps(current_blob, indent=4)
            
            # Create Empty Sections (Structure Only)
            sequence = 10
            for section in toc_data.get('table_of_contents', []):
                self.env['rfp.document.section'].create({
                    'project_id': project.id,
                    'section_title': section.get('title'),
                    'content_html': '', # Empty for now
                    'sequence': sequence
                })
                sequence += 10
                
                for sub in section.get('subsections', []):
                    self.env['rfp.document.section'].create({
                        'project_id': project.id,
                        'section_title': sub.get('title'),
                        'content_html': '', 
                        'sequence': sequence
                    })
                    sequence += 10

            project.current_stage = 'structuring'
            return True

    def action_generate_content(self):
        """
        Phase 2: The Writer (Generate Content for Sections)
        Moves stage to 'writing'.
        """
        import json
        import time

        for project in self:
            project.current_stage = 'writing' # Move immediately or after? User said "writing" stage.
            
            # Re-construct context (or retrieve from blob?)
            # Valid to rebuild context to ensure freshness
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
                elif inp.is_irrelevant:
                     context_data["q_and_a"].append(f"- {inp.label}: [IRRELEVANT - {inp.irrelevant_reason}]")
            
            context_str = "\n".join(context_data["q_and_a"])

            # Retrieve TOC Structure for context
            current_blob = project.get_context_data()
            toc_data = current_blob.get('toc_structure', {})
            toc_context_str = json.dumps(toc_data.get('table_of_contents', []), indent=2)

            section_writer_template = self.env['rfp.prompt'].search([('code', '=', 'writer_section_content')], limit=1).template_text

            # Iterate through existing sections
            for section_record in project.document_section_ids:
                if section_record.content_html:
                    continue # Skip if already written (allows resume)

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
                
                # Dispatch to Queue
                # We use the specific channel 'root.rfp_generation' to control concurrency
                job = section_record.with_delay(channel='root.rfp_generation').generate_content_job(
                    system_prompt=writer_prompt,
                    user_context=user_context
                )
                
                # Check if job is a Job object (from queue_job python lib) and get the recordset
                # The .with_delay() returns a Job object, which has a db_record() method to get the Odoo record
                if job and hasattr(job, 'db_record'):
                    section_record.job_id = job.db_record()
                
                section_record.generation_status = 'queued'
                
            project.current_stage = 'writing'
            return True

    def action_mark_completed(self):
        for project in self:
            project.current_stage = 'completed'

    # Deprecated / Legacy Support
    def action_generate_document(self):
        self.action_generate_structure()
        self.action_generate_content()
        self.action_mark_completed()

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
        """
        self.ensure_one()
        current_ids = self.document_section_ids.ids
        incoming_ids = []

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
        
        # Delete missing sections
        to_delete = list(set(current_ids) - set(incoming_ids))
        if to_delete:
            self.env['rfp.document.section'].browse(to_delete).unlink()
            
        return True

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


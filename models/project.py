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
        ('gathering', 'Information Gathering'),
        ('research_refinement', 'Best Practices Refinement'),
        ('structuring', 'Section Generation'),
        ('writing', 'Content Generation'),
        ('completed', 'Completed')
    ], string="Stage", default='initialization', tracking=True, group_expand='_expand_stages')

    form_input_ids = fields.One2many('rfp.form.input', 'project_id', string="Gathered Inputs")
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
            project.current_stage = 'structuring'

    def action_analyze_gap(self):
        """
        Main Engine:
        1. Gather Context.
        2. Call AI.
        3. Parse JSON.
        4. Generate Questions.
        """
        import json

        for project in self:
            # 1. Gather Context
            blob_context = json.loads(project.ai_context_blob or '{}')
            standard_requirements = blob_context.get('standard_requirements', [])

            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_id.name or 'General',
                "initial_best_practices": project.initial_research or "No research found.", 
                "refined_best_practices": project.refined_practices, # Added for context if available
                "previous_inputs": [],
                "rejected_topics": []
            }
            
            # Ensure chronological order for Recency Bias
            sorted_inputs = project.form_input_ids.sorted(key=lambda r: r.create_date or r.id)
            
            for form_input in sorted_inputs:
                if form_input.is_irrelevant:
                    context_data["rejected_topics"].append({
                        "key": form_input.field_key,
                        "question": form_input.label,
                        "reason": f"[REJECTED] {form_input.irrelevant_reason or 'No reason provided'}"
                    })
                elif form_input.user_value:
                    context_data["previous_inputs"].append({
                        "key": form_input.field_key,
                        "question": form_input.label,
                        "answer": form_input.user_value
                    })
            
            # Calculate Round Count (Approx 4 questions per round)
            question_count = len(context_data["previous_inputs"])
            round_count = (question_count // 4) + 1
            context_data["current_round"] = round_count

            context_str = json.dumps(context_data, indent=2)
            
            # 2. Call AI with Logging
            prompt_record = self.env['rfp.prompt'].search([('code', '=', 'interviewer_main')], limit=1)
            if not prompt_record:
                raise ValueError("System Prompt 'interviewer_main' not found.")
            
            # Inject Round Count into Prompt Text
            prompt_template = prompt_record.template_text.replace("{{round_count}}", str(round_count))
            if not prompt_template:
                raise ValueError("System Prompt 'interviewer_main' not found.")
            
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_interviewer_schema

            # We use the new Logging Model wrapper
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
                # If rate limit or other error raised by log model, we handle it here or let it propagate.
                # The Log model raises RateLimitError again so we can catch it.
                # However, our old logic handled Rate Limit by returning a custom JSON.
                # We need to adapt.
                # If execute_request raises RateLimitError, we should catch it and return the "Rate Limit" JSON structure
                # so the frontend can show the warning.
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
            
            # 3. Parse JSON
            if not response_json_str:
                response_json_str = json.dumps({
                    "analysis_meta": {"status": "error", "completeness_score": 0},
                    "research_notes": "The AI service is temporarily unavailable (503). Please try again in a few moments.",
                    "form_fields": []
                })

            try:
                response_data = json.loads(response_json_str)
            except json.JSONDecodeError:
                # Fallback or Error handling
                response_data = {}

            # Update Metdata (Explicit Write as Text)
            # Inject Debug Context
            response_data['last_input_context'] = context_data

            # FIX: Ensure monotonization of completeness_score (Don't let it drop)
            current_context = project.get_context_data()
            old_score = current_context.get('analysis_meta', {}).get('completeness_score', 0)
            new_score = response_data.get('analysis_meta', {}).get('completeness_score', 0)
            
            # If new score is lower, keep the old one to avoid confusion
            if new_score < old_score:
                if 'analysis_meta' not in response_data:
                    response_data['analysis_meta'] = {}
                response_data['analysis_meta']['completeness_score'] = old_score

            project.ai_context_blob = json.dumps(response_data, indent=4)
            
            # 4. Generate Questions
            form_fields = response_data.get('form_fields', [])
            
            # Only create fields that don't exist yet? 
            # Or assume the AI gives us the NEXT set of questions.
            # For this MVP, we append new questions.
            
            # Check existing keys to avoid duplicates in this round?
            existing_keys = project.form_input_ids.mapped('field_key')
            if not response_data:
                return

            # CRITICAL FIX: Check for Status (Rate Limit / Error)
            # If status is not 'success' (or implicit success), do NOT process fields and do NOT finalize.
            analysis_meta = response_data.get('analysis_meta', {})
            status = analysis_meta.get('status')
            if status in ['rate_limit', 'error']:
                # Do nothing, just return. The context blob is already updated with this status,
                # so the UI will show the warning. We must NOT advance stage.
                return True
                
            # Check for Auto-Finalization
            is_complete = response_data.get('is_gathering_complete', False)
            if is_complete:
                # CHECK FOR POST-GATHERING FIELDS
                post_fields = self.env['rfp.custom.field'].search([('phase', '=', 'post_gathering'), ('active', '=', True)])
                post_inputs_created = False
                
                for pf in post_fields:
                    # Check if already exists
                    if not self.env['rfp.form.input'].search_count([('project_id', '=', project.id), ('field_key', '=', pf.code)]):
                        # Serialize relational options field to JSON for form_input
                        opts_json = "[]"
                        if pf.option_ids:
                            # form_input options are usually just strings, but let's see logic.
                            # Standard form input options are ["Yes", "No"].
                            # field.option uses {label, value}.
                            # If we pass just a list of strings, it works for simple selects.
                            # Let's map it to [opt.label for opt in pf.option_ids]
                            opts_list = [opt.label for opt in pf.option_ids]
                            opts_json = json.dumps(opts_list)

                        self.env['rfp.form.input'].create({
                            'project_id': project.id,
                            'field_key': pf.code,
                            'label': pf.name,
                            'component_type': 'multiselect' if pf.input_type == 'checkboxes' else pf.input_type,
                            'options': opts_json,
                            'description_tooltip': pf.help_text,
                            'round_number': 99, # High number to indicate post-phase
                        })
                        post_inputs_created = True
                
                if post_inputs_created:
                    # If we added fields, we are NOT done. We need the user to answer them.
                    # We might want to add a system note or just let them appear.
                    return True

                project.current_stage = 'research_refinement'
                return True
            
            # Old logic fallback
            if response_data.get('should_finalize'):
                project.current_stage = 'research_refinement'
                return True

            # Process new questions
            new_fields = response_data.get('form_fields', [])
            current_round_number = len(project.form_input_ids) // 5 + 1 # Simple way to increment round number, assuming 5 questions per round
            
            # Track new keys in this batch to prevent duplicates
            batch_keys = set()
            new_inputs = []
            for field in new_fields:
                # API sometimes returns field_name, sometimes field_key. Normalize.
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
                        # Phase 12 Parsing
                        'suggested_answers': json.dumps(field.get('suggested_answers', [])),
                        'depends_on': json.dumps(field.get('depends_on', {})),
                        'specify_triggers': json.dumps(field.get('specify_triggers', [])),
                    }
                    new_inputs.append(vals)
            
            if new_inputs:
                self.env['rfp.form.input'].create(new_inputs)
            else:
                # If AI returned questions but they were all filtered out as duplicates (or AI returned empty list)
                # We should assume the gathering phase is effectively complete to prevent infinite loops.
                # If AI returned questions but they were all filtered out as duplicates (or AI returned empty list)
                # We should assume the gathering phase is effectively complete to prevent infinite loops.
                project.current_stage = 'research_refinement'
                
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


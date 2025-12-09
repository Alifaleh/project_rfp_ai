from odoo import models, fields, api

class RfpProject(models.Model):
    _name = 'rfp.project'
    _description = 'RFP Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string="Project Name", required=True, tracking=True)
    description = fields.Text(string="Initial Idea", help="High-level description of the project idea", required=True, tracking=True)
    
    domain_context = fields.Selection([
        ('software', 'Software Development'),
        ('construction', 'Construction & Engineering'),
        ('events', 'Event Planning'),
        ('marketing', 'Marketing Campaign'),
        ('other', 'Other')
    ], string="Domain Context", default='software', tracking=True)

    document_language = fields.Selection([
        ('en', 'English'),
        ('ar', 'Arabic'),
        ('fr', 'French'),
        ('es', 'Spanish'),
        ('de', 'German')
    ], string="Document Language", default='en', required=True, tracking=True)

    user_id = fields.Many2one('res.users', string="Project Owner", default=lambda self: self.env.user, tracking=True)
    
    ai_context_blob = fields.Text(string="AI Context Blob", default="{}")
    
    current_stage = fields.Selection([
        ('gathering', 'Information Gathering'),
        ('structuring', 'Section Generation'),
        ('writing', 'Content Generation'),
        ('completed', 'Completed')
    ], string="Stage", default='gathering', tracking=True, group_expand='_expand_stages')

    form_input_ids = fields.One2many('rfp.form.input', 'project_id', string="Gathered Inputs")
    document_section_ids = fields.One2many('rfp.document.section', 'project_id', string="Generated Sections")

    @api.model
    def _expand_stages(self, stages, domain, order):
        return [key for key, val in type(self).current_stage.selection]

    def action_analyze_gap(self):
        """
        Main Engine:
        1. Gather Context.
        2. Call AI.
        3. Parse JSON.
        4. Generate Questions.
        """
        from odoo.addons.project_rfp_ai.utils import ai_connector
        import json

        for project in self:
            # 1. Gather Context
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_context,
                "language": project.document_language,
                "previous_inputs": [],
                "rejected_topics": []
            }
            
            for form_input in project.form_input_ids:
                if form_input.is_irrelevant:
                    context_data["rejected_topics"].append({
                        "key": form_input.field_key,
                        "question": form_input.label,
                        "reason": form_input.irrelevant_reason or 'No reason provided'
                    })
                elif form_input.user_value:
                    context_data["previous_inputs"].append({
                        "key": form_input.field_key,
                        "question": form_input.label,
                        "answer": form_input.user_value
                    })
            
            context_str = json.dumps(context_data, indent=2)
            
            # 2. Call AI with Logging
            prompt_template = self.env['rfp.prompt'].search([('code', '=', 'interviewer_main')], limit=1).template_text
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
                    schema=get_interviewer_schema()
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
                project.current_stage = 'structuring'
                # If finished, we don't necessarily need to trigger doc gen immediately if users want to review "done" state first.
                return True
            
            # Old logic fallback
            if response_data.get('should_finalize'):
                project.current_stage = 'structuring'
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
                project.current_stage = 'structuring'
                
            return True

    def action_generate_structure(self):
        """
        Phase 1: The Architect (Generate TOC)
        Moves stage to 'structuring'.
        """
        from odoo.addons.project_rfp_ai.utils import ai_connector
        import json
        
        for project in self:
            # 1. Context Building
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_context,
                "language": project.document_language,
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
            toc_prompt_template = self.env['rfp.prompt'].search([('code', '=', 'writer_toc_architect')], limit=1).template_text
            if not toc_prompt_template:
                raise ValueError("System Prompt 'writer_toc_architect' not found.")
            
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_toc_structure_schema

            architect_prompt = toc_prompt_template.format(
                 project_name=project.name,
                 domain=project.domain_context,
                 language=project.document_language,
                 context_str=context_str
            )
            
            try:
                toc_json_str = self.env['rfp.ai.log'].execute_request(
                    system_prompt=architect_prompt,
                    user_context=context_str,
                    env=self.env,
                    mode='json',
                    schema=get_toc_structure_schema()
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
            current_blob['debug_architect_context'] = context_data
            project.ai_context_blob = json.dumps(current_blob, indent=4)
            
            # Create Empty Sections (Structure Only)
            sequence = 10
            for section in toc_data.get('table_of_contents', []):
                self.env['rfp.document.section'].create({
                    'project_id': project.id,
                    'section_title': section.get('title'),
                    'content_markdown': '', # Empty for now
                    'sequence': sequence
                })
                sequence += 10
                
                for sub in section.get('subsections', []):
                    self.env['rfp.document.section'].create({
                        'project_id': project.id,
                        'section_title': sub.get('title'),
                        'content_markdown': '', 
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
        from odoo.addons.project_rfp_ai.utils import ai_connector

        for project in self:
            project.current_stage = 'writing' # Move immediately or after? User said "writing" stage.
            
            # Re-construct context (or retrieve from blob?)
            # Valid to rebuild context to ensure freshness
             # 1. Context Building
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_context,
                "language": project.document_language,
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
                if section_record.content_markdown:
                    continue # Skip if already written (allows resume)

                section_title = section_record.section_title
                section_intent = "Write comprehensive details matching the project context."
                
                writer_prompt = section_writer_template.format(
                    project_name=project.name,
                    domain=project.domain_context,
                    language=project.document_language,
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


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
        ('generating', 'Document Generation'),
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
            try:
                response_data = json.loads(response_json_str)
            except json.JSONDecodeError:
                # Fallback or Error handling
                response_data = {}

            # Update Metdata (Explicit Write as Text)
            # Inject Debug Context
            response_data['last_input_context'] = context_data
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
                project.current_stage = 'generating'
                # If finished, we don't necessarily need to trigger doc gen immediately if users want to review "done" state first.
                return True
            
            # Old logic fallback
            if response_data.get('should_finalize'):
                project.current_stage = 'generating'
                return True

            # Process new questions
            new_fields = response_data.get('form_fields', [])
            current_round_number = len(project.form_input_ids) // 5 + 1 # Simple way to increment round number, assuming 5 questions per round
            
            new_inputs = []
            for field in new_fields:
                # API sometimes returns field_name, sometimes field_key. Normalize.
                key = field.get('field_key') or field.get('field_name')
                if key and key not in existing_keys:
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
                project.current_stage = 'generating'
                
            return True

    def action_generate_document(self):
        """
        The Writer Engine (Dynamic Architect + Section Writer):
        1. Compile full context.
        2. Phase 1: Call 'writer_toc_architect' to design the Table of Contents.
        3. Phase 2: Iterate through the TOC and call 'writer_section_content' for each.
        4. Save to document sections.
        """
        from odoo.addons.project_rfp_ai.utils import ai_connector
        import json
        import time

        for project in self:
            # 1. Context Building (Gathered Requirements)
            context_data = {
                "project_name": project.name,
                "description": project.description,
                "domain": project.domain_context,
                "language": project.document_language,
                "q_and_a": []
            }
            # Enhanced Q&A formatting to be more readable for the Writer
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
            
            # Use the new Schema
            from odoo.addons.project_rfp_ai.models.ai_schemas import get_toc_structure_schema

            # Prepare Architect Context
            # We format the prompt first, OR let the connector handle it. 
            # Given current architecture, we format context_str here.
            # But wait, ai_connector expects a single string prompt.
            architect_prompt = toc_prompt_template.format(
                 project_name=project.name,
                 domain=project.domain_context,
                 language=project.document_language,
                 context_str=context_str
            )
            
            # Call AI for TOC (Architect)
            try:
                toc_json_str = self.env['rfp.ai.log'].execute_request(
                    system_prompt=architect_prompt,
                    user_context=context_str,
                    env=self.env,
                    mode='json',
                    schema=get_toc_structure_schema()
                )
            except Exception as e:
                # Fallback for Architect failure
                toc_json_str = json.dumps({"table_of_contents": [{"title": "Error Generating Structure", "subsections": []}]})
            
            try:
                toc_data = json.loads(toc_json_str)
            except json.JSONDecodeError:
                # Fallback if AI fails completely (Should not happen with Retry logic)
                toc_data = {"table_of_contents": [{"title": "Executive Summary", "subsections": []}]}


            # Save TOC meta to context blob (to answer user's question about empty blob)
            # FORCE COPY to ensure Odoo detects the change
            # Text Field Update Logic
            current_blob_str = project.ai_context_blob or "{}"
            try:
                current_blob = json.loads(current_blob_str)
            except:
                current_blob = {}
            
            current_blob['toc_structure'] = toc_data
            current_blob['debug_architect_context'] = context_data
            project.ai_context_blob = json.dumps(current_blob, indent=4)
            
            
            # --- PHASE 2: THE WRITER (Generate Content) ---
            
            section_writer_template = self.env['rfp.prompt'].search([('code', '=', 'writer_section_content')], limit=1).template_text
            
            # Flatten the TOC for sequential writing
            # Logic: We will create sections. If there are subsections, we will generate them as separate records 
            # OR combined? User said "sections and subsections". 
            # To match Odoo's flat 'rfp.document.section' structure, we will treat them as sequence items.
            
            # Serialize the Global Structure to pass to the writer
            toc_context_str = json.dumps(toc_data.get('table_of_contents', []), indent=2)
            
            sequence = 10
            
            for section in toc_data.get('table_of_contents', []):
                # 1. Main Section
                section_title = section.get('title')
                section_intent = section.get('description_intent', 'Write comprehensive content.')
                
                # Generate Main Section Content
                writer_prompt = section_writer_template.format(
                    project_name=project.name,
                    domain=project.domain_context,
                    language=project.document_language,
                    toc_context=toc_context_str,
                    section_title=section_title,
                    section_intent=section_intent,
                    context_str=context_str
                )
                
                # Call Writer (Main Section)
                try:
                    content = self.env['rfp.ai.log'].execute_request(
                        system_prompt=writer_prompt,
                        # We construct the user message here as the single user_context argument
                        user_context=f"Project Context:\n{context_str}\n\nPlease write the {section_title} section now. Intent: {section_intent}",
                        env=self.env,
                        mode='text'
                    )
                except Exception:
                    content = "Error generating content."
                time.sleep(20) # Rate limit safeguard
                
                self.env['rfp.document.section'].create({
                    'project_id': project.id,
                    'section_title': section_title,
                    'content_markdown': content,
                    'sequence': sequence
                })
                sequence += 10
                
                # 2. Subsections (if any)
                for sub in section.get('subsections', []):
                    sub_title = sub.get('title') # e.g. "1.1 Overview"
                    sub_intent = sub.get('description_intent', 'Write specific details.')
                    
                    writer_prompt_sub = section_writer_template.format(
                        project_name=project.name,
                        domain=project.domain_context,
                        language=project.document_language,
                        toc_context=toc_context_str,
                        section_title=sub_title,
                        section_intent=sub_intent,
                        context_str=context_str
                    )
                    
                    try:
                        sub_content = self.env['rfp.ai.log'].execute_request(
                            system_prompt=writer_prompt_sub,
                            user_context=f"Project Context:\n{context_str}\n\nPlease write the {sub_title} section now. Intent: {sub_intent}",
                            env=self.env,
                            mode='text'
                        )
                    except Exception:
                        sub_content = "Error generating subsection content."
                    time.sleep(20) # Rate limit safeguard
                    
                    self.env['rfp.document.section'].create({
                        'project_id': project.id,
                        'section_title': sub_title, # Indentation is visual, backend is flat
                        'content_markdown': sub_content,
                        'sequence': sequence
                    })
                    sequence += 10

            project.current_stage = 'generating'
            return True

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


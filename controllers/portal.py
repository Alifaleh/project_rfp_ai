from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
import json
import base64
from odoo.addons.project_rfp_ai.const import *

class RfpCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'rfp_count' in counters:
            values['rfp_count'] = request.env['rfp.project'].sudo().search_count([('user_id', '=', request.env.user.id)])
        return values

    @http.route(['/my', '/my/home'], type='http', auth="user", website=True)
    def home(self, **kw):
        values = self._prepare_portal_layout_values()
        Project = request.env['rfp.project'].sudo()
        domain = [('user_id', '=', request.env.user.id)]
        projects = Project.search(domain)
        values.update({
            'projects': projects,
            'page_name': 'home',
        })
        return request.render("project_rfp_ai.portal_my_rfps", values)

    @http.route(['/my/rfp', '/my/rfp/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_rfps(self, page=1, **kw):
        return request.redirect('/my')

    @http.route(['/rfp/start'], type='http', auth="user", website=True)
    def portal_rfp_start(self, **kw):
        # Refactor Phase 4: Init fields moved to gathering stage
        return request.render("project_rfp_ai.portal_rfp_start", {})

    @http.route(['/rfp/init'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_init(self, **post):
        if request.httprequest.method == 'POST':
            final_description = post.get('description', '')

            Project = request.env['rfp.project'].sudo()
            new_project = Project.create({
                'name': post.get('name'),
                'description': final_description,
                'user_id': request.env.user.id
            })
            
            # 1. Initialize (Create empty inputs for Init Fields)
            new_project.action_initialize_project()
            
            # 2. DO NOT trigger action_analyze_gap yet
            # We want the user to answer the Init Fields first in the portal interface.
            # The interface logic will detect them and present them.
            
            return request.redirect(f"/rfp/interface/{new_project.id}")
        return request.redirect('/my/rfp/start')

    @http.route(['/rfp/interface/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_interface(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        
        # 0. Handle Draft State
        if Project.current_stage == STAGE_DRAFT:
            Project.action_initialize_project()
            return request.redirect(f"/rfp/interface/{Project.id}")

        # 1. Workflow Automation (Try to advance non-interactive stages)
        if Project.current_stage == STAGE_INFO_GATHERED:
            Project.action_proceed_next_stage() # -> practices_refined
            return request.redirect(f"/rfp/interface/{Project.id}")
            
        elif Project.current_stage == STAGE_PRACTICES_REFINED:
             Project.action_proceed_next_stage() # -> specifications_gathered
             return request.redirect(f"/rfp/interface/{Project.id}")
             
        elif Project.current_stage == STAGE_PRACTICES_GAP_GATHERED:
             Project.action_proceed_next_stage() # -> sections_generated
             return request.redirect(f"/rfp/interface/{Project.id}")
        
        # 2. Redirect based on Major Phase
        # 2. Redirect based on Major Phase
        if Project.current_stage in [STAGE_SECTIONS_GENERATED, STAGE_GENERATING_CONTENT, STAGE_CONTENT_GENERATED, STAGE_GENERATING_IMAGES, STAGE_IMAGES_GENERATED]:
             # UNIFIED PROCESSING PAGE
             return request.redirect(f"/rfp/processing/{Project.id}")
        elif Project.current_stage in [STAGE_DOCUMENT_LOCKED, STAGE_COMPLETED, STAGE_COMPLETED_WITH_ERRORS]:
             # FINAL VIEW / EDIT
             return request.redirect(f"/rfp/edit/{Project.id}")

        # 3. Gather Questions for Current Stage
        questions_to_answer = []
        is_generating = False 
        
        if Project.current_stage == STAGE_INITIALIZED:
             # Logic for "Preliminary Questions" (Init Fields) AND AI Follow-up
             # The first batch are init fields (created by action_initialize_project)
             # They have user_value = False.
             questions_to_answer = Project.form_input_ids.filtered(lambda i: not i.user_value and not i.is_irrelevant)
             
             # If no questions, but we are still in INITIALIZED, it means we need to trigger AI to ask more 
             # OR we are waiting for AI.
             if not questions_to_answer:
                 # Check if AI job is running? For now, we assume if we are here and no questions,
                 # we should trigger the next round analysis.
                 # BUT, we must distinguish between "All questions answered, trigger AI" vs "AI is thinking".
                 # The 'action_analyze_gap' handles this. If it returns True (ongoing), we might mean AI returns instantly (sync).
                 # If using async jobs, we'd need a status check.
                 pass

        elif Project.current_stage == STAGE_SPECIFICATIONS_GATHERED:
             questions_to_answer = Project.practice_input_ids.filtered(lambda i: not i.user_value and not i.is_irrelevant)
             
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_interface',
            'questions_to_answer': questions_to_answer,
            'is_generating': is_generating
        })
        return request.render("project_rfp_ai.portal_rfp_interface", values)

    @http.route(['/rfp/next_step/<int:project_id>'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_next_step(self, project_id, **post):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')

        # Determine Inputs to Process
        input_map = {}
        stage_action = None

        if Project.current_stage == STAGE_INITIALIZED:
             input_map = {inp.field_key: inp for inp in Project.form_input_ids}
             stage_action = Project.action_analyze_gap
        elif Project.current_stage == STAGE_SPECIFICATIONS_GATHERED:
             input_map = {inp.field_key: inp for inp in Project.practice_input_ids}
             stage_action = Project.action_analyze_practices_gap

        # Process Inputs
        for key, inp_record in input_map.items():
            # 1. Custom Answer
            custom_answer_flag = post.get(f"has_custom_answer_{key}")
            if custom_answer_flag == 'true':
                custom_val = post.get(f"custom_answer_val_{key}")
                if custom_val:
                    inp_record.sudo().write({'user_value': custom_val})
                continue
            # 2. Irrelevant
            is_irrelevant = post.get(f"is_irrelevant_{key}")
            if is_irrelevant == 'true':
                reason = post.get(f"irrelevant_reason_{key}")
                vals = {'is_irrelevant': True}
                if reason: vals['irrelevant_reason'] = reason
                inp_record.sudo().write(vals)
                continue
            # 3. Standard
            if key in post:
                value = post.get(key)
                specify_key = f"{key}_specify"
                final_value = value
                if specify_key in post and post.get(specify_key):
                     final_value = f"{value}: {post.get(specify_key)}"
                
                inp_record.sudo().write({'user_value': final_value})
        # Trigger Next Analysis Step
        if stage_action:
            stage_action()
            
        return request.redirect(f"/rfp/interface/{Project.id}")

    # --- PHASE 2: UNIFIED PROCESSING ---
    @http.route(['/rfp/processing/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_processing(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        # Define milestones for the progress bar
        milestones = [
            {'stage': STAGE_SECTIONS_GENERATED, 'label': 'Generating Structure...', 'progress': 20},
            {'stage': STAGE_GENERATING_CONTENT, 'label': 'Writing Content...', 'progress': 50},
            {'stage': STAGE_CONTENT_GENERATED, 'label': 'Content Written', 'progress': 70},
            {'stage': STAGE_GENERATING_IMAGES, 'label': 'Drawing Diagrams...', 'progress': 90}, 
            {'stage': STAGE_IMAGES_GENERATED, 'label': 'Finishing Up...', 'progress': 100}
        ]
        
        # Determine current visual state
        current_progress = 0
        current_label = "Initializing..."
        
        # Simple lookup
        for m in milestones:
            if Project.current_stage == m['stage']:
                current_label = m['label']
                current_progress = m['progress']
                break
        
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_processing',
            'current_label': current_label,
            'current_progress': current_progress
        })
        return request.render("project_rfp_ai.portal_rfp_processing", values)
        
    @http.route(['/rfp/status/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_status(self, project_id):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return {'error': 'Access Denied'}
        
        # Trigger status check to update stage if complete
        Project.action_check_generation_status()
        
        # Return progress
        status_data = Project.get_generation_status()
        status_data['stage'] = Project.current_stage # Add Stage Info
        return status_data

    # --- PHASE 3: UNIFIED EDITOR (SPA) ---
    @http.route(['/rfp/edit/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_edit(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_edit',
        })
        return request.render("project_rfp_ai.portal_rfp_unified_editor", values)

    @http.route(['/rfp/unified/save/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_unified_save(self, project_id, structure_data=None, content_data=None):
        """
        Unified Save Endpoint.
        structure_data: List of {id, section_title, sequence}
        content_data: Dict of {id: html}
        """
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
             return {'error': 'Access Denied'}
             
        if structure_data:
            # We need to map temp IDs to real IDs if new sections are created
            # Assuming action_update_structure returns a map or we handle it here
            id_map = Project.action_update_structure(structure_data)
            
            # Update content_data keys if we have mappings (for new sections)
            if id_map and content_data:
                for temp_id, real_id in id_map.items():
                    if str(temp_id) in content_data:
                        content_data[str(real_id)] = content_data.pop(str(temp_id))
                        
        if content_data:
            Project.action_update_content_html(content_data)
            
        return {'status': 'success'}

    @http.route(['/rfp/lock_toggle'], type='json', auth="user", website=True)
    def portal_rfp_lock_toggle(self, project_id):
        # Use sudo to bypass ACL, then verify ownership
        project = request.env['rfp.project'].sudo().browse(int(project_id))
        if not project.exists():
            return {'error': 'Project not found'}
        
        # Verify ownership
        if project.user_id.id != request.env.user.id:
            return {'error': 'Permission Denied'}
        
        # Toggle Logic
        if project.current_stage == 'completed':
            # Unlock
            # Unlock 
            # Note: Using 'document_locked' as the "Completed/Locked" state for now based on prompt, 
            # but user request implies toggle. Let's assume 'document_locked' is the locked state.
            # Rereading models: STAGE_DOCUMENT_LOCKED = 'document_locked'
            # STAGE_COMPLETED = 'completed'
            # Wait, user wants to Lock/Unlock. 
            # If current is locked, unlock to generated? or completed? 
            # Let's pivot: Unlock -> STAGE_SECTIONS_GENERATED (allows editing), Lock -> STAGE_DOCUMENT_LOCKED
            new_stage = 'sections_generated'
            locked = False
        elif project.current_stage == 'document_locked':
            # Unlock
             new_stage = 'sections_generated'
             locked = False
        else:
            # Lock
            new_stage = 'document_locked'
            locked = True
            
        project.write({'current_stage': new_stage})
        return {'success': True, 'locked': locked, 'new_stage': new_stage}

    @http.route(['/rfp/diagram/upload'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_diagram_upload(self, section_id=None, image_file=None, title=None, description=None, **kwargs):
        if not section_id or not image_file:
            return json.dumps({'error': 'Missing data'})
        
        # Use sudo to browse section (portal users can't read related project)
        section = request.env['rfp.document.section'].sudo().browse(int(section_id))
        if not section.exists():
             return json.dumps({'error': 'Section not found'})
             
        # Check ownership via explicit ID comparison
        if section.project_id.user_id.id != request.env.user.id:
            return json.dumps({'error': 'Permission Denied'})

        try:
            image_data = image_file.read()
            # Create diagram record using sudo()
            diagram = request.env['rfp.section.diagram'].sudo().create({
                'section_id': section.id,
                'image_file': base64.b64encode(image_data),
                'title': title or image_file.filename,
                'description': description or 'Uploaded Image'
            })
            return json.dumps({
                'success': True, 
                'diagram_id': diagram.id, 
                'image_url': f"/web/image/rfp.section.diagram/{diagram.id}/image_file",
                'title': diagram.title,
                'description': diagram.description
            })
        except Exception as e:
            return json.dumps({'error': str(e)})

    @http.route(['/rfp/diagram/delete/<int:diagram_id>'], type='json', auth="user", website=True)
    def portal_rfp_diagram_delete(self, diagram_id):
        # Use sudo entirely to bypass the restriction, BUT modify the check logic
        diagram = request.env['rfp.section.diagram'].sudo().browse(diagram_id)
        if diagram.exists():
            # Check if user owns the project via section - explicit ID check
            # We access user_id.id to avoid record rule issues on res.user 
            if diagram.section_id.project_id.user_id.id != request.env.user.id:
                 return {'error': 'Permission Denied'}
                 
            diagram.unlink() # already sudo-ed
            return {'success': True}
        return {'error': 'Diagram not found'}

    # --- AI EDITING ROUTES ---
    
    @http.route(['/rfp/ai/edit/text'], type='json', auth="user", website=True)
    def portal_rfp_ai_edit_text(self, section_id, user_prompt):
        """Edit section content with AI based on user prompt."""
        from odoo.addons.project_rfp_ai.utils.ai_connector import _call_gemini_api
        
        section = request.env['rfp.document.section'].sudo().browse(int(section_id))
        if not section.exists():
            return {'error': 'Section not found'}
        
        # Verify ownership
        if section.project_id.user_id.id != request.env.user.id:
            return {'error': 'Permission Denied'}
        
        try:
            # Get prompt template
            prompt_record = request.env['rfp.prompt'].sudo().search([('code', '=', 'edit_with_ai_text')], limit=1)
            if not prompt_record:
                return {'error': 'AI prompt not configured. Please run module upgrade.'}
            
            # Format system prompt and user content
            system_prompt = prompt_record.template_text.format(
                current_content=section.content_html or '<p>No content yet.</p>',
                user_prompt=user_prompt
            )
            
            # Get model name from prompt record
            model_name = prompt_record.ai_model_id.technical_name if prompt_record.ai_model_id else None
            
            # Call AI using the utility function
            response = _call_gemini_api(
                system_instructions=system_prompt,
                user_content=f"Apply the following edit to the section content: {user_prompt}",
                env=request.env,
                response_mime_type="text/plain",
                model_name=model_name
            )
            
            if response:
                # Update section content
                section.write({'content_html': response})
                return {'success': True, 'new_content': response}
            else:
                return {'error': 'AI returned empty response'}
                
        except Exception as e:
            return {'error': str(e)}
    
    @http.route(['/rfp/ai/edit/image'], type='json', auth="user", website=True)
    def portal_rfp_ai_edit_image(self, diagram_id, user_prompt):
        """Regenerate diagram image with AI based on user prompt."""
        from odoo.addons.project_rfp_ai.utils.ai_connector import _generate_image_gemini
        import base64
        
        diagram = request.env['rfp.section.diagram'].sudo().browse(int(diagram_id))
        if not diagram.exists():
            return {'error': 'Diagram not found'}
        
        # Verify ownership
        if diagram.section_id.project_id.user_id.id != request.env.user.id:
            return {'error': 'Permission Denied'}
        
        try:
            # Get prompt template
            prompt_record = request.env['rfp.prompt'].sudo().search([('code', '=', 'edit_with_ai_image')], limit=1)
            if not prompt_record:
                return {'error': 'AI prompt not configured. Please run module upgrade.'}
            
            # Format prompt
            full_prompt = prompt_record.template_text.format(
                original_description=diagram.description or diagram.title or 'A diagram',
                user_prompt=user_prompt
            )
            
            # Get model name from prompt record
            model_name = prompt_record.ai_model_id.technical_name if prompt_record.ai_model_id else 'imagen-3.0-generate-001'
            
            # Call AI (Image generation)
            image_bytes = _generate_image_gemini(
                prompt=full_prompt,
                env=request.env,
                model_name=model_name
            )
            
            if image_bytes:
                # Convert to base64 and update diagram
                image_b64 = base64.b64encode(image_bytes).decode('utf-8')
                diagram.write({'image_file': image_b64})
                return {
                    'success': True, 
                    'new_image_url': f"/web/image/rfp.section.diagram/{diagram.id}/image_file?t={int(__import__('time').time())}"
                }
            else:
                return {'error': 'AI returned empty response'}
                
        except Exception as e:
            return {'error': str(e)}

    @http.route(['/rfp/download/word/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_download_word(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')

        # Use Zero-Dependency DOCX Generator
        from odoo.addons.project_rfp_ai.utils.simple_docx import SimpleDocxGenerator
        
        docx = SimpleDocxGenerator()
        
        # Add Title
        docx.add_heading(Project.name, 1)
        docx.add_text("") # spacing
        
        # Add Contact Information
        contact_keys = ['contact_name', 'contact_email', 'contact_phone', 'contact_details']
        contact_inputs = Project.form_input_ids.filtered(lambda i: i.field_key in contact_keys)
        
        if contact_inputs:
            docx.add_heading("Contact Information", 3)
            # Sort by intended order? The fields have sequence in DB, but inputs might be created by ID. 
            # We can just map key to value.
            input_map = {i.field_key: i.user_value for i in contact_inputs}
            
            # Helper to add line if exists
            def add_contact_line(label, key):
                val = input_map.get(key)
                if val:
                    docx.add_text(f"{label}: {val}")
            
            add_contact_line("Name", 'contact_name')
            add_contact_line("Email", 'contact_email')
            add_contact_line("Phone", 'contact_phone')
            add_contact_line("Details", 'contact_details')
            
            docx.add_spacer()
        
        for section in Project.document_section_ids.sorted('sequence'):
            docx.add_heading(section.section_title, 2)
            
            # Content
            if section.content_html:
                docx.add_html_chunk(section.content_html)
                
            # Diagrams
            if section.diagram_ids:
                docx.add_spacer()
                
                for diagram in section.diagram_ids:
                    # Image
                    if diagram.image_file:
                        try:
                            image_data = base64.b64decode(diagram.image_file)
                            docx.add_image(image_data)
                        except Exception as e:
                            print(f"Error embedding image: {e}")
                            docx.add_text("[Error embedding image]")
                            
                    # Title (Caption) under the image
                    docx.add_caption(diagram.title)
                    docx.add_spacer()

        file_content = docx.generate()
        
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
            ('Content-Disposition', f'attachment; filename="RFP - {Project.name}.docx"')
        ]
        return request.make_response(file_content, headers=headers)

    # ============ PUBLISH ROUTES ============

    @http.route(['/rfp/publish/<int:project_id>'], type='json', auth="user", methods=['POST'])
    def portal_rfp_publish(self, project_id, **kw):
        """Publish or update an RFP for public viewing."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        
        # Verify ownership
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}
        
        try:
            public_url = Project.action_publish()
            return {'success': True, 'url': public_url, 'is_update': bool(Project.published_id.last_updated)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route(['/rfp/unpublish/<int:project_id>'], type='json', auth="user", methods=['POST'])
    def portal_rfp_unpublish(self, project_id, **kw):
        """Take down a published RFP."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        
        # Verify ownership
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}
        
        try:
            Project.action_unpublish()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route(['/rfp/public/<string:uuid>'], type='http', auth="public", website=True)
    def portal_rfp_public_view(self, uuid, **kw):
        """Public view of a published RFP."""
        Published = request.env['rfp.published'].sudo().search([('uuid', '=', uuid), ('active', '=', True)], limit=1)
        
        if not Published:
            return request.redirect('/')
        
        values = {
            'published': Published,
            'sections': Published.section_ids.sorted(lambda s: s.sequence),
        }
        return request.render("project_rfp_ai.portal_rfp_public_view", values)

    @http.route(['/rfp/public/<string:uuid>/submit'], type='http', auth="public", website=True, methods=['GET', 'POST'], csrf=True)
    def portal_rfp_proposal_submit(self, uuid, **post):
        """Proposal submission form and handler."""
        Published = request.env['rfp.published'].sudo().search([('uuid', '=', uuid), ('active', '=', True)], limit=1)
        
        if not Published:
            return request.redirect('/')
        
        if request.httprequest.method == 'POST':
            # Handle file upload
            proposal_file = None
            proposal_filename = None
            if 'proposal_file' in request.httprequest.files:
                file = request.httprequest.files['proposal_file']
                if file.filename:
                    proposal_file = base64.b64encode(file.read())
                    proposal_filename = file.filename
            
            # Create proposal
            request.env['rfp.proposal'].sudo().create({
                'published_id': Published.id,
                'company_name': post.get('company_name'),
                'contact_person': post.get('contact_person'),
                'email': post.get('email'),
                'phone': post.get('phone'),
                'website': post.get('website'),
                'linkedin': post.get('linkedin'),
                'proposal_file': proposal_file,
                'proposal_filename': proposal_filename,
                'notes': post.get('notes'),
            })
            
            return request.render("project_rfp_ai.portal_rfp_proposal_success", {'published': Published})
        
        values = {
            'published': Published,
        }
        return request.render("project_rfp_ai.portal_rfp_proposal_form", values)

    @http.route(['/rfp/proposals/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_view_proposals(self, project_id, **kw):
        """View proposals for a project."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return request.redirect('/my')
        
        if not Project.published_id:
            return request.redirect(f'/rfp/editor/{project_id}')
        
        values = {
            'project': Project,
            'published': Project.published_id,
            'proposals': Project.published_id.proposal_ids.sorted(lambda p: p.submitted_date, reverse=True),
        }
        return request.render("project_rfp_ai.portal_rfp_proposals_list", values)

    @http.route(['/rfp/proposal/<int:proposal_id>'], type='http', auth="user", website=True)
    def portal_rfp_proposal_detail(self, proposal_id, **kw):
        """View individual proposal details."""
        Proposal = request.env['rfp.proposal'].sudo().browse(proposal_id)
        
        if not Proposal.exists():
            return request.redirect('/my')
        
        # Check ownership - the proposal's RFP must belong to current user
        Project = Proposal.published_id.project_id
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return request.redirect('/my')
        
        # Determine file type for viewer
        file_type = None
        if Proposal.proposal_filename:
            ext = Proposal.proposal_filename.lower().split('.')[-1] if '.' in Proposal.proposal_filename else ''
            if ext == 'pdf':
                file_type = 'pdf'
            elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                file_type = 'image'
        
        values = {
            'proposal': Proposal,
            'project': Project,
            'file_type': file_type,
        }
        return request.render("project_rfp_ai.portal_rfp_proposal_detail", values)

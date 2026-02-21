from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal
import json
import base64
import logging

_logger = logging.getLogger(__name__)
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

    @http.route(['/rfp/upload'], type='http', auth="user", methods=['POST'], website=True, csrf=True)
    def portal_rfp_upload(self, **post):
        """Upload an existing RFP document to create a new project."""
        uploaded_file = request.httprequest.files.get('rfp_file')
        project_name = post.get('project_name', '').strip()

        if not uploaded_file or not uploaded_file.filename:
            return request.make_json_response({'success': False, 'error': 'No file uploaded'})

        filename = uploaded_file.filename
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        MIME_MAP = {
            'pdf': 'application/pdf',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
        if ext not in MIME_MAP:
            return request.make_json_response({'success': False, 'error': 'Only PDF and DOCX files are supported'})

        try:
            file_data = uploaded_file.read()
            file_b64 = base64.b64encode(file_data)

            Project = request.env['rfp.project'].sudo()
            new_project = Project.create({
                'name': project_name or 'Untitled Upload',
                'description': f'Imported from: {filename}',
                'user_id': request.env.user.id,
                'source_document': file_b64,
                'source_filename': filename,
                'source_mimetype': MIME_MAP[ext],
            })

            new_project.action_initialize_from_document()

            return request.make_json_response({
                'success': True,
                'project_id': new_project.id,
                'redirect_url': f'/rfp/interface/{new_project.id}'
            })
        except Exception as e:
            _logger.exception("RFP upload failed for file '%s'", filename)
            return request.make_json_response({'success': False, 'error': str(e)})

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

    @http.route(['/rfp/clear_autofill/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_clear_autofill(self, project_id, field_key=None, **kw):
        """Clear an auto-filled answer so the user can re-answer it."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return {'success': False, 'error': 'Access denied'}

        if not field_key:
            return {'success': False, 'error': 'No field_key provided'}

        inp = Project.form_input_ids.filtered(lambda i: i.field_key == field_key)
        if inp:
            inp.write({'user_value': False, 'is_auto_filled': False})
            return {'success': True}
        return {'success': False, 'error': 'Field not found'}

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

    # ============ EXPORT ROUTES ============

    @http.route(['/rfp/export/<int:project_id>'], type='json', auth="user", methods=['POST'])
    def portal_rfp_export(self, project_id, **kw):
        """Export RFP for download (no public submission)."""
        Project = request.env['rfp.project'].sudo().browse(project_id)

        # Verify ownership
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        try:
            download_url = Project.action_export_rfp()
            return {'success': True, 'url': download_url, 'is_update': bool(Project.published_id.last_updated)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route(['/rfp/delete_export/<int:project_id>'], type='json', auth="user", methods=['POST'])
    def portal_rfp_delete_export(self, project_id, **kw):
        """Delete an exported RFP."""
        Project = request.env['rfp.project'].sudo().browse(project_id)

        # Verify ownership
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        try:
            Project.action_delete_export()
            return {'success': True}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route(['/rfp/export/view/<string:uuid>'], type='http', auth="user", website=True)
    def portal_rfp_export_view(self, uuid, **kw):
        """View exported RFP (authenticated only)."""
        Published = request.env['rfp.published'].sudo().search([('uuid', '=', uuid), ('active', '=', True)], limit=1)

        if not Published:
            return request.redirect('/my')

        # Verify ownership
        if Published.owner_id.id != request.env.user.id:
            return request.redirect('/my')

        values = {
            'published': Published,
            'sections': Published.section_ids.sorted(lambda s: s.sequence),
        }
        return request.render("project_rfp_ai.portal_rfp_export_view", values)

    # ============ PROPOSALS ROUTES (Owner only - no public submission) ============

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
        import json
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
        
        # Parse analysis result if available
        analysis = None
        if Proposal.analysis_status == 'done' and Proposal.analysis_result:
            try:
                analysis = json.loads(Proposal.analysis_result)
            except json.JSONDecodeError:
                analysis = None
        
        values = {
            'proposal': Proposal,
            'project': Project,
            'file_type': file_type,
            'analysis': analysis,
        }
        # Parse criteria scores if available
        criteria_scores = None
        if Proposal.criteria_scores:
            try:
                criteria_scores = json.loads(Proposal.criteria_scores)
            except json.JSONDecodeError:
                criteria_scores = None

        values['criteria_scores'] = criteria_scores
        values['weighted_score'] = Proposal.weighted_score
        values['has_must_have_failure'] = Proposal.has_must_have_failure

        # Multi-document support
        proposal_documents = []
        for doc in Proposal.document_ids.sorted('sequence'):
            doc_file_type = None
            if doc.filename:
                ext = doc.filename.lower().split('.')[-1] if '.' in doc.filename else ''
                if ext == 'pdf':
                    doc_file_type = 'pdf'
                elif ext in ['png', 'jpg', 'jpeg', 'gif', 'webp']:
                    doc_file_type = 'image'
            proposal_documents.append({
                'doc': doc,
                'file_type': doc_file_type,
            })
        values['proposal_documents'] = proposal_documents

        return request.render("project_rfp_ai.portal_rfp_proposal_detail", values)

    @http.route(['/rfp/proposal/upload/<int:project_id>'], type='http', auth="user",
                methods=['POST'], website=True, csrf=True)
    def portal_rfp_proposal_upload(self, project_id, **post):
        """Client uploads vendor proposal documents for AI analysis."""
        import base64
        Project = request.env['rfp.project'].sudo().browse(project_id)

        # Verify ownership
        if not Project.exists() or Project.user_id != request.env.user:
            return request.make_json_response({'success': False, 'error': 'Access denied'})

        vendor_name = post.get('vendor_name', '').strip()
        required_docs = Project.required_document_ids.sorted('sequence')

        # Collect all uploaded files
        all_files = request.httprequest.files
        main_proposal_file = None
        main_proposal_filename = None
        main_proposal_b64 = None

        # Ensure project has a published record
        if not Project.published_id:
            published = request.env['rfp.published'].sudo().create({
                'project_id': Project.id,
                'title': Project.name,
                'description': Project.description or '',
                'owner_id': Project.user_id.id,
            })
            Project.published_id = published.id

        # Process required document files (doc_file_{id})
        doc_entries = []
        for doc_type in required_docs:
            file_key = f'doc_file_{doc_type.id}'
            if file_key in all_files:
                f = all_files[file_key]
                if f.filename:
                    f_bytes = f.read()
                    f_b64 = base64.b64encode(f_bytes).decode('utf-8')
                    doc_entries.append({
                        'required_document_id': doc_type.id,
                        'name': doc_type.name,
                        'file_data': f_b64,
                        'filename': f.filename,
                        'sequence': doc_type.sequence,
                    })
                    # Use first PDF/DOCX as main proposal for AI extraction
                    if not main_proposal_file:
                        ext = f.filename.lower().split('.')[-1]
                        if ext in ('pdf', 'docx'):
                            main_proposal_file = f_b64
                            main_proposal_filename = f.filename

        # Process the additional/single proposal_file input
        additional_file = all_files.get('proposal_file')
        if additional_file and additional_file.filename:
            add_bytes = additional_file.read()
            add_b64 = base64.b64encode(add_bytes).decode('utf-8')
            if not main_proposal_file:
                ext = additional_file.filename.lower().split('.')[-1]
                if ext in ('pdf', 'docx'):
                    main_proposal_file = add_b64
                    main_proposal_filename = additional_file.filename
                else:
                    return request.make_json_response({
                        'success': False,
                        'error': 'Only PDF and DOCX files are supported for AI analysis'
                    })
            # Also store as a document entry if required docs exist
            if required_docs:
                doc_entries.append({
                    'name': 'Additional Document',
                    'file_data': add_b64,
                    'filename': additional_file.filename,
                    'sequence': 999,
                })

        # Validate we have at least one file
        if not main_proposal_file and not doc_entries:
            return request.make_json_response({'success': False, 'error': 'No files provided'})

        # Create proposal record
        Proposal = request.env['rfp.proposal'].sudo().create({
            'published_id': Project.published_id.id,
            'proposal_file': main_proposal_file,
            'proposal_filename': main_proposal_filename or '',
            'company_name': vendor_name or 'Processing...',
            'contact_person': 'Extracting...',
            'email': 'pending@extraction.ai',
            'status': 'new',
            'analysis_status': 'pending',
        })

        # Create document records
        for entry in doc_entries:
            entry['proposal_id'] = Proposal.id
            request.env['rfp.proposal.document'].sudo().create(entry)

        # Trigger AI extraction and analysis
        try:
            Proposal.action_extract_and_analyze()
        except Exception as e:
            return request.make_json_response({
                'success': False,
                'error': f'Upload succeeded but analysis failed: {str(e)}'
            })

        return request.make_json_response({
            'success': True,
            'proposal_id': Proposal.id,
            'redirect_url': f'/rfp/proposals/{project_id}'
        })

    # ========== EVALUATION CRITERIA ROUTES ==========

    @http.route(['/rfp/eval/setup/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_eval_setup(self, project_id, **kw):
        """Evaluation criteria setup page - routes to interview or review."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return request.redirect('/my')

        if Project.eval_criteria_status == 'not_started':
            # First visit — trigger first interview round
            Project.action_gather_eval_criteria()
            return request.redirect(f"/rfp/eval/setup/{Project.id}")

        if Project.eval_criteria_status == 'gathering':
            # Show unanswered eval questions
            questions = Project.eval_input_ids.filtered(lambda i: not i.user_value and not i.is_irrelevant)
            if not questions:
                # All questions answered but still gathering — trigger next round
                Project.action_gather_eval_criteria()
                return request.redirect(f"/rfp/eval/setup/{Project.id}")

            values = self._prepare_portal_layout_values()
            values.update({
                'rfp_project': Project,
                'questions_to_answer': questions,
                'page_name': 'eval_interview',
            })
            return request.render("project_rfp_ai.portal_rfp_eval_interview", values)

        if Project.eval_criteria_status in ('generated', 'finalized'):
            # Show criteria for review/edit
            values = self._prepare_portal_layout_values()
            values.update({
                'rfp_project': Project,
                'criteria': Project.evaluation_criterion_ids.filtered('active').sorted('sequence'),
                'page_name': 'eval_review',
                'total_weight': sum(c.weight for c in Project.evaluation_criterion_ids.filtered('active')),
            })
            return request.render("project_rfp_ai.portal_rfp_eval_review", values)

        return request.redirect(f"/rfp/proposals/{Project.id}")

    @http.route(['/rfp/eval/next_step/<int:project_id>'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_eval_next_step(self, project_id, **post):
        """Process eval interview answers and trigger next round."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return request.redirect('/my')

        # Process inputs — same pattern as portal_rfp_next_step
        input_map = {inp.field_key: inp for inp in Project.eval_input_ids}

        for key, inp_record in input_map.items():
            custom_answer_flag = post.get(f"has_custom_answer_{key}")
            if custom_answer_flag == 'true':
                custom_val = post.get(f"custom_answer_val_{key}")
                if custom_val:
                    inp_record.sudo().write({'user_value': custom_val})
                continue

            is_irrelevant = post.get(f"is_irrelevant_{key}")
            if is_irrelevant == 'true':
                reason = post.get(f"irrelevant_reason_{key}")
                vals = {'is_irrelevant': True}
                if reason:
                    vals['irrelevant_reason'] = reason
                inp_record.sudo().write(vals)
                continue

            if key in post:
                value = post.get(key)
                specify_key = f"{key}_specify"
                final_value = value
                if specify_key in post and post.get(specify_key):
                    final_value = f"{value}: {post.get(specify_key)}"
                inp_record.sudo().write({'user_value': final_value})

        # Trigger next round
        Project.action_gather_eval_criteria()
        return request.redirect(f"/rfp/eval/setup/{Project.id}")

    @http.route(['/rfp/eval/save/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_save(self, project_id, criteria=None, **kw):
        """Save edited criteria (weights, names, must-have toggles)."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        if not criteria:
            return {'success': False, 'error': 'No data provided'}

        for item in criteria:
            criterion = request.env['rfp.evaluation.criterion'].sudo().browse(item.get('id'))
            if criterion.exists() and criterion.project_id.id == Project.id:
                vals = {}
                if 'name' in item:
                    vals['name'] = item['name']
                if 'weight' in item:
                    vals['weight'] = max(1, min(100, int(item['weight'])))
                if 'is_must_have' in item:
                    vals['is_must_have'] = bool(item['is_must_have'])
                if 'description' in item:
                    vals['description'] = item['description']
                if 'scoring_guidance' in item:
                    vals['scoring_guidance'] = item['scoring_guidance']
                if vals:
                    criterion.write(vals)

        return {'success': True}

    @http.route(['/rfp/eval/finalize/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_finalize(self, project_id, **kw):
        """Finalize evaluation criteria."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        Project.action_finalize_eval_criteria()
        return {'success': True}

    @http.route(['/rfp/eval/unfinalize/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_unfinalize(self, project_id, **kw):
        """Unlock finalized criteria for editing."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        Project.eval_criteria_status = 'generated'
        return {'success': True}

    @http.route(['/rfp/eval/add/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_add_criterion(self, project_id, name=None, **kw):
        """Add a custom criterion."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        max_seq = max([c.sequence for c in Project.evaluation_criterion_ids] or [0])
        criterion = request.env['rfp.evaluation.criterion'].sudo().create({
            'project_id': Project.id,
            'name': name or 'New Criterion',
            'description': '',
            'scoring_guidance': '',
            'category': 'other',
            'weight': 5,
            'sequence': max_seq + 10,
        })
        return {'success': True, 'id': criterion.id, 'name': criterion.name}

    @http.route(['/rfp/eval/delete/<int:criterion_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_delete_criterion(self, criterion_id, **kw):
        """Delete a criterion."""
        criterion = request.env['rfp.evaluation.criterion'].sudo().browse(criterion_id)
        if not criterion.exists():
            return {'success': False, 'error': 'Not found'}

        Project = criterion.project_id
        if Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        criterion.unlink()
        return {'success': True}

    @http.route(['/rfp/eval/regenerate/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_eval_regenerate(self, project_id, **kw):
        """Restart eval criteria: clear old answers + criteria, reset to not_started."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        try:
            # Clear old eval interview answers
            Project.eval_input_ids.unlink()
            # Clear old criteria
            Project.evaluation_criterion_ids.unlink()
            # Reset status so setup page triggers a fresh interview
            Project.eval_criteria_status = 'not_started'
            return {
                'success': True,
                'redirect_url': f'/rfp/eval/setup/{project_id}'
            }
        except Exception as e:
            _logger.exception("Eval criteria restart failed for project %s", project_id)
            return {'success': False, 'error': str(e)}

    # ========== REQUIRED DOCUMENT ROUTES ==========

    @http.route(['/rfp/required_docs/add/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_required_doc_add(self, project_id, name=None, **kw):
        """Add a new required document type."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        max_seq = max([d.sequence for d in Project.required_document_ids] or [0])
        doc = request.env['rfp.required.document'].sudo().create({
            'project_id': Project.id,
            'name': name or 'New Document',
            'description': '',
            'is_required': True,
            'sequence': max_seq + 10,
        })
        return {'success': True, 'id': doc.id, 'name': doc.name}

    @http.route(['/rfp/required_docs/save/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_required_docs_save(self, project_id, docs=None, **kw):
        """Save/update all required document types."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        if not docs:
            return {'success': False, 'error': 'No data provided'}

        for item in docs:
            doc = request.env['rfp.required.document'].sudo().browse(item.get('id'))
            if doc.exists() and doc.project_id.id == Project.id:
                vals = {}
                if 'name' in item:
                    vals['name'] = item['name']
                if 'description' in item:
                    vals['description'] = item['description']
                if 'accept_types' in item:
                    vals['accept_types'] = item['accept_types']
                if 'is_required' in item:
                    vals['is_required'] = bool(item['is_required'])
                if 'sequence' in item:
                    vals['sequence'] = int(item['sequence'])
                if vals:
                    doc.write(vals)

        return {'success': True}

    @http.route(['/rfp/required_docs/delete/<int:doc_id>'], type='json', auth="user", website=True)
    def portal_rfp_required_doc_delete(self, doc_id, **kw):
        """Delete a required document type."""
        doc = request.env['rfp.required.document'].sudo().browse(doc_id)
        if not doc.exists():
            return {'success': False, 'error': 'Not found'}

        Project = doc.project_id
        if Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        doc.unlink()
        return {'success': True}

    # ==================== Project Duplication ====================

    @http.route(['/rfp/duplicate/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_duplicate_project(self, project_id, **kw):
        """Duplicate an existing project for adaptation."""
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id.id != request.env.user.id:
            return {'success': False, 'error': 'Access denied'}

        try:
            new_name = kw.get('new_name', '').strip() or None
            new_project_id = Project.action_duplicate_for_adaptation(new_name=new_name)
            return {
                'success': True,
                'project_id': new_project_id,
                'redirect_url': f'/rfp/interface/{new_project_id}'
            }
        except Exception as e:
            _logger.exception("Failed to duplicate project %s", project_id)
            return {'success': False, 'error': str(e)}

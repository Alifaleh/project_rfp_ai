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
        if Project.current_stage == STAGE_SECTIONS_GENERATED:
             return request.redirect(f"/rfp/structure/{Project.id}")
        elif Project.current_stage == STAGE_GENERATING_CONTENT:
             return request.redirect(f"/rfp/generating/{Project.id}")
        elif Project.current_stage == STAGE_CONTENT_GENERATED:
             return request.redirect(f"/rfp/review/{Project.id}")
        elif Project.current_stage == STAGE_GENERATING_IMAGES:
             return request.redirect(f"/rfp/generating_images/{Project.id}")
        elif Project.current_stage == STAGE_IMAGES_GENERATED:
             return request.redirect(f"/rfp/images_review/{Project.id}")
        elif Project.current_stage == STAGE_DOCUMENT_LOCKED:
             return request.redirect(f"/rfp/document/{Project.id}")
        elif Project.current_stage == STAGE_COMPLETED_WITH_ERRORS:
             return request.redirect(f"/rfp/review/{Project.id}")
        elif Project.current_stage == STAGE_COMPLETED:
             return request.redirect(f"/rfp/document/{Project.id}")

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

    # --- PHASE 2: STRUCTURE REVIEW ---
    @http.route(['/rfp/structure/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_structure(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
        
        if Project.current_stage != STAGE_SECTIONS_GENERATED:
             return request.redirect(f"/rfp/interface/{Project.id}")

        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_structure',
        })
        return request.render("project_rfp_ai.portal_rfp_structure_review", values)

    @http.route(['/rfp/structure/save_and_generate/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_save_structure(self, project_id, sections_data=None, generate=True):
        """
        AJAX Route to save structure and optionally trigger generation.
        sections_data: List of dicts
        generate: bool
        """
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return {'error': 'Access Denied'}
        
        if sections_data:
             Project.action_update_structure(sections_data)
        
        if generate:
            # Trigger Generation
            Project.action_generate_content()
            return {'status': 'success', 'redirect': f'/rfp/generating/{Project.id}'}
        
        return {'status': 'success'}

    # --- PHASE 3: GENERATION STATUS ---
    @http.route(['/rfp/generating/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_generating(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_generating',
        })
        return request.render("project_rfp_ai.portal_rfp_generating", values)
        
    @http.route(['/rfp/status/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_status(self, project_id):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return {'error': 'Access Denied'}
        
        # Trigger status check to update stage if complete
        Project.action_check_generation_status()
        
        # Return progress
        status_data = Project.get_generation_status()
        return status_data

    # --- PHASE 4: CONTENT REVIEW ---
    @http.route(['/rfp/review/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_content_review(self, project_id, **kw):
        """
        This is the "Show all sections with ability to make changes" page.
        """
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        # Ensure we are in writing stage (or completed, but editable?)
        # Let's assume writing stage until verified.
        
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_content_review',
        })
        return request.render("project_rfp_ai.portal_rfp_content_review", values)
        
    @http.route(['/rfp/content/save/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_save_content(self, project_id, sections_content=None, finish=False):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
             return {'error': 'Access Denied'}
             
        if sections_content:
            Project.action_update_content_html(sections_content)
            
        if finish:
            # Transition to Image Generation
            Project.sudo().write({'current_stage': STAGE_GENERATING_IMAGES})
            Project.with_delay().action_generate_diagram_images()
            return {'status': 'success', 'redirect': f'/rfp/generating_images/{Project.id}'}
            
        return {'status': 'success'}

    # --- PHASE 4.5: IMAGE GENERATION & REVIEW ---
    @http.route(['/rfp/generating_images/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_generating_images(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_generating_images',
        })
        return request.render("project_rfp_ai.portal_rfp_generating_images", values)

    @http.route(['/rfp/images_review/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_images_review(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_images_review',
        })
        return request.render("project_rfp_ai.portal_rfp_images_review", values)
        
    @http.route(['/rfp/images/finish/<int:project_id>'], type='json', auth="user", website=True)
    def portal_rfp_images_finish(self, project_id):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
             return {'error': 'Access Denied'}
             
        Project.action_mark_completed()
        return {'status': 'success', 'redirect': f'/rfp/document/{Project.id}'}

    # --- PHASE 5: COMPLETED DOCUMENT ---
    @http.route(['/rfp/document/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_document(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_document',
        })
        return request.render("project_rfp_ai.portal_rfp_document", values)
    
    @http.route(['/rfp/revert_to_edit/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_revert_to_edit(self, project_id, **kw):
        """
        Reverts a completed project back to 'writing' stage and redirects to editor.
        """
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        if Project.current_stage == STAGE_COMPLETED:
            Project.sudo().write({'current_stage': STAGE_CONTENT_GENERATED})
            
        return request.redirect(f"/rfp/review/{Project.id}")

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

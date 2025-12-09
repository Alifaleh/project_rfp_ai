from odoo import http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal

class RfpCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'rfp_count' in counters:
            values['rfp_count'] = request.env['rfp.project'].sudo().search_count([('user_id', '=', request.env.user.id)])
        return values

    @http.route(['/my', '/my/home'], type='http', auth="user", website=True)
    def home(self, **kw):
        values = self._prepare_portal_layout_values()
        # Use sudo() but strictly filter by the current user to ensure data isolation
        Project = request.env['rfp.project'].sudo()
        domain = [('user_id', '=', request.env.user.id)]
        projects = Project.search(domain)
        
        values.update({
            'projects': projects,
            'page_name': 'home',
        })
        return request.render("project_rfp_ai.portal_my_rfps", values)

    # Replaced by home/my but keeping the route just in case links exist, but it can just redirect to home
    @http.route(['/my/rfp', '/my/rfp/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_rfps(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        return request.redirect('/my')

    @http.route(['/my/rfp/start'], type='http', auth="user", website=True)
    def portal_rfp_start(self):
        # This will be the wizard entry point
        return request.render("project_rfp_ai.portal_rfp_wizard_start")

    @http.route(['/rfp/init'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_init(self, **post):
        # Secure Creation
        if post.get('name') and post.get('description'):
            # Create as sudo but perform strictly for the current user
            Project = request.env['rfp.project'].sudo()
            new_project = Project.create({
                'name': post.get('name'),
                'description': post.get('description'),
                'document_language': post.get('document_language', 'en'),
                'user_id': request.env.user.id
            })
            
            # Auto-trigger analysis
            new_project.action_analyze_gap()
            
            # Redirect to the interview interface
            return request.redirect(f"/rfp/interface/{new_project.id}")
        return request.redirect('/my/rfp/start')

    @http.route(['/rfp/interface/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_interface(self, project_id, **kw):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        
        # Security Check: Ensure project exists and belongs to user
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')
            
        values = self._prepare_portal_layout_values()
        values.update({
            'rfp_project': Project,
            'page_name': 'rfp_interface',
        })
        return request.render("project_rfp_ai.portal_rfp_interface", values)

    @http.route(['/rfp/next_step/<int:project_id>'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_next_step(self, project_id, **post):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')

        # 1. Save Answers
        # Iterate over post keys. If key matches a field_key in inputs, update it.
        # We need to map field_key to input record.
        input_map = {inp.field_key: inp for inp in Project.form_input_ids}
        
        for key, value in post.items():
            # Check for special 'irrelevant' flags
            if key.startswith('is_irrelevant_'):
                base_key = key.replace('is_irrelevant_', '')
                if base_key in input_map and value == 'true':
                    input_map[base_key].sudo().write({'is_irrelevant': True})
                    
            elif key.startswith('irrelevant_reason_'):
                base_key = key.replace('irrelevant_reason_', '')
                if base_key in input_map:
                    input_map[base_key].sudo().write({'irrelevant_reason': value})
                    
            elif key in input_map:
                # Only update user_value if NOT marked irrelevant (or update anyway, but flags take precedence)
                # Handle "Specify" logic
                specify_key = f"{key}_specify"
                final_value = value
                
                if specify_key in post and post.get(specify_key):
                     # Append the custom specification
                     # e.g. "Other: My custom CRM"
                     final_value = f"{value}: {post.get(specify_key)}"

                input_map[key].sudo().write({'user_value': final_value})
        
        # 2. Run Analysis (The AI Cycle)
        Project.action_analyze_gap()
        
        # 3. Check for Redirect (Auto-Finalization)
        if Project.current_stage in ['generating', 'completed']:
             return request.redirect(f"/rfp/document/{Project.id}")
        
        # 4. Reload Interface
        return request.redirect(f"/rfp/interface/{Project.id}")

    @http.route(['/rfp/finish/<int:project_id>'], type='http', auth="user", website=True, methods=['POST'], csrf=True)
    def portal_rfp_finish(self, project_id, **post):
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')

        # Trigger Document Generation
        Project.action_generate_document()
        
        return request.redirect(f"/rfp/document/{Project.id}")

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

    @http.route(['/rfp/report/download/<int:project_id>'], type='http', auth="user", website=True)
    def portal_rfp_report_download(self, project_id, **kw):
        """
        Custom route to download the PDF report using SUPERUSER.
        """
        Project = request.env['rfp.project'].sudo().browse(project_id)
        if not Project.exists() or Project.user_id != request.env.user:
            return request.redirect('/my')

        # Generate PDF using SUPERUSER to bypass all ACLs
        # We must use with_user(SUPERUSER_ID) because .sudo() sometimes isn't enough for Reports if they check context.
        from odoo import SUPERUSER_ID
        report_action = request.env.ref('project_rfp_ai.action_report_rfp_document').with_user(SUPERUSER_ID)
        pdf_content, _ = report_action._render_qweb_pdf(report_action.id, [project_id])
        
        pdfhttpheaders = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_content)),
            ('Content-Disposition', f'attachment; filename="RFP - {Project.name}.pdf"'),
        ]
        return request.make_response(pdf_content, headers=pdfhttpheaders)


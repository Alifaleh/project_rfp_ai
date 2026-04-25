# -*- coding: utf-8 -*-
from odoo import fields, models


class RfpGlossaryTerm(models.Model):
    _name = 'rfp.glossary.term'
    _inherit = 'rfp.glossary.term.mixin'
    _description = 'RFP Project Glossary Term'

    project_id = fields.Many2one(
        comodel_name='rfp.project',
        string='Project',
        required=True,
        ondelete='cascade',
        index=True,
    )

    _sql_constraints = [
        (
            'unique_term_per_project',
            'UNIQUE(project_id, name)',
            'Term must be unique within a project.',
        ),
    ]

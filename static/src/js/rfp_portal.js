/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.RfpPortalInteractions = publicWidget.Widget.extend({
    selector: '.rfp-portal-wrapper', // Simplified to prevent double instantiation on nested matches
    events: {
        // Gap Analysis Events (Standard Odoo events usually work fine here, but manual binding is safer if we see issues)
        'click .btn-suggestion': '_onSuggestionClick',
        'click .btn-irrelevant-toggle': '_onIrrelevantToggle',
        'click .btn-irrelevant-cancel': '_onIrrelevantToggle',
        'click .btn-custom-answer-toggle': '_onCustomAnswerToggle',
        'click .btn-custom-answer-cancel': '_onCustomAnswerToggle',
        'change .rfp-input-group input, .rfp-input-group select, .rfp-input-group textarea': '_onInputChange',
        'submit form': '_onSubmit',

        // Unified Editor Actions
        'click #btn_unified_save': '_onUnifiedSave',
        'click #btn_toggle_lock': '_onToggleLock',
        'click #btn_confirm_lock_action': '_onConfirmLockAction',

        // Section Management
        'click #btn_add_section': '_onAddSection',
        'click .btn-delete-section': '_onDeleteSection',

        // Diagram Management
        'click .btn-upload-diagram-trigger': '_onUploadDiagramTrigger',
        'click #btn_save_diagram': '_onUploadDiagramSubmit',
        'click .btn-delete-diagram': '_onDeleteDiagram',

        // Delete Confirmation
        'click #btn_confirm_delete': '_onConfirmDelete',

        // Image Viewer
        'click .diagram-card img': '_onViewImage',

        // AI Editing
        'click .btn-ai-edit-section': '_onAiEditSection',
        'click .btn-ai-edit-diagram': '_onAiEditDiagram',
        'click #btn_submit_ai_edit': '_onSubmitAiEdit',

        // Export Actions
        'click #btn_publish': '_onExport',
        'click #btn_unpublish': '_onDeleteExport',
        'click #btn_confirm_unpublish': '_onConfirmDeleteExport',
        'click #btn_copy_publish_url': '_onCopyExportUrl',
        'click #btn_copy_editor_url': '_onCopyEditorUrl',
        'click #btn_copy_proposals_url': '_onCopyProposalsUrl',

        // Evaluation Criteria Review
        'click #btn_save_criteria': '_onSaveCriteria',
        'click #btn_finalize_criteria': '_onFinalizeCriteria',
        'click #btn_add_criterion': '_onAddCriterion',
        'click .btn-delete-criterion': '_onDeleteCriterion',
        'input .criterion-weight-slider': '_onWeightSliderChange',
        'click #btn_regenerate_criteria': '_onRegenerateCriteria',
        'click #btn_unfinalize_criteria': '_onUnfinalizeCriteria',
        'click #btn_eval_confirm_action': '_onEvalConfirmAction',

        // Required Documents CRUD
        'click #btn_add_rdoc': '_onAddRequiredDoc',
        'click .btn-delete-rdoc': '_onDeleteRequiredDoc',
        'click #btn_save_rdocs': '_onSaveRequiredDocs',

        // Project Duplication
        'click .btn-duplicate-project': '_onDuplicateProject',
        'click #btn_confirm_duplicate': '_onConfirmDuplicate',

        // Upload Existing RFP
        'click .btn-upload-rfp': '_onUploadRfpClick',
        'change #rfp_upload_file': '_onUploadFileChange',
        'click #btn_confirm_upload': '_onConfirmUpload',
        'click #btn_retry_upload': '_onRetryUpload',

        // Auto-Fill Review
        'click .btn-clear-autofill': '_onClearAutofill',

        // Upload Proposal (Vendor Proposals)
        'click .btn-upload-proposal': '_onUploadProposalClick',
        'click #btn_confirm_proposal_upload': '_onConfirmProposalUpload',
        'click #btn_retry_proposal_upload': '_onRetryProposalUpload',
    },

    // Custom RPC implementation to avoid module dependency issues in frontend
    _rpc: async function (options) {
        const response = await fetch(options.route, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: options.params || {},
                id: Math.floor(Math.random() * 1000000000)
            })
        });

        if (!response.ok) {
            throw new Error("HTTP error " + response.status);
        }

        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data ? data.error.data.message : data.error.message);
        }
        return data.result;
    },

    start: function () {
        this._super.apply(this, arguments);

        var self = this;

        // Proposal upload modal: document-level delegated change events
        // (Bootstrap modals can break widget-scoped event delegation)
        $(document).on('change.rfpProposalUpload', '#modal_upload_proposal .proposal-doc-file, #modal_upload_proposal #proposal_upload_file', function (e) {
            var file = e.target.files[0];
            var $modal = $('#modal_upload_proposal');
            if (file && file.size > 25 * 1024 * 1024) {
                $modal.find('#proposal_file_error').text('File too large (max 25 MB): ' + file.name).removeClass('d-none');
                e.target.value = '';
            } else {
                $modal.find('#proposal_file_error').addClass('d-none');
            }
            self._validateProposalFiles();
        });

        // 3. Drag and Drop (Native Events)
        // We bind native events to a container (e.g. tbody)
        const list = this.el.querySelector('#rfp_section_list');
        if (list) {
            list.addEventListener('dragstart', this._onDragStart.bind(this), false);
            list.addEventListener('dragover', this._onDragOver.bind(this), false);
            list.addEventListener('drop', this._onDrop.bind(this), false);
            list.addEventListener('dragleave', this._onDragLeave.bind(this), false);
            list.addEventListener('dragend', this._onDragEnd.bind(this), false);
        }

        // Initial checks for Gap Analysis
        if (this.$('.rfp-input-group').length) {
            this._checkDependencies();
            this._checkSpecifyTriggers();
        }

        // Auto-Start Polling if on Generating Page
        if (this.$('#rfp_generation_progress').length) {
            this._startGenerationPolling();
        }

        // Initialize Quill Editors
        this._initQuillEditors();
    },

    // --- PHASE 2: STRUCTURE EDITOR ---

    _onAddSection: function (ev) {
        ev.preventDefault();
        const $list = this.$('#rfp_section_list');
        const $template = this.$('#section_template_clone').children().first().clone();

        if (!$template.length) {
            console.error("Template not found");
            return;
        }

        // Generate Temp ID
        const tempId = `new_${Date.now()}`;
        $template.attr('data-section-id', tempId);

        // Append
        $list.append($template);

        // Initialize Quill for this new section
        const $editorContainer = $template.find('.rfp-quill-editor');
        $editorContainer.attr('id', `editor_${tempId}`);

        // We need to re-init Quill for this new element
        this._initQuillElement($editorContainer[0], tempId);

        // Scroll to new section
        if ($template[0] && typeof $template[0].scrollIntoView === 'function') {
            $template[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    },

    _onDeleteSection: function (ev) {
        ev.preventDefault();
        const $section = $(ev.currentTarget).closest('.rfp-section-block');
        const sectionId = $section.data('section-id');

        // Set modal data
        this.$('#delete_confirm_title').text('Delete Section?');
        this.$('#delete_confirm_message').text('This section and its content will be permanently removed.');
        this.$('#delete_target_type').val('section');
        this.$('#delete_target_id').val(sectionId);

        // Show modal
        $('#modal_delete_confirm').modal('show');
    },

    // Drag and Drop Handlers
    _onDragStart: function (ev) {
        // Check target (now .rfp-section-block)
        const target = ev.target.closest('.rfp-section-block');
        if (!target) return;

        this.draggedRow = target;
        ev.dataTransfer.effectAllowed = 'move';
        // Simple visual feedback
        target.classList.add('opacity-50', 'border-primary');
    },

    _onDragOver: function (ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';

        // --- Auto Scroll Logic ---
        const scrollThreshold = 100; // px from edge
        const scrollSpeed = 20;

        if (ev.clientY < scrollThreshold) {
            // Scroll Up
            window.scrollBy(0, -scrollSpeed);
        } else if ((window.innerHeight - ev.clientY) < scrollThreshold) {
            // Scroll Down
            window.scrollBy(0, scrollSpeed);
        }
        // -------------------------

        const targetRow = ev.target.closest('.rfp-section-block');
        if (targetRow && targetRow !== this.draggedRow) {
            this._clearDragVisuals();

            if (this._isBefore(this.draggedRow, targetRow)) {
                // Dragging UP (Target is above Dragged) -> Place BEFORE Target
                targetRow.style.borderTop = "4px solid #0dcaf0";
            } else {
                // Dragging DOWN (Target is below Dragged) -> Place AFTER Target
                targetRow.style.borderBottom = "4px solid #0dcaf0";
            }
            targetRow.classList.add('rfp-drop-target');
        }
    },

    _onDragLeave: function (ev) {
        // Optional cleanup
    },

    _onDragEnd: function (ev) {
        this._clearDragVisuals();
        if (this.draggedRow) {
            this.draggedRow.classList.remove('opacity-50', 'border-primary');
            this.draggedRow = null;
        }
    },

    _clearDragVisuals: function () {
        // Iterate all rows and remove styles
        const rows = this.el.querySelectorAll('.rfp-section-block');
        rows.forEach(r => {
            r.style.borderTop = "";
            r.style.borderBottom = "";
            r.classList.remove('rfp-drop-target');
        });
    },

    _onDrop: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this._clearDragVisuals();

        const targetRow = ev.target.closest('.rfp-section-block');
        if (this.draggedRow && targetRow && this.draggedRow !== targetRow) {
            // Check position
            if (this._isBefore(this.draggedRow, targetRow)) {
                // Dragging UP -> Insert Before
                targetRow.parentNode.insertBefore(this.draggedRow, targetRow);
            } else {
                // Dragging DOWN -> Insert After
                targetRow.parentNode.insertBefore(this.draggedRow, targetRow.nextSibling);
            }
        }
    },

    _isBefore: function (el1, el2) {
        if (el2.parentNode === el1.parentNode) {
            for (let cur = el1.previousSibling; cur; cur = cur.previousSibling) {
                if (cur === el2) return true;
            }
        }
        return false;
    },

    // Unified Save Function logic
    _saveStructure: async function (projectId, generate) {
        // 1. Collect Data & Recalculate Sequence
        const sections = [];
        let seqCounter = 10;

        this.$('.rfp-section-row').each(function () {
            const $row = $(this);
            const id = $row.data('section-id'); // int or "new_..."
            const title = $row.find('.section-title').val() || "New Section";

            // Overwrite stored sequence with new position-based sequence
            sections.push({
                id: id,
                sequence: seqCounter,
                section_title: title
            });
            seqCounter += 10;
        });

        if (!sections.length) {
            alert("You must have at least one section.");
            return null;
        }

        return await this._rpc({
            route: `/rfp/structure/save_and_generate/${projectId}`,
            params: {
                sections_data: sections,
                generate: generate
            }
        });
    },

    _onSaveStructure: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = this.$('#rfp_structure_editor').data('project-id');
        const originalText = $btn.html();

        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        try {
            const result = await this._saveStructure(projectId, false);
            if (result && result.status === 'success') {
                // Update IDs if necessary?
                // Ideally we'd replace the rows with returned clean IDs but reloading is simpler if we want to be pure.
                // For now, simple success feedback.
                $btn.addClass('btn-success').removeClass('btn-secondary');
                setTimeout(() => {
                    $btn.removeClass('btn-success').addClass('btn-secondary').html(originalText).prop('disabled', false);
                    // Reload to get real IDs? Not strictly needed for UX unless they delete immediately.
                    // A reload is safer to sync IDs.
                    window.location.reload();
                }, 1000);
            } else {
                alert("Error saving.");
                $btn.prop('disabled', false).html(originalText);
            }
        } catch (e) {
            console.error(e);
            $btn.prop('disabled', false).html(originalText);
        }
    },

    _onConfirmStructure: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = this.$('#rfp_structure_editor').data('project-id');

        // Disable Button
        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        // RPC Call
        try {
            const result = await this._saveStructure(projectId, true);

            if (result && result.status === 'success') {
                window.location.href = result.redirect;
            } else {
                alert("Error saving: " + (result ? result.error : 'Unknown'));
                $btn.prop('disabled', false).text('Generate Content');
            }
        } catch (e) {
            console.error(e);
            alert("Connection Error");
            $btn.prop('disabled', false).text('Generate Content');
        }
    },

    // --- PHASE 2: UNIFIED PROCESSING POLLING ---

    _startGenerationPolling: function () {
        const $progressBar = this.$('#rfp_generation_progress');
        if (!$progressBar.length) return;

        const projectId = $progressBar.data('project-id');
        const self = this;
        const $statusText = this.$('#rfp_status_text');

        // Steps
        const $stepStructure = this.$('#step_structure');
        const $stepContent = this.$('#step_content');
        const $stepImages = this.$('#step_images');

        const interval = setInterval(async () => {
            try {
                const result = await self._rpc({
                    route: `/rfp/status/${projectId}`,
                    params: {}
                });

                // Status Map for Steps
                // We need to map `result.stage` (e.g., 'generating_content') to our steps
                const stage = result.stage;
                // Stages: sections_generated, generating_content, content_generated, generating_images, images_generated, completed...

                // Helper to set step status
                const setStep = ($el, state) => {
                    const $badge = $el.find('.status-badge');
                    if (state === 'done') {
                        $badge.removeClass('bg-secondary bg-primary').addClass('bg-success').text('Completed');
                        $el.addClass('list-group-item-success');
                    } else if (state === 'active') {
                        $badge.removeClass('bg-secondary bg-success').addClass('bg-primary').text('In Progress');
                        $el.removeClass('list-group-item-success').addClass('list-group-item-light');
                    } else {
                        $badge.removeClass('bg-success bg-primary').addClass('bg-secondary').text('Pending');
                        $el.removeClass('list-group-item-success list-group-item-light');
                    }
                };

                // Logic to update steps based on stage
                // 1. Structure
                // Structure is instantaneous usually, so it's likely done if we are here? 
                // Actually `sections_generated` means it IS done.
                if (['sections_generated', 'generating_content', 'content_generated', 'generating_images', 'images_generated', 'completed', 'document_locked'].includes(stage)) {
                    setStep($stepStructure, 'done');
                } else {
                    setStep($stepStructure, 'active');
                }

                // 2. Content
                if (['content_generated', 'generating_images', 'images_generated', 'completed', 'document_locked'].includes(stage)) {
                    setStep($stepContent, 'done');
                } else if (stage === 'generating_content') {
                    setStep($stepContent, 'active');
                    $statusText.text("Writing granular content for each section...");
                } else if (stage === 'sections_generated') {
                    // It might be waiting to pick up job
                    setStep($stepContent, 'active');
                } else {
                    setStep($stepContent, 'pending');
                }

                // 3. Images
                if (['images_generated', 'completed', 'document_locked'].includes(stage)) {
                    setStep($stepImages, 'done');
                } else if (stage === 'generating_images') {
                    setStep($stepImages, 'active');
                    $statusText.text("Generating architectural diagrams...");
                } else {
                    setStep($stepImages, 'pending');
                }

                // Global Progress Bar
                let pct = 0;
                const jobProgress = result.progress || 0; // 0-100 from backend

                if (['sections_generated'].includes(stage)) {
                    // Just started
                    pct = 20;
                } else if (stage === 'generating_content') {
                    // Structure (20) + Content Portion (50 * job_progress)
                    pct = 20 + (jobProgress * 0.5);
                } else if (['content_generated'].includes(stage)) {
                    // Structure (20) + Content (50) Done
                    pct = 70;
                } else if (stage === 'generating_images') {
                    // Structure (20) + Content (50) + Images Portion (30 * job_progress)
                    pct = 70 + (jobProgress * 0.3);
                } else if (['images_generated', 'completed', 'document_locked'].includes(stage)) {
                    pct = 100;
                }

                // Ensure int
                pct = Math.round(pct);
                $progressBar.css('width', pct + '%').text(pct + '%');

                // Completion Redirect
                if (['images_generated', 'completed', 'document_locked'].includes(stage)) {
                    clearInterval(interval);
                    $progressBar.removeClass('progress-bar-animated').addClass('bg-success');
                    $statusText.text("All Done! Redirecting to Editor...");

                    setTimeout(() => {
                        window.location.href = `/rfp/edit/${projectId}`;
                    }, 1000);
                }
            } catch (e) {
                console.error("Polling error", e);
            }
        }, 2000); // 2 seconds
    },

    // --- PHASE 3: UNIFIED EDITOR ---

    _initQuillEditors: function () {
        if (typeof Quill === 'undefined') return;

        this.quillInstances = {};
        const self = this;

        // Unified Editor uses same class .rfp-quill-editor
        this.$('.rfp-quill-editor').each(function () {
            self._initQuillElement(this);
        });
    },

    _initQuillElement: function (el, explicitId = null) {
        if (!el) return;
        const $el = $(el);
        // If explicitId is provided, use it, otherwise parse from ID
        // Note: New sections have data-section-id attribute or we rely on ID

        let sectionId = explicitId;
        if (!sectionId) {
            const idAttr = $el.attr('id'); // editor_123
            if (idAttr) sectionId = idAttr.replace('editor_', '');
        }

        if (!sectionId) return;

        const toolbarOptions = [
            [{ 'header': [2, 3, false] }],
            ['bold', 'italic', 'underline', 'strike'],
            [{ 'list': 'ordered' }, { 'list': 'bullet' }],
            ['clean']
        ];

        // Prevent double init
        if (this.quillInstances[sectionId]) return;

        const quill = new Quill(el, {
            theme: 'snow',
            modules: {
                toolbar: toolbarOptions
            }
        });

        this.quillInstances[sectionId] = quill;

        // Check lock state
        if (this.$('#btn_toggle_lock[data-locked="false"]').length) {
            quill.disable();
        }
    },

    _onUnifiedSave: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = $btn.data('project-id');
        const originalText = $btn.html();

        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i> Saving...');

        // 1. Collect Structure (Order + Titles)
        const sectionsData = [];
        let seqCounter = 10;

        this.$('.rfp-section-block').each(function () {
            const $block = $(this);
            const id = $block.data('section-id');
            const title = $block.find('.section-title-input').val();

            sectionsData.push({
                id: id,
                sequence: seqCounter,
                section_title: title
            });
            seqCounter += 10;
        });

        // 2. Collect Content (Quill)
        const contentData = {};
        if (this.quillInstances) {
            for (const [sectionId, quill] of Object.entries(this.quillInstances)) {
                contentData[sectionId] = quill.root.innerHTML;
            }
        }

        try {
            const result = await this._rpc({
                route: `/rfp/unified/save/${projectId}`,
                params: {
                    structure_data: sectionsData,
                    content_data: contentData
                }
            });

            if (result.status === 'success') {
                $btn.addClass('btn-success').removeClass('btn-primary').html('<i class="fa fa-check"/> Saved');
                setTimeout(() => {
                    $btn.removeClass('btn-success').addClass('btn-primary').html(originalText).prop('disabled', false);
                }, 1500);
            } else {
                alert("Error saving: " + (result.error || 'Unknown'));
                $btn.prop('disabled', false).html(originalText);
            }
        } catch (e) {
            console.error(e);
            alert("Connection Error");
            $btn.prop('disabled', false).html(originalText);
        }
    },

    _onToggleLock: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const isLocking = $btn.data('locked');

        // Store project ID on modal for the confirm action
        const projectId = $btn.data('project-id');
        this.$('#btn_confirm_lock_action').data('project-id', projectId);
        this.$('#btn_confirm_lock_action').data('is-locking', isLocking);

        if (isLocking) {
            // Show Custom Modal using jQuery
            $('#modal_lock_confirm').modal('show');
        } else {
            // Unlocking happens immediately
            this._performLockToggle(projectId, false);
        }
    },

    _onConfirmLockAction: function (ev) {
        const $btn = $(ev.currentTarget);
        const projectId = $btn.data('project-id');
        const isLocking = $btn.data('is-locking');

        // Hide Modal using jQuery
        $('#modal_lock_confirm').modal('hide');

        this._performLockToggle(projectId, isLocking);
    },

    _performLockToggle: async function (projectId, isLocking) {
        try {
            const result = await this._rpc({
                route: '/rfp/lock_toggle',
                params: {
                    project_id: projectId
                } // Route now handles toggle/logic internally or we send param. 
                // Updated route signature is `portal_rfp_lock_toggle(project_id)`
            });

            if (result.success) {
                window.location.reload();
            }
        } catch (e) {
            console.error(e);
            alert("Error updating lock status");
        }
    },

    // --- Image Management ---

    // --- Image Management ---

    _onUploadDiagramTrigger: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const sectionId = $btn.data('section-id');

        // Check if section is new (unsaved)
        if (String(sectionId).startsWith('new_')) {
            alert("Please save the section first before adding images.");
            return;
        }

        // Set Hidden Input
        this.$('#upload_section_id').val(sectionId);

        // Reset Form
        const form = document.getElementById('form_upload_diagram');
        if (form) form.reset();

        // Show Modal using jQuery
        $('#modal_upload_diagram').modal('show');
    },

    _onUploadDiagramSubmit: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const originalText = $btn.html();

        // Validate
        const title = this.$('#upload_diagram_title').val();
        // Use native checks or simple logic
        if (!title || !this.$('#upload_diagram_file').val()) {
            alert("Please fill required fields (Title and File)");
            return;
        }

        const sectionId = this.$('#upload_section_id').val();
        const fileInput = this.$('#upload_diagram_file')[0];
        const description = this.$('#upload_diagram_desc').val();

        $btn.html('<i class="fa fa-spinner fa-spin"></i> <span>Uploading...</span>').prop('disabled', true);

        try {
            const formData = new FormData();
            formData.append('csrf_token', odoo.csrf_token);
            formData.append('section_id', sectionId);
            formData.append('image_file', fileInput.files[0]);
            formData.append('title', title);
            formData.append('description', description);

            const response = await fetch('/rfp/diagram/upload', {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            if (result.success) {
                // Append to container
                let $container = $(`#diagrams-container-${sectionId}`);
                // Use fallback search if ID not found (e.g. if we are in a context where ID is generated)
                if (!$container.length) {
                    // Try to find section block by ID then find container inside
                    const $section = this.$(`.rfp-section-block[data-section-id="${sectionId}"]`);
                    $container = $section.find('.diagrams-container');
                }

                const cardHtml = `
                    <div class="col-md-4 col-sm-6 diagram-wrapper" data-diagram-id="${result.diagram_id}">
                        <div class="card h-100 border-0 shadow-sm diagram-card">
                            <div class="position-relative">
                                <img src="${result.image_url}" class="card-img-top object-fit-cover" style="height: 150px; cursor: pointer;" alt="${result.title}">
                                <div class="position-absolute top-0 end-0 p-2">
                                    <button class="btn btn-sm btn-light text-danger shadow-sm btn-delete-diagram" data-diagram-id="${result.diagram_id}" title="Delete Image">
                                        <i class="fa fa-trash"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="card-body p-2">
                                <h6 class="card-title text-truncate mb-1 small fw-bold" title="${result.title}">${result.title}</h6>
                                <p class="card-text small text-muted text-truncate mb-0" title="${result.description}">
                                    ${result.description}
                                </p>
                            </div>
                        </div>
                    </div>
                `;
                $container.append(cardHtml);

                // Hide Modal using jQuery
                $('#modal_upload_diagram').modal('hide');

            } else {
                alert("Upload failed: " + result.error);
            }
        } catch (e) {
            console.error(e);
            alert("Upload error");
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _onDeleteDiagram: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const diagramId = $btn.data('diagram-id');

        // Set modal data
        this.$('#delete_confirm_title').text('Delete Image?');
        this.$('#delete_confirm_message').text('This image will be permanently removed.');
        this.$('#delete_target_type').val('diagram');
        this.$('#delete_target_id').val(diagramId);

        // Show modal
        $('#modal_delete_confirm').modal('show');
    },

    _onConfirmDelete: async function (ev) {
        ev.preventDefault();
        const targetType = this.$('#delete_target_type').val();
        const targetId = this.$('#delete_target_id').val();

        // Hide modal first
        $('#modal_delete_confirm').modal('hide');

        if (targetType === 'section') {
            // Remove section from DOM
            this.$(`.rfp-section-block[data-section-id="${targetId}"]`).remove();

            // Also remove from quillInstances if it exists
            if (this.quillInstances && this.quillInstances[targetId]) {
                delete this.quillInstances[targetId];
            }
        } else if (targetType === 'diagram') {
            try {
                const result = await this._rpc({
                    route: `/rfp/diagram/delete/${targetId}`,
                    params: {}
                });

                if (result.success) {
                    this.$(`.diagram-wrapper[data-diagram-id="${targetId}"]`).remove();
                } else {
                    alert("Could not delete: " + (result.error || 'Unknown error'));
                }
            } catch (e) {
                console.error(e);
                alert("Delete error");
            }
        }
    },

    _onViewImage: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();

        const $img = $(ev.currentTarget);
        const imgSrc = $img.attr('src');
        const $card = $img.closest('.diagram-wrapper');
        const title = $card.find('.card-title').text() || 'Image Preview';

        // Set modal content
        this.$('#image_viewer_title').text(title);
        this.$('#image_viewer_img').attr('src', imgSrc);
        this.$('#image_viewer_download').attr('href', imgSrc).attr('download', title + '.png');

        // Show modal
        $('#modal_image_viewer').modal('show');
    },

    // --- AI EDITING ---

    _onAiEditSection: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const sectionId = $btn.data('section-id');

        // Set modal context
        this.$('#ai_edit_context_label').text('Describe how you want to modify the section content:');
        this.$('#ai_edit_prompt').val('').attr('placeholder', 'E.g., Make it more formal, add bullet points, focus on security aspects...');
        this.$('#ai_edit_type').val('section');
        this.$('#ai_edit_target_id').val(sectionId);

        // Show modal
        $('#modal_ai_edit').modal('show');
    },

    _onAiEditDiagram: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const $btn = $(ev.currentTarget);
        const diagramId = $btn.data('diagram-id');

        // Set modal context
        this.$('#ai_edit_context_label').text('Describe how you want to modify the image:');
        this.$('#ai_edit_prompt').val('').attr('placeholder', 'E.g., Add more details, change colors to blue, add a legend...');
        this.$('#ai_edit_type').val('diagram');
        this.$('#ai_edit_target_id').val(diagramId);

        // Show modal
        $('#modal_ai_edit').modal('show');
    },

    _onSubmitAiEdit: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const originalText = $btn.html();

        const editType = this.$('#ai_edit_type').val();
        const targetId = this.$('#ai_edit_target_id').val();
        const userPrompt = this.$('#ai_edit_prompt').val().trim();

        if (!userPrompt) {
            this._showNotification('error', 'Missing Input', 'Please enter instructions for the AI.');
            return;
        }

        $btn.html('<i class="fa fa-spinner fa-spin"></i> <span>Processing...</span>').prop('disabled', true);

        try {
            let route, params;

            if (editType === 'section') {
                route = '/rfp/ai/edit/text';
                params = { section_id: targetId, user_prompt: userPrompt };
            } else if (editType === 'diagram') {
                route = '/rfp/ai/edit/image';
                params = { diagram_id: targetId, user_prompt: userPrompt };
            } else {
                throw new Error('Invalid edit type');
            }

            const result = await this._rpc({ route: route, params: params });

            if (result.success) {
                // Hide modal
                $('#modal_ai_edit').modal('hide');

                if (editType === 'section') {
                    // Update Quill editor content
                    if (this.quillInstances && this.quillInstances[targetId]) {
                        this.quillInstances[targetId].root.innerHTML = result.new_content;
                    } else {
                        // Fallback: update DOM directly
                        const $editor = this.$(`.rfp-section-block[data-section-id="${targetId}"] .rfp-quill-editor`);
                        $editor.html(result.new_content);
                    }
                } else if (editType === 'diagram') {
                    // Update image src with cache buster
                    const $img = this.$(`.diagram-wrapper[data-diagram-id="${targetId}"] img`);
                    $img.attr('src', result.new_image_url);
                }

                // Show success feedback
                this._showNotification('success', 'AI Edit Applied', 'Your content has been updated successfully.');

            } else {
                this._showNotification('error', 'AI Edit Failed', result.error || 'Unknown error');
            }
        } catch (e) {
            console.error(e);
            this._showNotification('error', 'Error', 'Error processing AI edit: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _showNotification: function (type, title, message) {
        const $icon = this.$('#notification_icon');
        const $title = this.$('#notification_title');
        const $message = this.$('#notification_message');

        // Set icon based on type
        if (type === 'success') {
            $icon.removeClass().addClass('fa fa-check-circle fa-3x text-success');
        } else if (type === 'error') {
            $icon.removeClass().addClass('fa fa-times-circle fa-3x text-danger');
        } else {
            $icon.removeClass().addClass('fa fa-info-circle fa-3x text-primary');
        }

        $title.text(title);
        $message.text(message);

        $('#modal_notification').modal('show');
    },

    // --- FORM SUBMIT (show loading overlay) ---

    _onSubmit: function (ev) {
        // Show loading overlay on any form submit within the portal
        const $overlay = this.$('#rfp_loading_overlay');
        if ($overlay.length) {
            $overlay.removeClass('d-none');
        }
        // Let form submit normally
    },

    // --- SUGGESTION CLICK ---

    _onSuggestionClick: function (ev) {
        ev.preventDefault();
        const $suggestion = $(ev.currentTarget);
        const value = $suggestion.data('value');
        const targetKey = $suggestion.data('target');

        // Find the target input or textarea
        const $input = this.$(`[name="${targetKey}"]`);

        if ($input.length) {
            const currentVal = $input.val().trim();
            if (currentVal) {
                // Append with comma separator
                $input.val(currentVal + ', ' + value);
            } else {
                // Set value
                $input.val(value);
            }
            // Trigger change event
            $input.trigger('change');
        }
    },

    // --- IRRELEVANT TOGGLE ---

    _onIrrelevantToggle: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const targetId = $btn.data('target');
        const $box = this.$(`#${targetId}`);
        const $group = $box.closest('.rfp-input-group');
        const $flag = $box.find('.irrelevant-flag');

        if ($box.hasClass('d-none')) {
            // Show the irrelevant box
            $box.removeClass('d-none');
            $flag.val('true');
            // Disable other inputs in the group
            $group.find('input:not(.irrelevant-flag), select, textarea').not($box.find('input')).prop('disabled', true);
        } else {
            // Hide the irrelevant box
            $box.addClass('d-none');
            $flag.val('false');
            // Re-enable inputs
            $group.find('input, select, textarea').prop('disabled', false);
        }
    },

    // --- CUSTOM ANSWER TOGGLE ---

    _onCustomAnswerToggle: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const targetId = $btn.data('target');
        const $box = this.$(`#${targetId}`);
        const $group = $box.closest('.rfp-input-group');
        const $flag = $box.find('.custom-answer-flag');

        if ($box.hasClass('d-none')) {
            // Show the custom answer box
            $box.removeClass('d-none');
            $flag.val('true');
            // Disable other inputs in the group (except the custom answer input)
            $group.find('input:not(.custom-answer-flag), select, textarea').not($box.find('input')).prop('disabled', true);
        } else {
            // Hide the custom answer box
            $box.addClass('d-none');
            $flag.val('false');
            // Re-enable inputs
            $group.find('input, select, textarea').prop('disabled', false);
        }
    },

    // --- DEPENDENCY & SPECIFY TRIGGER CHECKS ---

    _checkDependencies: function () {
        const self = this;
        this.$('.rfp-input-group').each(function () {
            const $group = $(this);
            const raw = $group.data('depends-on');
            let dep = {};
            try {
                dep = typeof raw === 'string' ? JSON.parse(raw) : (raw || {});
            } catch (e) {
                dep = {};
            }

            if (dep.field_key && dep.value) {
                const $parent = self.$(`[name="${dep.field_key}"]`);
                const parentVal = $parent.filter(':checked').val() || $parent.val();
                const $inputs = $group.find('input, select, textarea');
                if (parentVal !== dep.value) {
                    $group.addClass('d-none');
                    // Disable hidden inputs so browser validation skips them
                    $inputs.prop('disabled', true);
                } else {
                    $group.removeClass('d-none');
                    $inputs.prop('disabled', false);
                }
            }
        });
    },

    _checkSpecifyTriggers: function () {
        const self = this;
        this.$('.rfp-input-group').each(function () {
            const $group = $(this);
            const rawTriggers = $group.data('specify-triggers');
            let specifyTriggers = [];
            try {
                specifyTriggers = typeof rawTriggers === 'string' ? JSON.parse(rawTriggers) : (rawTriggers || []);
            } catch (e) {
                specifyTriggers = [];
            }

            if (!specifyTriggers.length) return;

            const fieldKey = $group.data('field-key');
            const $input = self.$(`[name="${fieldKey}"]`);
            const value = $input.filter(':checked').val() || $input.val();
            const $specifyInput = $group.find('.rfp-specify-input');

            if ($specifyInput.length) {
                if (specifyTriggers.includes(value)) {
                    $specifyInput.removeClass('d-none');
                } else {
                    $specifyInput.addClass('d-none').val('');
                }
            }
        });
    },

    // --- INPUT CHANGE (for dependency logic) ---

    _onInputChange: function (ev) {
        this._checkDependencies();
        this._checkSpecifyTriggers();
    },

    // --- EXPORT/DELETE EXPORT ---

    _onExport: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = $btn.data('project-id');
        const isUpdate = $btn.data('is-update') === 'true';
        const originalText = $btn.html();

        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Exporting...').prop('disabled', true);

        try {
            const result = await this._rpc({
                route: `/rfp/export/${projectId}`,
                params: {}
            });

            if (result.success) {
                // Show export success modal with URL and copy button
                this._showExportSuccessModal(isUpdate ? 'Re-Exported!' : 'Exported!', result.url);
            } else {
                this._showNotification('error', 'Error', result.error || 'Failed to export');
            }
        } catch (e) {
            this._showNotification('error', 'Error', 'Failed to export: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _showExportSuccessModal: function (title, url) {
        // Update existing notification modal to show export success
        const $modal = this.$('#modal_publish_success');
        $modal.find('#publish_success_title').text(title);
        $modal.find('#publish_success_url').val(url).attr('data-url', url);
        $modal.find('#link_open_public').attr('href', url);
        $('#modal_publish_success').modal('show');
    },

    _onDeleteExport: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = $btn.data('project-id');

        // Store project ID for confirmation handler
        this.$('#modal_unpublish_confirm').data('project-id', projectId);
        $('#modal_unpublish_confirm').modal('show');
    },

    _onConfirmDeleteExport: async function (ev) {
        ev.preventDefault();
        const $modal = this.$('#modal_unpublish_confirm');
        const projectId = $modal.data('project-id');
        const $btn = $(ev.currentTarget);
        const originalText = $btn.html();

        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Deleting...').prop('disabled', true);

        try {
            const result = await this._rpc({
                route: `/rfp/delete_export/${projectId}`,
                params: {}
            });

            if (result.success) {
                $('#modal_unpublish_confirm').modal('hide');
                this._showNotification('success', 'Deleted', 'Your RFP export has been deleted.');
                setTimeout(() => window.location.reload(), 1500);
            } else {
                this._showNotification('error', 'Error', result.error || 'Failed to delete export');
            }
        } catch (e) {
            this._showNotification('error', 'Error', 'Failed to delete export: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _onCopyExportUrl: function (ev) {
        const $input = this.$('#publish_success_url');
        const inputEl = $input[0];
        const $btn = $(ev.currentTarget);

        // Select and copy directly from the input
        inputEl.select();
        inputEl.setSelectionRange(0, 99999); // For mobile

        try {
            document.execCommand('copy');
            $btn.html('<i class="fa fa-check me-1"></i> Copied!');
            setTimeout(() => {
                $btn.html('<i class="fa fa-copy me-1"></i> Copy URL');
            }, 2000);
        } catch (err) {
            console.error('Copy failed:', err);
        }
    },

    _onCopyEditorUrl: function (ev) {
        const $input = this.$('#editor_public_url');
        const inputEl = $input[0];
        const $btn = $(ev.currentTarget);

        inputEl.select();
        inputEl.setSelectionRange(0, 99999);

        try {
            document.execCommand('copy');
            $btn.html('<i class="fa fa-check me-1"></i> Copied!');
            setTimeout(() => {
                $btn.html('<i class="fa fa-copy me-1"></i> Copy');
            }, 2000);
        } catch (err) {
            console.error('Copy failed:', err);
        }
    },

    _onCopyProposalsUrl: function (ev) {
        const $input = this.$('#proposals_public_url');
        const inputEl = $input[0];
        const $btn = $(ev.currentTarget);

        inputEl.select();
        inputEl.setSelectionRange(0, 99999);

        try {
            document.execCommand('copy');
            $btn.html('<i class="fa fa-check me-1"></i> Copied!');
            setTimeout(() => {
                $btn.html('<i class="fa fa-copy me-1"></i> Copy');
            }, 2000);
        } catch (err) {
            console.error('Copy failed:', err);
        }
    },

    // ==================== Evaluation Criteria Review ====================

    _getEvalProjectId: function () {
        const $el = this.$('#eval_criteria_container');
        // jQuery .data() camelCases 'project-id' to 'projectId'
        return $el.data('projectId') || $el.data('project-id') || $el.attr('data-project-id');
    },

    // Normalize response: handles both {success: true} and {status: 'success'}
    _isEvalSuccess: function (result) {
        return result && (result.success === true || result.status === 'success');
    },

    _getEvalError: function (result) {
        return (result && (result.error || result.message)) || 'Unknown error';
    },

    _collectCriteriaData: function () {
        const criteria = [];
        this.$('.eval-criterion-card').each(function () {
            const $card = $(this);
            const rawId = $card.data('criterionId') || $card.data('criterion-id') || $card.attr('data-criterion-id');
            criteria.push({
                id: parseInt(rawId, 10),
                name: $card.find('.criterion-name').val(),
                weight: parseInt($card.find('.criterion-weight-slider').val(), 10),
                is_must_have: $card.find('.criterion-must-have').is(':checked'),
                description: $card.find('.criterion-description').val() || '',
                scoring_guidance: $card.find('.criterion-scoring-guidance').val() || '',
            });
        });
        return criteria;
    },

    _updateTotalWeight: function () {
        let total = 0;
        this.$('.criterion-weight-slider').each(function () {
            total += parseInt($(this).val(), 10) || 0;
        });
        const $indicator = this.$('#eval_total_weight');
        $indicator.text(total);

        const $alert = this.$('#eval_weight_alert');
        $alert.removeClass('alert-success alert-warning alert-danger');
        if (total === 100) {
            $alert.addClass('alert-success');
        } else if (total < 100) {
            $alert.addClass('alert-warning');
        } else {
            $alert.addClass('alert-danger');
        }

        const $hint = this.$('#eval_weight_hint');
        if (total === 100) {
            $hint.text('').hide();
        } else {
            $hint.text('(should equal 100)').show();
        }
    },

    _showEvalBanner: function (type, title, message) {
        const $banner = this.$('#eval_status_banner');
        const $icon = this.$('#eval_status_icon');
        const $title = this.$('#eval_status_title');
        const $msg = this.$('#eval_status_message');

        $banner.removeClass('d-none alert-success alert-danger alert-warning alert-info');
        $icon.removeClass();

        if (type === 'success') {
            $banner.addClass('alert-success');
            $icon.addClass('fa fa-2x fa-check-circle text-success me-3');
        } else if (type === 'error') {
            $banner.addClass('alert-danger');
            $icon.addClass('fa fa-2x fa-times-circle text-danger me-3');
        } else {
            $banner.addClass('alert-info');
            $icon.addClass('fa fa-2x fa-info-circle text-info me-3');
        }

        $title.text(title);
        $msg.text(message);

        // Scroll to top so user sees the banner
        $('html, body').animate({ scrollTop: $banner.offset().top - 80 }, 300);

        // Auto-hide success after 5 seconds
        if (type === 'success') {
            setTimeout(() => $banner.fadeOut(400, () => $banner.addClass('d-none').show()), 5000);
        }
    },

    // Custom confirmation modal instead of browser confirm()
    _pendingConfirmCallback: null,

    _showEvalConfirm: function (options) {
        const $modal = $('#modal_eval_confirm');
        const $icon = $modal.find('#eval_confirm_icon');
        const $iconWrap = $modal.find('#eval_confirm_icon_wrap');
        const $title = $modal.find('#eval_confirm_title');
        const $message = $modal.find('#eval_confirm_message');
        const $actionBtn = $modal.find('#btn_eval_confirm_action');

        $icon.removeClass().addClass('fa fa-3x ' + (options.icon || 'fa-question-circle'));
        $iconWrap.css('background', options.iconBg || '#fff3cd');
        $icon.css('color', options.iconColor || '#856404');
        $title.text(options.title || 'Confirm');
        $message.text(options.message || 'Are you sure?');
        $actionBtn
            .text(options.confirmText || 'Confirm')
            .removeClass('btn-danger btn-rfp-gold btn-warning')
            .addClass(options.confirmClass || 'btn-rfp-gold');

        this._pendingConfirmCallback = options.onConfirm || null;
        $modal.modal('show');
    },

    _onEvalConfirmAction: function () {
        $('#modal_eval_confirm').modal('hide');
        if (this._pendingConfirmCallback) {
            this._pendingConfirmCallback();
            this._pendingConfirmCallback = null;
        }
    },

    _onWeightSliderChange: function (ev) {
        const $slider = $(ev.currentTarget);
        let val = parseInt($slider.val(), 10) || 0;

        // Calculate total weight excluding THIS slider
        let otherTotal = 0;
        this.$('.criterion-weight-slider').not($slider).each(function () {
            otherTotal += parseInt($(this).val(), 10) || 0;
        });

        // Ensure total doesn't exceed 100
        if (otherTotal + val > 100) {
            val = Math.max(1, 100 - otherTotal);
            $slider.val(val);
        }

        $slider.closest('.eval-criterion-card').find('.criterion-weight-display').text(val);
        this._updateTotalWeight();
    },

    _onSaveCriteria: async function (ev) {
        const $btn = $(ev.currentTarget);
        const originalText = $btn.html();
        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Saving...').prop('disabled', true);

        try {
            const projectId = this._getEvalProjectId();
            const criteria = this._collectCriteriaData();
            const result = await this._rpc({
                route: '/rfp/eval/save/' + projectId,
                params: { criteria: criteria },
            });
            if (this._isEvalSuccess(result)) {
                this._showEvalBanner('success', 'Changes Saved', 'All evaluation criteria have been saved successfully.');
            } else {
                this._showEvalBanner('error', 'Save Failed', this._getEvalError(result));
            }
        } catch (e) {
            this._showEvalBanner('error', 'Save Failed', 'An error occurred: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _onFinalizeCriteria: function () {
        const self = this;
        this._showEvalConfirm({
            icon: 'fa-lock',
            iconBg: '#d4edda',
            iconColor: '#155724',
            title: 'Finalize Evaluation Criteria?',
            message: 'Once finalized, all new proposals will be scored against these criteria. You can still edit them later.',
            confirmText: 'Save & Finalize',
            confirmClass: 'btn-rfp-gold',
            onConfirm: async function () {
                const $btn = self.$('#btn_finalize_criteria');
                $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Finalizing...').prop('disabled', true);

                try {
                    const projectId = self._getEvalProjectId();
                    const criteria = self._collectCriteriaData();

                    const saveResult = await self._rpc({
                        route: '/rfp/eval/save/' + projectId,
                        params: { criteria: criteria },
                    });
                    if (!self._isEvalSuccess(saveResult)) {
                        self._showEvalBanner('error', 'Save Failed', self._getEvalError(saveResult));
                        $btn.html('<i class="fa fa-check me-1"></i> Finalize Criteria').prop('disabled', false);
                        return;
                    }

                    const result = await self._rpc({
                        route: '/rfp/eval/finalize/' + projectId,
                        params: {},
                    });
                    if (self._isEvalSuccess(result)) {
                        self._showEvalBanner('success', 'Criteria Finalized!', 'All new proposals will now be scored against these criteria.');
                        $btn.html('<i class="fa fa-check me-1"></i> Finalized').addClass('btn-success').removeClass('btn-rfp-gold');
                        setTimeout(() => window.location.reload(), 2000);
                    } else {
                        self._showEvalBanner('error', 'Finalize Failed', self._getEvalError(result));
                        $btn.html('<i class="fa fa-check me-1"></i> Finalize Criteria').prop('disabled', false);
                    }
                } catch (e) {
                    self._showEvalBanner('error', 'Finalize Failed', 'An error occurred: ' + e.message);
                    $btn.html('<i class="fa fa-check me-1"></i> Finalize Criteria').prop('disabled', false);
                }
            }
        });
    },

    _onAddCriterion: async function (ev) {
        const currentTotal = parseInt(this.$('#eval_total_weight').text(), 10) || 0;
        if (currentTotal >= 100) {
            alert("Total weight is already 100. Please reduce weight of existing criteria before adding new ones.");
            return;
        }

        const $btn = $(ev.currentTarget);
        const originalText = $btn.html();
        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Adding...').prop('disabled', true);

        try {
            const projectId = this._getEvalProjectId();
            const result = await this._rpc({
                route: '/rfp/eval/add/' + projectId,
                params: {},
            });
            if (this._isEvalSuccess(result)) {
                // Inject new card matching server-rendered structure exactly
                const newId = result.id;
                const cardHtml =
                    '<div class="card shadow-sm border-0 mb-3 eval-criterion-card" data-criterion-id="' + newId + '">' +
                        '<div class="card-body">' +
                            '<div class="row align-items-center">' +
                                '<div class="col-md-4">' +
                                    '<input type="text" class="form-control form-control-sm fw-bold criterion-name" value="' + (result.name || 'New Criterion') + '"/>' +
                                    '<div class="mt-1">' +
                                        '<span class="badge bg-secondary" style="text-transform: capitalize;">other</span>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="col-md-3">' +
                                    '<label class="form-label small text-muted mb-0">Weight</label>' +
                                    '<div class="d-flex align-items-center gap-2">' +
                                        '<input type="range" class="form-range criterion-weight-slider" min="1" max="100" value="5"/>' +
                                        '<span class="badge bg-rfp-gold criterion-weight-display" style="min-width: 40px;">5</span>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="col-md-2 text-center">' +
                                    '<label class="form-label small text-muted mb-0 d-block">Must-Have</label>' +
                                    '<div class="form-check form-switch d-inline-block">' +
                                        '<input class="form-check-input criterion-must-have" type="checkbox"/>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="col-md-3 text-end">' +
                                    '<button class="btn btn-sm btn-outline-secondary me-1" type="button" data-bs-toggle="collapse" data-bs-target="#detail_new_' + newId + '">' +
                                        '<i class="fa fa-chevron-down"></i>' +
                                    '</button>' +
                                    '<button class="btn btn-sm btn-outline-danger btn-delete-criterion" type="button">' +
                                        '<i class="fa fa-trash"></i>' +
                                    '</button>' +
                                '</div>' +
                            '</div>' +
                            '<div class="collapse show mt-3" id="detail_new_' + newId + '">' +
                                '<div class="bg-light rounded p-3">' +
                                    '<label class="form-label small fw-bold">Description</label>' +
                                    '<textarea class="form-control form-control-sm mb-3 criterion-description" rows="2" placeholder="Describe what this criterion evaluates..."></textarea>' +
                                    '<label class="form-label small fw-bold">Evaluation Guidance</label>' +
                                    '<textarea class="form-control form-control-sm criterion-scoring-guidance" rows="2" placeholder="What constitutes high, medium, and low scores..."></textarea>' +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                    '</div>';

                const $newCard = $(cardHtml);
                this.$('#eval_criteria_container').append($newCard);
                this._updateTotalWeight();
                // Scroll smoothly to new card, then focus the name field
                setTimeout(() => {
                    $('html, body').animate({ scrollTop: $newCard.offset().top - 100 }, 300, () => {
                        $newCard.find('.criterion-name').focus().select();
                    });
                }, 100);
            } else {
                this._showEvalBanner('error', 'Error', this._getEvalError(result));
            }
        } catch (e) {
            this._showEvalBanner('error', 'Error', 'Add failed: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _onDeleteCriterion: function (ev) {
        const self = this;
        const $card = $(ev.currentTarget).closest('.eval-criterion-card');
        const rawId = $card.data('criterionId') || $card.data('criterion-id') || $card.attr('data-criterion-id');
        const criterionId = parseInt(rawId, 10);
        const criterionName = $card.find('.criterion-name').val();

        this._showEvalConfirm({
            icon: 'fa-trash',
            iconBg: '#f8d7da',
            iconColor: '#721c24',
            title: 'Delete Criterion?',
            message: 'Remove "' + criterionName + '" from the evaluation criteria. This cannot be undone.',
            confirmText: 'Delete',
            confirmClass: 'btn-danger',
            onConfirm: async function () {
                try {
                    const result = await self._rpc({
                        route: '/rfp/eval/delete/' + criterionId,
                        params: {},
                    });
                    if (self._isEvalSuccess(result)) {
                        $card.slideUp(300, () => {
                            $card.remove();
                            self._updateTotalWeight();
                        });
                    } else {
                        self._showEvalBanner('error', 'Error', self._getEvalError(result));
                    }
                } catch (e) {
                    self._showEvalBanner('error', 'Error', 'Delete failed: ' + e.message);
                }
            }
        });
    },

    _onRegenerateCriteria: function (ev) {
        const self = this;
        const $btn = $(ev.currentTarget);

        this._showEvalConfirm({
            icon: 'fa-refresh',
            iconBg: '#fff3cd',
            iconColor: '#856404',
            title: 'Restart Evaluation Interview?',
            message: 'This will clear all current criteria and interview answers, then start a fresh evaluation interview from scratch. Any manual edits will be lost.',
            confirmText: 'Restart',
            confirmClass: 'btn-warning',
            onConfirm: async function () {
                const originalText = $btn.html();
                $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Restarting...').prop('disabled', true);

                try {
                    const projectId = self._getEvalProjectId();
                    const result = await self._rpc({
                        route: '/rfp/eval/regenerate/' + projectId,
                        params: {},
                    });
                    if (self._isEvalSuccess(result)) {
                        window.location.href = result.redirect_url || ('/rfp/eval/setup/' + projectId);
                    } else {
                        self._showEvalBanner('error', 'Error', self._getEvalError(result));
                        $btn.html(originalText).prop('disabled', false);
                    }
                } catch (e) {
                    self._showEvalBanner('error', 'Error', 'Restart failed: ' + e.message);
                    $btn.html(originalText).prop('disabled', false);
                }
            }
        });
    },

    _onUnfinalizeCriteria: function () {
        const self = this;
        this._showEvalConfirm({
            icon: 'fa-unlock',
            iconBg: '#fff3cd',
            iconColor: '#856404',
            title: 'Unlock Evaluation Criteria?',
            message: 'This will allow you to edit weights, add/remove criteria, and re-finalize. Existing proposal scores will not change until proposals are re-analyzed.',
            confirmText: 'Unlock',
            confirmClass: 'btn-warning',
            onConfirm: async function () {
                try {
                    const projectId = self._getEvalProjectId();
                    const result = await self._rpc({
                        route: '/rfp/eval/unfinalize/' + projectId,
                        params: {},
                    });
                    if (self._isEvalSuccess(result)) {
                        self._showEvalBanner('success', 'Criteria Unlocked', 'You can now edit the criteria. Remember to finalize when done.');
                        setTimeout(() => window.location.reload(), 1200);
                    } else {
                        self._showEvalBanner('error', 'Error', self._getEvalError(result));
                    }
                } catch (e) {
                    self._showEvalBanner('error', 'Error', 'Unlock failed: ' + e.message);
                }
            }
        });
    },

    // ==================== Required Documents CRUD ====================

    _getReqDocsProjectId: function () {
        var $el = this.$('#required_docs_container');
        return $el.data('projectId') || $el.data('project-id') || $el.attr('data-project-id');
    },

    _onAddRequiredDoc: async function (ev) {
        var $btn = $(ev.currentTarget);
        var originalText = $btn.html();
        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Adding...').prop('disabled', true);

        try {
            var projectId = this._getReqDocsProjectId();
            var result = await this._rpc({
                route: '/rfp/required_docs/add/' + projectId,
                params: {},
            });
            if (result && result.success) {
                var newId = result.id;
                var cardHtml =
                    '<div class="card border mb-2 required-doc-card" data-doc-id="' + newId + '">' +
                        '<div class="card-body py-2 px-3">' +
                            '<div class="row align-items-center">' +
                                '<div class="col-md-3">' +
                                    '<input type="text" class="form-control form-control-sm fw-bold rdoc-name" value="' + (result.name || 'New Document') + '" placeholder="Document name"/>' +
                                '</div>' +
                                '<div class="col-md-3">' +
                                    '<input type="text" class="form-control form-control-sm rdoc-description" value="" placeholder="Description / instructions"/>' +
                                '</div>' +
                                '<div class="col-md-2">' +
                                    '<input type="text" class="form-control form-control-sm rdoc-accept-types" value=".pdf,.doc,.docx" placeholder=".pdf,.doc,.docx"/>' +
                                '</div>' +
                                '<div class="col-md-2 text-center">' +
                                    '<label class="form-label small text-muted mb-0 d-block">Required</label>' +
                                    '<div class="form-check form-switch d-inline-block">' +
                                        '<input class="form-check-input rdoc-required" type="checkbox" checked="checked"/>' +
                                    '</div>' +
                                '</div>' +
                                '<div class="col-md-2 text-end">' +
                                    '<button class="btn btn-sm btn-outline-danger btn-delete-rdoc" type="button">' +
                                        '<i class="fa fa-trash"></i>' +
                                    '</button>' +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                    '</div>';

                var $newCard = $(cardHtml);
                this.$('#required_docs_container').append($newCard);

                // Update count badge
                var count = this.$('.required-doc-card').length;
                this.$('#required_docs_count').text(count);

                // Focus name field
                setTimeout(function () {
                    $newCard.find('.rdoc-name').focus().select();
                }, 100);
            } else {
                this._showNotification('error', 'Error', (result && result.error) || 'Failed to add document type');
            }
        } catch (e) {
            this._showNotification('error', 'Error', 'Add failed: ' + e.message);
        } finally {
            $btn.html(originalText).prop('disabled', false);
        }
    },

    _onDeleteRequiredDoc: async function (ev) {
        var self = this;
        var $card = $(ev.currentTarget).closest('.required-doc-card');
        var docId = $card.data('docId') || $card.data('doc-id') || $card.attr('data-doc-id');

        try {
            var result = await self._rpc({
                route: '/rfp/required_docs/delete/' + docId,
                params: {},
            });
            if (result && result.success) {
                $card.slideUp(300, function () {
                    $card.remove();
                    var count = self.$('.required-doc-card').length;
                    self.$('#required_docs_count').text(count);
                });
            } else {
                self._showNotification('error', 'Error', (result && result.error) || 'Failed to delete');
            }
        } catch (e) {
            self._showNotification('error', 'Error', 'Delete failed: ' + e.message);
        }
    },

    _onSaveRequiredDocs: async function (ev) {
        var $btn = $(ev.currentTarget);
        var originalText = $btn.html();
        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Saving...').prop('disabled', true);

        try {
            var projectId = this._getReqDocsProjectId();
            var docs = [];
            var seqCounter = 10;

            this.$('.required-doc-card').each(function () {
                var $card = $(this);
                var rawId = $card.data('docId') || $card.data('doc-id') || $card.attr('data-doc-id');
                docs.push({
                    id: parseInt(rawId, 10),
                    name: $card.find('.rdoc-name').val(),
                    description: $card.find('.rdoc-description').val() || '',
                    accept_types: $card.find('.rdoc-accept-types').val() || '.pdf,.doc,.docx',
                    is_required: $card.find('.rdoc-required').is(':checked'),
                    sequence: seqCounter,
                });
                seqCounter += 10;
            });

            var result = await this._rpc({
                route: '/rfp/required_docs/save/' + projectId,
                params: { docs: docs },
            });

            if (result && result.success) {
                $btn.addClass('btn-success').removeClass('btn-rfp-gold').html('<i class="fa fa-check me-1"></i> Saved');
                setTimeout(function () {
                    $btn.removeClass('btn-success').addClass('btn-rfp-gold').html(originalText).prop('disabled', false);
                }, 1500);
            } else {
                this._showNotification('error', 'Save Failed', (result && result.error) || 'Unknown error');
                $btn.html(originalText).prop('disabled', false);
            }
        } catch (e) {
            this._showNotification('error', 'Save Failed', 'An error occurred: ' + e.message);
            $btn.html(originalText).prop('disabled', false);
        }
    },

    // ==================== Project Duplication ====================

    _onDuplicateProject: function (ev) {
        ev.preventDefault();
        var $btn = $(ev.currentTarget);
        var projectId = $btn.data('projectId') || $btn.data('project-id') || $btn.attr('data-project-id');
        var projectName = $btn.data('projectName') || $btn.data('project-name') || $btn.attr('data-project-name') || '';

        var $modal = $('#modal_duplicate_confirm');
        $modal.data('project-id', projectId);
        // Pre-fill name field with "Original Name - Copy"
        $modal.find('#duplicate_new_name').val(projectName ? projectName + ' - Copy' : '');
        $modal.modal('show');
    },

    _onConfirmDuplicate: async function (ev) {
        var $modal = $('#modal_duplicate_confirm');
        var projectId = $modal.data('project-id');
        var newName = $modal.find('#duplicate_new_name').val().trim();
        var $btn = $(ev.currentTarget);
        var originalText = $btn.html();

        $btn.html('<i class="fa fa-spinner fa-spin me-1"></i> Creating &amp; pre-filling...').prop('disabled', true);

        try {
            var result = await this._rpc({
                route: '/rfp/duplicate/' + projectId,
                params: { new_name: newName },
            });

            if (result && result.success) {
                $modal.modal('hide');
                if (this._showNotification) {
                    this._showNotification('success', 'Project Duplicated', 'Redirecting to your new project...');
                }
                setTimeout(function () {
                    window.location.href = result.redirect_url;
                }, 500);
            } else {
                $modal.modal('hide');
                if (this._showNotification) {
                    this._showNotification('error', 'Duplication Failed', (result && result.error) || 'Unknown error');
                }
                $btn.html(originalText).prop('disabled', false);
            }
        } catch (e) {
            $modal.modal('hide');
            if (this._showNotification) {
                this._showNotification('error', 'Error', 'Duplication failed: ' + e.message);
            }
            $btn.html(originalText).prop('disabled', false);
        }
    },

    // ==================== Upload Existing RFP ====================

    _onUploadRfpClick: function (ev) {
        ev.preventDefault();
        var $modal = $('#modal_upload_rfp');
        // Reset to form state
        $modal.find('#upload_form_state').removeClass('d-none');
        $modal.find('#upload_processing_state').addClass('d-none');
        $modal.find('#upload_error_state').addClass('d-none');
        $modal.find('#rfp_upload_file').val('');
        $modal.find('#upload_project_name').val('');
        $modal.find('#upload_file_info').addClass('d-none');
        $modal.find('#upload_file_error').addClass('d-none');
        $modal.find('#btn_confirm_upload').prop('disabled', true);
        $modal.modal('show');
    },

    _onUploadFileChange: function (ev) {
        var $input = $(ev.currentTarget);
        var file = $input[0].files[0];
        var $modal = $('#modal_upload_rfp');
        var $info = $modal.find('#upload_file_info');
        var $error = $modal.find('#upload_file_error');
        var $uploadBtn = $modal.find('#btn_confirm_upload');

        $info.addClass('d-none');
        $error.addClass('d-none');
        $uploadBtn.prop('disabled', true);

        if (!file) return;

        // Validate file type
        var ext = file.name.split('.').pop().toLowerCase();
        if (ext !== 'pdf' && ext !== 'docx') {
            $error.removeClass('d-none').find('.alert').text('Invalid file type. Please select a PDF or DOCX file.');
            $input.val('');
            return;
        }

        // Validate file size (25 MB max)
        var maxSize = 25 * 1024 * 1024;
        if (file.size > maxSize) {
            $error.removeClass('d-none').find('.alert').text('File is too large. Maximum size is 25 MB.');
            $input.val('');
            return;
        }

        // Show file info
        var sizeStr = file.size < 1024 * 1024
            ? (file.size / 1024).toFixed(1) + ' KB'
            : (file.size / (1024 * 1024)).toFixed(1) + ' MB';
        $info.removeClass('d-none');
        $modal.find('#upload_file_name').text(file.name);
        $modal.find('#upload_file_size').text('(' + sizeStr + ')');
        $uploadBtn.prop('disabled', false);
    },

    _onConfirmUpload: async function (ev) {
        var self = this;
        var $modal = $('#modal_upload_rfp');
        var fileInput = $modal.find('#rfp_upload_file')[0];
        var file = fileInput.files[0];
        var projectName = $modal.find('#upload_project_name').val().trim();

        if (!file) return;

        // Switch to processing state
        $modal.find('#upload_form_state').addClass('d-none');
        $modal.find('#upload_processing_state').removeClass('d-none');

        try {
            var formData = new FormData();
            formData.append('rfp_file', file);
            formData.append('project_name', projectName);
            formData.append('csrf_token', odoo.csrf_token);

            var response = await fetch('/rfp/upload', {
                method: 'POST',
                body: formData,
            });

            var result = await response.json();

            if (result && result.success) {
                if (self._showNotification) {
                    self._showNotification('success', 'RFP Uploaded', 'Redirecting to your new project...');
                }
                setTimeout(function () {
                    window.location.href = result.redirect_url;
                }, 500);
            } else {
                // Show error state
                $modal.find('#upload_processing_state').addClass('d-none');
                $modal.find('#upload_error_state').removeClass('d-none');
                $modal.find('#upload_error_message').text((result && result.error) || 'An unknown error occurred.');
            }
        } catch (e) {
            $modal.find('#upload_processing_state').addClass('d-none');
            $modal.find('#upload_error_state').removeClass('d-none');
            $modal.find('#upload_error_message').text('Upload failed: ' + e.message);
        }
    },

    _onRetryUpload: function (ev) {
        var $modal = $('#modal_upload_rfp');
        $modal.find('#upload_error_state').addClass('d-none');
        $modal.find('#upload_form_state').removeClass('d-none');
        $modal.find('#rfp_upload_file').val('');
        $modal.find('#upload_file_info').addClass('d-none');
        $modal.find('#btn_confirm_upload').prop('disabled', true);
    },

    // ========== AUTO-FILL REVIEW ==========
    _onClearAutofill: async function (ev) {
        ev.preventDefault();
        var $btn = $(ev.currentTarget);
        var fieldKey = $btn.data('field-key');
        var projectId = $btn.data('project-id');

        if (!fieldKey || !projectId) return;

        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"/>');

        try {
            var result = await this._rpc({
                route: '/rfp/clear_autofill/' + projectId,
                params: { field_key: fieldKey }
            });
            if (result && result.success) {
                window.location.reload();
            } else {
                $btn.prop('disabled', false).html('<i class="fa fa-undo"/>');
            }
        } catch (e) {
            console.error('Failed to clear auto-fill:', e);
            $btn.prop('disabled', false).html('<i class="fa fa-undo"/>');
        }
    },

    // ========== UPLOAD PROPOSAL (VENDOR PROPOSALS) ==========
    _onUploadProposalClick: function (ev) {
        var self = this;
        var projectId = $(ev.currentTarget).data('project-id');
        var $modal = $('#modal_upload_proposal');
        $modal.data('project-id', projectId);
        // Reset states
        $modal.find('#proposal_form_state').removeClass('d-none');
        $modal.find('#proposal_processing_state').addClass('d-none');
        $modal.find('#proposal_error_state').addClass('d-none');
        $modal.find('#proposal_upload_file').val('');
        $modal.find('.proposal-doc-file').each(function () { this.value = ''; });
        $modal.find('#proposal_vendor_name').val('');
        $modal.find('#proposal_file_error').addClass('d-none');
        $modal.find('#btn_confirm_proposal_upload').prop('disabled', true);

        // Clear any previous polling
        if (this._proposalPollId) clearInterval(this._proposalPollId);

        // Poll file inputs every 500ms as fallback for event delegation issues
        this._proposalPollId = setInterval(function () {
            var $m = $('#modal_upload_proposal');
            if (!$m.hasClass('show')) {
                clearInterval(self._proposalPollId);
                self._proposalPollId = null;
                return;
            }
            self._validateProposalFiles();
        }, 500);

        $modal.modal('show');
    },

    _validateProposalFiles: function () {
        var $modal = $('#modal_upload_proposal');
        var $requiredInputs = $modal.find('.proposal-doc-input[data-required="true"]');
        var hasRequiredDocs = $requiredInputs.length > 0;

        if (hasRequiredDocs) {
            var allFilled = true;
            $requiredInputs.each(function () {
                var fileInput = $(this).find('.proposal-doc-file')[0];
                if (!fileInput || !fileInput.files || !fileInput.files.length) {
                    allFilled = false;
                }
            });
            $modal.find('#btn_confirm_proposal_upload').prop('disabled', !allFilled);
        } else {
            // Fallback: single file mode — need at least the main file
            var fileInput = $modal.find('#proposal_upload_file')[0];
            var hasFile = fileInput && fileInput.files && fileInput.files.length > 0;
            $modal.find('#btn_confirm_proposal_upload').prop('disabled', !hasFile);
        }
    },

    _onConfirmProposalUpload: async function (ev) {
        var $modal = $('#modal_upload_proposal');
        var projectId = $modal.data('project-id');
        var vendorName = $modal.find('#proposal_vendor_name').val();

        // Switch to processing state
        $modal.find('#proposal_form_state').addClass('d-none');
        $modal.find('#proposal_processing_state').removeClass('d-none');

        // Build FormData with all files
        var formData = new FormData();
        formData.append('vendor_name', vendorName);
        formData.append('csrf_token', odoo.csrf_token);

        // Add required document files
        $modal.find('.proposal-doc-file').each(function () {
            if (this.files && this.files.length > 0) {
                formData.append(this.name, this.files[0]);
            }
        });

        // Add additional/single proposal file
        var mainFileInput = $modal.find('#proposal_upload_file')[0];
        if (mainFileInput && mainFileInput.files && mainFileInput.files.length > 0) {
            formData.append('proposal_file', mainFileInput.files[0]);
        }

        try {
            var response = await fetch('/rfp/proposal/upload/' + projectId, {
                method: 'POST',
                body: formData
            });
            var result = await response.json();

            if (result.success) {
                $modal.modal('hide');
                window.location.href = result.redirect_url;
            } else {
                $modal.find('#proposal_processing_state').addClass('d-none');
                $modal.find('#proposal_error_state').removeClass('d-none');
                $modal.find('#proposal_error_message').text(result.error || 'Upload failed');
            }
        } catch (e) {
            $modal.find('#proposal_processing_state').addClass('d-none');
            $modal.find('#proposal_error_state').removeClass('d-none');
            $modal.find('#proposal_error_message').text('Network error: ' + e.message);
        }
    },

    _onRetryProposalUpload: function (ev) {
        var $modal = $('#modal_upload_proposal');
        $modal.find('#proposal_error_state').addClass('d-none');
        $modal.find('#proposal_form_state').removeClass('d-none');
    }

});

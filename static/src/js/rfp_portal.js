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

    // --- INPUT CHANGE (for dependency logic) ---

    _onInputChange: function (ev) {
        // Trigger dependency re-evaluation if needed
        const $input = $(ev.currentTarget);
        const $group = $input.closest('.rfp-input-group');
        const fieldKey = $group.data('field-key');
        const value = $input.val();

        // Check if any specify input needs to be shown
        const rawTriggers = $group.data('specify-triggers');
        let specifyTriggers = [];
        try {
            specifyTriggers = typeof rawTriggers === 'string' ? JSON.parse(rawTriggers) : (rawTriggers || []);
        } catch (e) {
            specifyTriggers = [];
        }

        const $specifyInput = $group.find('.rfp-specify-input');
        if (specifyTriggers.length && $specifyInput.length) {
            if (specifyTriggers.includes(value)) {
                $specifyInput.removeClass('d-none');
            } else {
                $specifyInput.addClass('d-none').val('');
            }
        }
    }

});

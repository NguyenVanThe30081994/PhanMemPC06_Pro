/**
 * Shared guard preventing accidental loss of unsaved configuration changes.
 * Prompts user whether to Save, Discard, or Stay before exiting.
 */
(function (global) {
    'use strict';

    function setBootstrapModalFocusTrap(active) {
        if (!global.bootstrap || !global.bootstrap.Modal) return;
        document.querySelectorAll('.modal.show').forEach(function (modalEl) {
            var inst = global.bootstrap.Modal.getInstance(modalEl);
            if (!inst || !inst._focustrap) return;
            if (active && typeof inst._focustrap.activate === 'function') {
                inst._focustrap.activate();
            } else if (!active && typeof inst._focustrap.deactivate === 'function') {
                inst._focustrap.deactivate();
            }
        });
    }

    /**
     * Show a 3-choice SweetAlert2 dialog: Save & Exit / Discard & Exit / Stay.
     * Returns Promise<'save' | 'discard' | 'stay'>.
     */
    global.pcPromptUnsavedExit = function pcPromptUnsavedExit(opts) {
        var cfg = opts || {};
        var title = cfg.title || 'Bạn đang cấu hình';
        var text = cfg.text || 'Cấu hình hiện tại chưa được lưu. Bạn có muốn lưu lại trước khi thoát không?';
        var showSave = cfg.showSave !== false;

        if (typeof global.Swal === 'undefined') {
            var msg = title + '\n\n' + text + '\n\nNhấn OK để thoát không lưu, hoặc Cancel để ở lại.';
            return Promise.resolve(global.confirm(msg) ? 'discard' : 'stay');
        }

        return global.Swal.fire({
            icon: 'warning',
            title: title,
            text: text,
            showConfirmButton: showSave,
            confirmButtonText: cfg.saveText || 'Lưu lại & Thoát',
            showDenyButton: true,
            denyButtonText: cfg.discardText || 'Không lưu, thoát',
            showCancelButton: true,
            cancelButtonText: cfg.stayText || 'Ở lại',
            reverseButtons: false,
            focusCancel: true,
            buttonsStyling: false,
            customClass: {
                popup: 'pc-swal-popup',
                title: 'pc-swal-title',
                htmlContainer: 'pc-swal-html',
                actions: 'gap-2 flex-wrap justify-content-center',
                confirmButton: 'pc-btn pc-btn-primary pc-swal-confirm',
                denyButton: 'pc-btn pc-btn-danger pc-swal-confirm',
                cancelButton: 'pc-btn pc-btn-secondary pc-swal-cancel',
            },
            didOpen: function () {
                setBootstrapModalFocusTrap(false);
            },
            didClose: function () {
                setBootstrapModalFocusTrap(true);
            },
        }).then(function (result) {
            if (result.isConfirmed) return 'save';
            if (result.isDenied) return 'discard';
            return 'stay';
        });
    };

    /**
     * Build a deterministic serialized snapshot of editable fields in a form.
     */
    global.pcSerializeForm = function pcSerializeForm(formEl) {
        if (!formEl) return '';
        var entries = [];
        var fields = formEl.querySelectorAll('input, select, textarea');
        fields.forEach(function (el) {
            var name = el.name || el.id || '';
            if (!name || name === 'csrf_token' || el.hasAttribute('data-ignore-dirty')) return;
            var type = (el.type || '').toLowerCase();
            if (type === 'hidden' && !el.hasAttribute('data-track-dirty')) return;
            if (type === 'checkbox' || type === 'radio') {
                entries.push([name, el.value || '', Boolean(el.checked)]);
            } else if (el.tagName === 'SELECT' && el.multiple) {
                var selected = Array.from(el.selectedOptions || []).map(function (o) { return o.value; });
                entries.push([name, selected]);
            } else {
                entries.push([name, el.value != null ? String(el.value) : '']);
            }
        });
        return JSON.stringify(entries);
    };

    function isSamePageHref(href) {
        if (!href) return true;
        var trimmed = String(href).trim();
        if (!trimmed || trimmed.charAt(0) === '#' || trimmed.toLowerCase().indexOf('javascript:') === 0) {
            return true;
        }
        try {
            var dest = new URL(trimmed, global.location.href);
            var cur = new URL(global.location.href);
            return dest.origin === cur.origin && dest.pathname === cur.pathname && dest.search === cur.search && Boolean(dest.hash);
        } catch (_err) {
            return false;
        }
    }

    /**
     * Attach page-level unsaved-changes guard (`beforeunload` + link clicks + logout).
     */
    global.pcAttachUnsavedGuard = function pcAttachUnsavedGuard(opts) {
        var cfg = opts || {};
        var disabled = false;
        var prompting = false;

        function shouldWarn() {
            if (disabled || prompting) return false;
            return typeof cfg.isDirty === 'function' ? Boolean(cfg.isDirty()) : false;
        }

        function handleBeforeUnload(e) {
            if (!shouldWarn()) return;
            e.preventDefault();
            e.returnValue = '';
        }

        async function runPrompt(proceedFn, customOpts) {
            if (prompting) return false;
            prompting = true;
            try {
                var merged = Object.assign({}, cfg, customOpts || {});
                var choice = await global.pcPromptUnsavedExit(merged);
                if (choice === 'save') {
                    var saveOk = true;
                    if (typeof merged.onSaveAndExit === 'function') {
                        saveOk = await merged.onSaveAndExit();
                    }
                    if (saveOk === false) return false;
                    disabled = true;
                    if (typeof proceedFn === 'function') await proceedFn('save');
                    return true;
                }
                if (choice === 'discard') {
                    if (typeof merged.onDiscardExit === 'function') {
                        await merged.onDiscardExit();
                    }
                    disabled = true;
                    if (typeof proceedFn === 'function') await proceedFn('discard');
                    return true;
                }
                return false;
            } finally {
                prompting = false;
            }
        }

        function handleDocumentClick(e) {
            if (e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) {
                return;
            }
            if (!shouldWarn()) return;
            var link = e.target && e.target.closest ? e.target.closest('a[href]') : null;
            if (!link) return;
            if (
                link.target === '_blank' ||
                link.hasAttribute('download') ||
                link.hasAttribute('data-bs-toggle') ||
                link.hasAttribute('data-ignore-unsaved') ||
                (cfg.ignoreSelector && link.closest(cfg.ignoreSelector))
            ) {
                return;
            }
            var href = link.getAttribute('href');
            if (isSamePageHref(href)) return;

            e.preventDefault();
            e.stopPropagation();
            runPrompt(function () {
                global.location.assign(link.href);
            });
        }

        function handleLogoutSubmit(e) {
            if (!shouldWarn()) return;
            var form = e.target;
            if (!form || !(form instanceof HTMLFormElement)) return;
            var action = String(form.getAttribute('action') || '');
            if (action.indexOf('/logout') === -1) return;
            e.preventDefault();
            e.stopPropagation();
            runPrompt(function () {
                form.submit();
            });
        }

        global.addEventListener('beforeunload', handleBeforeUnload);
        document.addEventListener('click', handleDocumentClick, true);
        document.addEventListener('submit', handleLogoutSubmit, true);

        return {
            disable: function () { disabled = true; },
            enable: function () { disabled = false; },
            isDisabled: function () { return disabled; },
            confirmExitAction: function (proceedFn, customOpts) {
                if (!shouldWarn()) {
                    if (typeof proceedFn === 'function') return Promise.resolve(proceedFn('clean'));
                    return Promise.resolve(true);
                }
                return runPrompt(proceedFn, customOpts);
            },
            destroy: function () {
                global.removeEventListener('beforeunload', handleBeforeUnload);
                document.removeEventListener('click', handleDocumentClick, true);
                document.removeEventListener('submit', handleLogoutSubmit, true);
            },
        };
    };
})(window);

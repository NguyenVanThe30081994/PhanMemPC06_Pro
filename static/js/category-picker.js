function escapeCategoryHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

class CategoryPicker {
    constructor(root) {
        this.root = root;
        this.targetSelect = root.querySelector('[data-category-target]') || root.querySelector('select');
        if (!this.targetSelect) {
            return;
        }

        this.storageKey = root.dataset.storageKey || '';
        this.moduleCode = root.dataset.module || '';
        this.fieldCode = root.dataset.field || '';
        this.groupCode = root.dataset.groupCode || '';
        this.groupName = root.dataset.groupName || '';
        this.valueMode = root.dataset.valueMode || '';
        this.placeholder = root.dataset.placeholder || this.targetSelect.dataset.placeholder || 'Chọn danh mục';
        this.loadingLabel = root.dataset.loadingLabel || 'Đang tải...';
        this.selectedValue = this.targetSelect.dataset.selectedValue || this.targetSelect.value || '';

        this.buildChrome();
        this.bootstrap();
    }

    buildChrome() {
        this.root.classList.add('category-picker');

        this.toggleButton = document.createElement('button');
        this.toggleButton.type = 'button';
        this.toggleButton.className = 'btn btn-outline-secondary category-picker-toggle';
        this.toggleButton.title = 'Chọn danh mục nguồn';
        this.toggleButton.innerHTML = '<i class="fa-solid fa-list"></i>';
        this.toggleButton.addEventListener('click', () => {
            this.root.classList.toggle('category-picker-open');
        });

        if (!this.targetSelect.parentElement.classList.contains('category-picker-input')) {
            const control = document.createElement('div');
            control.className = 'category-picker-input input-group';
            this.targetSelect.parentNode.insertBefore(control, this.targetSelect);
            control.appendChild(this.targetSelect);
            control.appendChild(this.toggleButton);
        }

        this.sourceRow = document.createElement('div');
        this.sourceRow.className = 'category-picker-source';
        this.sourceRow.innerHTML = `
            <select class="form-select form-select-sm"></select>
        `;
        this.sourceSelect = this.sourceRow.querySelector('select');
        this.sourceSelect.addEventListener('change', () => {
            const groupId = this.sourceSelect.value;
            if (this.storageKey && groupId) {
                localStorage.setItem(this.storageKey, groupId);
            }
            this.fetchBundle(groupId);
        });

        const anchor = this.root.querySelector('.category-picker-input');
        anchor.parentNode.insertBefore(this.sourceRow, anchor);
    }

    async bootstrap() {
        const storedGroupId = this.storageKey ? localStorage.getItem(this.storageKey) : '';
        try {
            await this.fetchBundle(storedGroupId || '');
        } catch (error) {
            console.error('Category picker init failed:', error);
            this.renderTargetOptions([]);
        }
    }

    async fetchBundle(groupId) {
        this.setLoadingState();

        const params = new URLSearchParams();
        if (groupId) params.set('group_id', groupId);
        if (this.moduleCode) params.set('module', this.moduleCode);
        if (this.fieldCode) params.set('field', this.fieldCode);
        if (this.groupCode) params.set('group_code', this.groupCode);
        if (this.groupName) params.set('group_name', this.groupName);

        const response = await fetch(`/api/category-picker?${params.toString()}`);
        if (!response.ok) {
            this.renderTargetOptions([]);
            return;
        }

        const payload = await response.json();
        const selectedGroupId = String(payload.selected_group_id || groupId || '');

        this.renderSourceOptions(payload.groups || [], selectedGroupId);
        this.renderTargetOptions(payload.items || []);
    }

    renderSourceOptions(groups, selectedGroupId) {
        const options = ['<option value="">Chọn danh mục nguồn</option>'];
        groups.forEach(group => {
            options.push(
                `<option value="${escapeCategoryHtml(group.id)}">${escapeCategoryHtml(group.name)}</option>`
            );
        });
        this.sourceSelect.innerHTML = options.join('');
        this.sourceSelect.value = selectedGroupId || '';

        if (selectedGroupId && this.storageKey) {
            localStorage.setItem(this.storageKey, selectedGroupId);
        }
    }

    renderTargetOptions(items) {
        const options = [`<option value="">${escapeCategoryHtml(this.placeholder)}</option>`];
        const useStableValue = this.valueMode === 'stable'
            || (this.moduleCode === 'library' && this.fieldCode === 'category');
        const optionValueOf = (item) => {
            if (useStableValue) {
                return item.stable_value || item.value || item.code || item.name || '';
            }
            return item.value || item.code || item.name || '';
        };
        const normalizedItemValues = new Set();

        items.forEach(item => {
            const optionValue = optionValueOf(item);
            normalizedItemValues.add(String(optionValue));
            normalizedItemValues.add(String(item.name || ''));
            normalizedItemValues.add(String(item.code || ''));
            options.push(
                `<option value="${escapeCategoryHtml(optionValue)}">${escapeCategoryHtml(item.name)}</option>`
            );
        });

        if (this.selectedValue && !normalizedItemValues.has(String(this.selectedValue))) {
            options.push(
                `<option value="${escapeCategoryHtml(this.selectedValue)}">${escapeCategoryHtml(this.selectedValue)}</option>`
            );
        }

        this.targetSelect.innerHTML = options.join('');
        if (this.selectedValue) {
            this.targetSelect.value = this.selectedValue;
        }
    }

    setLoadingState() {
        this.targetSelect.innerHTML = `<option value="">${escapeCategoryHtml(this.loadingLabel)}</option>`;
    }
}

function initCategoryPickers(scope = document) {
    scope.querySelectorAll('[data-category-picker]').forEach(root => {
        if (root.dataset.categoryPickerReady === '1') {
            return;
        }
        root.dataset.categoryPickerReady = '1';
        root._categoryPicker = new CategoryPicker(root);
    });
}

window.initCategoryPickers = initCategoryPickers;

document.addEventListener('DOMContentLoaded', () => {
    initCategoryPickers();
});

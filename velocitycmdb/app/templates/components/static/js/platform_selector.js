// static/js/platform_selector.js

class PlatformSelector {
    constructor(containerElement, options = {}) {
        this.container = containerElement;
        this.selectedValue = options.initialValue || '';
        this.allowCustom = options.allowCustom !== false;
        this.onChange = options.onChange || (() => {});
        
        this.render();
    }

    render() {
        const grouped = platformManager.getGroupedPlatforms();
        
        const html = `
            <div class="platform-selector">
                <select id="platform-select" class="platform-dropdown">
                    <option value="">Select Platform...</option>
                    ${Object.entries(grouped).map(([category, platforms]) => `
                        <optgroup label="${category}">
                            ${platforms.map(p => `
                                <option value="${p.value}" 
                                        data-icon="${p.icon}"
                                        ${p.value === this.selectedValue ? 'selected' : ''}>
                                    ${p.label}
                                </option>
                            `).join('')}
                        </optgroup>
                    `).join('')}
                    ${this.allowCustom ? `
                        <optgroup label="Custom">
                            <option value="__custom__">Custom Platform...</option>
                        </optgroup>
                    ` : ''}
                </select>
                
                <div class="platform-preview">
                    <img id="platform-icon-preview" 
                         src="" 
                         alt="Platform icon"
                         style="display: none;">
                </div>
                
                ${this.allowCustom ? `
                    <div id="custom-platform-input" style="display: none;">
                        <input type="text" 
                               id="custom-platform-text"
                               placeholder="Enter custom platform (e.g., FortiGate-60E)"
                               class="platform-input">
                        <small class="hint">
                            Will use generic icon if no pattern match
                        </small>
                    </div>
                ` : ''}
            </div>
        `;
        
        this.container.innerHTML = html;
        this.attachEventListeners();
        this.updatePreview();
    }

    attachEventListeners() {
        const select = document.getElementById('platform-select');
        const customInput = document.getElementById('custom-platform-text');
        
        select.addEventListener('change', (e) => {
            if (e.target.value === '__custom__') {
                document.getElementById('custom-platform-input').style.display = 'block';
                document.getElementById('platform-icon-preview').style.display = 'none';
            } else {
                document.getElementById('custom-platform-input').style.display = 'none';
                this.selectedValue = e.target.value;
                this.updatePreview();
                this.onChange(this.selectedValue);
            }
        });
        
        if (customInput) {
            customInput.addEventListener('input', (e) => {
                this.selectedValue = e.target.value;
                this.onChange(this.selectedValue);
            });
        }
    }

    updatePreview() {
        const preview = document.getElementById('platform-icon-preview');
        if (this.selectedValue && this.selectedValue !== '__custom__') {
            const icon = platformManager.getIconForPlatform(this.selectedValue);
            preview.src = icon;
            preview.style.display = 'block';
        } else {
            preview.style.display = 'none';
        }
    }

    getValue() {
        const select = document.getElementById('platform-select');
        if (select.value === '__custom__') {
            return document.getElementById('custom-platform-text').value;
        }
        return select.value;
    }

    setValue(value) {
        this.selectedValue = value;
        
        // Check if value exists in dropdown
        const select = document.getElementById('platform-select');
        const option = Array.from(select.options).find(opt => opt.value === value);
        
        if (option) {
            select.value = value;
        } else if (this.allowCustom && value) {
            // Custom value
            select.value = '__custom__';
            document.getElementById('custom-platform-input').style.display = 'block';
            document.getElementById('custom-platform-text').value = value;
        }
        
        this.updatePreview();
    }
}

console.log("platform_selector.js loaded...")
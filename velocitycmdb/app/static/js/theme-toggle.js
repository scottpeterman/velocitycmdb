// static/js/theme-toggle.js

class ThemeManager {
    constructor() {
        this.themes = ['light', 'dark', 'cyber'];
        this.currentTheme = this.getSavedTheme() || 'light';
        this.init();
    }

    init() {
        // Set initial theme
        this.setTheme(this.currentTheme);

        // Bind event listeners
        this.bindEvents();

        // Update UI elements
        this.updateUI();
    }

    bindEvents() {
        // Theme toggle button (cycles through themes)
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                this.cycleTheme();
            });
        }

        // Theme selector dropdown
        const themeSelector = document.getElementById('theme-selector');
        if (themeSelector) {
            themeSelector.value = this.currentTheme;
            themeSelector.addEventListener('change', (e) => {
                this.setTheme(e.target.value);
            });
        }

        // Listen for system theme changes
        if (window.matchMedia) {
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                // Only auto-switch if no theme preference is saved
                if (!localStorage.getItem('theme-preference')) {
                    this.setTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    }

    cycleTheme() {
        const currentIndex = this.themes.indexOf(this.currentTheme);
        const nextIndex = (currentIndex + 1) % this.themes.length;
        this.setTheme(this.themes[nextIndex]);
    }

    setTheme(theme) {
        if (!this.themes.includes(theme)) {
            console.warn(`Theme "${theme}" not supported. Using light theme.`);
            theme = 'light';
        }

        this.currentTheme = theme;

        // Apply theme to document
        document.documentElement.setAttribute('data-theme', theme);

        // Save preference
        localStorage.setItem('theme-preference', theme);

        // Update UI elements
        this.updateUI();

        // Dispatch custom event for other components
        window.dispatchEvent(new CustomEvent('themeChanged', {
            detail: { theme: theme }
        }));
    }

    updateUI() {
        // Update theme selector
        const themeSelector = document.getElementById('theme-selector');
        if (themeSelector) {
            themeSelector.value = this.currentTheme;
        }

        // Update toggle button icon
        const themeIcon = document.getElementById('theme-icon');
        if (themeIcon) {
            const iconMap = {
                'light': 'fa-sun',
                'dark': 'fa-moon',
                'cyber': 'fa-terminal'
            };

            // Remove all theme icons
            themeIcon.className = themeIcon.className.replace(/fa-[a-z-]+/g, '');
            // Add current theme icon
            themeIcon.classList.add('fas', iconMap[this.currentTheme] || 'fa-sun');
        }

        // Update toggle button title
        const toggleBtn = document.getElementById('theme-toggle');
        if (toggleBtn) {
            const titleMap = {
                'light': 'Switch to Dark Theme',
                'dark': 'Switch to Cyber Theme',
                'cyber': 'Switch to Light Theme'
            };
            toggleBtn.title = titleMap[this.currentTheme] || 'Toggle Theme';
        }
    }

    getSavedTheme() {
        // Check localStorage first
        const saved = localStorage.getItem('theme-preference');
        if (saved && this.themes.includes(saved)) {
            return saved;
        }

        // Fall back to system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }

        return 'light';
    }

    getCurrentTheme() {
        return this.currentTheme;
    }

    // Public API for other scripts
    getAvailableThemes() {
        return [...this.themes];
    }
}

// Initialize theme manager when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    // Create global theme manager instance
    window.themeManager = new ThemeManager();

    // Add some cyber theme specific animations
    if (window.themeManager.getCurrentTheme() === 'cyber') {
        initCyberEffects();
    }

    // Listen for theme changes to toggle cyber effects
    window.addEventListener('themeChanged', (e) => {
        if (e.detail.theme === 'cyber') {
            initCyberEffects();
        } else {
            removeCyberEffects();
        }
    });
});

// Cyber theme specific effects
function initCyberEffects() {
    // Add pulse animation to stats cards
    const statsCards = document.querySelectorAll('.stats-card');
    statsCards.forEach((card, index) => {
        setTimeout(() => {
            card.classList.add('pulse');
        }, index * 200);
    });

    // Add subtle glow to primary buttons
    const primaryBtns = document.querySelectorAll('.btn-primary');
    primaryBtns.forEach(btn => {
        btn.style.transition = 'all 0.3s ease';
    });
}

function removeCyberEffects() {
    // Remove pulse animations
    const pulseElements = document.querySelectorAll('.pulse');
    pulseElements.forEach(el => {
        el.classList.remove('pulse');
    });
}

// Utility function to manually set theme (for console debugging)
function setTheme(themeName) {
    if (window.themeManager) {
        window.themeManager.setTheme(themeName);
    } else {
        console.warn('Theme manager not initialized yet');
    }
}

// Export for module systems (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ThemeManager;
}
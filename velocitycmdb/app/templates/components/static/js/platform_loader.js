// static/js/platform_loader.js

class PlatformManager {
    constructor() {
        this.platformMap = null;
        this.platforms = [];
        this.iconCache = {};
    }

    async loadPlatformMap() {
        const response = await fetch('/api/platform-map');
        this.platformMap = await response.json();
        this.buildPlatformList();
    }

    buildPlatformList() {
        const platforms = [];

        // Add all platform patterns
        for (const [pattern, icon] of Object.entries(this.platformMap.platform_patterns)) {
            platforms.push({
                value: pattern,
                label: pattern,
                icon: `${this.platformMap.base_path}/${icon}`,
                category: this.categorizePattern(pattern)
            });
        }

        // Add defaults as options
        for (const [key, icon] of Object.entries(this.platformMap.defaults)) {
            const label = key.replace('default_', '').replace('_', ' ');
            platforms.push({
                value: label,
                label: `Generic ${label.charAt(0).toUpperCase() + label.slice(1)}`,
                icon: `${this.platformMap.base_path}/${icon}`,
                category: 'Generic'
            });
        }

        this.platforms = platforms;
    }

    categorizePattern(pattern) {
        // Group by vendor
        if (pattern.startsWith('C9') || pattern.startsWith('WS-C') ||
            pattern.includes('Nexus') || pattern.startsWith('ISR') ||
            pattern.startsWith('CISCO')) {
            return 'Cisco';
        }
        if (pattern.startsWith('DCS-') || pattern.includes('Arista') ||
            pattern === 'vEOS') {
            return 'Arista';
        }
        if (pattern.includes('Juniper') || pattern.toLowerCase().includes('qfx')) {
            return 'Juniper';
        }
        if (pattern.includes('linux') || pattern.includes('debian')) {
            return 'Linux/Unix';
        }
        if (pattern.includes('Phone') || pattern === 'SEP' ||
            pattern === 'ATA' || pattern === 'VG') {
            return 'Voice';
        }
        return 'Other';
    }

    getGroupedPlatforms() {
        const grouped = {};

        for (const platform of this.platforms) {
            if (!grouped[platform.category]) {
                grouped[platform.category] = [];
            }
            grouped[platform.category].push(platform);
        }

        // Sort categories
        const sortOrder = ['Cisco', 'Arista', 'Juniper', 'Voice', 'Linux/Unix', 'Other', 'Generic'];
        const sorted = {};

        for (const category of sortOrder) {
            if (grouped[category]) {
                sorted[category] = grouped[category].sort((a, b) =>
                    a.label.localeCompare(b.label)
                );
            }
        }

        return sorted;
    }

    getIconForPlatform(platformValue) {
        const platform = this.platforms.find(p => p.value === platformValue);
        return platform ? platform.icon : `${this.platformMap.base_path}/${this.platformMap.defaults.default_unknown}`;
    }
}

// Global instance
const platformManager = new PlatformManager();
console.log("platform_loader.js loaded...")
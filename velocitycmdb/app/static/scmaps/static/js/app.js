/**
 * Main Application Controller for SecureCartography Visualizer
 * Handles initialization, map loading, and coordination between modules
 */

const App = {
    currentMap: null,

    /**
     * Initialize the application
     */
    async init() {
        console.log('[App] Initializing SecureCartography...');

        // Initialize modules
        Theme.init();
        Layout.init();
        FileManager.init();
        Sidebar.init();

        // Setup event listeners
        this.setupEventListeners();

        // Load initial map list
        await this.refreshMapList();

        console.log('[App] Initialization complete');
    },

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        // Map selector
        const mapSelect = document.getElementById('map-select');
        if (mapSelect) {
            mapSelect.addEventListener('change', (e) => {
                if (e.target.value) {
                    this.loadMap(e.target.value);
                }
            });
        }

        // View controls
        document.getElementById('fit-view-btn')?.addEventListener('click', () => {
            if (Graph.cy) {
                Graph.cy.fit(null, 50);
            }
        });

        document.getElementById('reset-layout-btn')?.addEventListener('click', () => {
            Layout.resetLayout();
        });

        // Export PNG
        document.getElementById('export-png-btn')?.addEventListener('click', () => {
            this.exportPNG();
        });

        // Create node/edge buttons
        document.getElementById('create-node-btn')?.addEventListener('click', () => {
            Graph.createNode();
        });

        document.getElementById('create-edge-btn')?.addEventListener('click', () => {
            Graph.createEdge();
        });
    },

    /**
     * Refresh the list of available maps
     */
    async refreshMapList() {
        try {
            const result = await API.listMaps();

            if (!result || result.error) {
                console.error('Failed to load maps:', result?.error);
                UI.showToast('Failed to load map list', 'error');
                return;
            }

            const maps = Array.isArray(result) ? result : [];
            console.log(`[App] Loaded ${maps.length} maps`);

            // Update map selector
            const mapSelect = document.getElementById('map-select');
            if (!mapSelect) return;

            const currentValue = mapSelect.value;
            mapSelect.innerHTML = '<option value="">Select a network map...</option>';

            maps.forEach(map => {
                const option = document.createElement('option');
                option.value = map.name;
                option.textContent = map.has_layout ? `${map.name} ✓` : map.name;
                mapSelect.appendChild(option);
            });

            // Restore selection if it still exists
            if (currentValue && maps.find(m => m.name === currentValue)) {
                mapSelect.value = currentValue;
            }

        } catch (error) {
            console.error('[App] Error refreshing map list:', error);
            UI.showToast('Error loading maps: ' + error.message, 'error');
        }
    },

    /**
     * Load a specific map
     */
    async loadMap(mapName) {
        console.log(`[App] Loading map: ${mapName}`);
        UI.showLoading();

        try {
            const result = await API.loadMap(mapName);

            if (result.error) {
                throw new Error(result.error);
            }

            this.currentMap = mapName;
            Layout.setCurrentMap(mapName);

            // Initialize or update graph
            if (!Graph.cy) {
                Graph.init('cy');
            }

            // Load topology into graph
            if (result.cytoscape) {
                Graph.loadTopology(result.cytoscape);
            } else {
                UI.showToast('No topology data in map', 'warning');
                return;
            }

            // Restore saved layout if exists
            if (result.layout) {
                Layout.restoreLayout(result.layout);
            } else {
                // Apply default layout
                Layout.applyLayout();
            }

            UI.showToast(`Loaded map: ${mapName}`, 'success');
            console.log(`[App] Map loaded successfully`);

        } catch (error) {
            console.error('[App] Error loading map:', error);
            UI.showToast('Error loading map: ' + error.message, 'error');
        } finally {
            UI.hideLoading();
        }
    },

    /**
     * Export current view as PNG
     */
    exportPNG() {
        if (!Graph.cy) {
            UI.showToast('No graph to export', 'warning');
            return;
        }

        try {
            const png = Graph.cy.png({
                output: 'blob',
                full: true,
                scale: 2,
                bg: getComputedStyle(document.documentElement)
                    .getPropertyValue('--md-surface-container-low').trim()
            });

            const url = URL.createObjectURL(png);
            const link = document.createElement('a');
            link.href = url;
            link.download = `${this.currentMap || 'network'}.png`;
            link.click();
            URL.revokeObjectURL(url);

            UI.showToast('PNG exported successfully', 'success');
        } catch (error) {
            console.error('PNG export error:', error);
            UI.showToast('PNG export failed', 'error');
        }
    }
};

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        console.log('[App] DOM loaded, initializing...');
        App.init();
    });
} else {
    console.log('[App] DOM already loaded, initializing immediately...');
    App.init();
}

// Make App available globally
window.App = App;
/**
 * VelocityCMDB Discovery Wizard - Complete Flow
 * Discovery -> Fingerprinting -> Data Collection (future)
 */

// SocketIO connection
const socket = io();

// Current job tracking
let currentDiscoveryJobId = null;
let currentFingerprintJobId = null;

// Wizard state
const wizardState = {
    currentStep: 'discovery',
    discoveryComplete: false,
    fingerprintComplete: false
};

// ============================================================================
// STEP NAVIGATION
// ============================================================================

function showStep(stepName) {
    // Hide all steps
    document.querySelectorAll('.wizard-step').forEach(step => {
        step.style.display = 'none';
    });

    // Show requested step
    const stepElement = document.getElementById(`step-${stepName}`);
    if (stepElement) {
        stepElement.style.display = 'block';
        wizardState.currentStep = stepName;
    }
}

// ============================================================================
// STEP 1: DISCOVERY
// ============================================================================

document.getElementById('start-discovery-btn')?.addEventListener('click', function() {
    const seedIp = document.getElementById('seed-ip').value.trim();
    const username = document.getElementById('discovery-username').value.trim();
    const password = document.getElementById('discovery-password').value.trim();

    if (!seedIp || !username || !password) {
        M.toast({html: 'Please fill in all required fields', classes: 'red'});
        return;
    }

    // Disable form
    document.getElementById('discovery-form').style.display = 'none';
    document.getElementById('discovery-progress').style.display = 'block';

    // Start discovery
    fetch('/discovery/start', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            seed_ip: seedIp,
            username: username,
            password: password
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            currentDiscoveryJobId = data.job_id;
            M.toast({html: 'Discovery started!', classes: 'green'});
        } else {
            throw new Error(data.error || 'Failed to start discovery');
        }
    })
    .catch(err => {
        console.error('Discovery start error:', err);
        M.toast({html: `Error: ${err.message}`, classes: 'red'});
        document.getElementById('discovery-form').style.display = 'block';
        document.getElementById('discovery-progress').style.display = 'none';
    });
});

// Listen for discovery progress
socket.on('discovery_progress', function(data) {
    if (data.job_id !== currentDiscoveryJobId) return;

    // Update progress bar
    const progressBar = document.getElementById('discovery-progress-bar');
    if (progressBar) {
        progressBar.style.width = data.progress + '%';
    }

    // Update status message
    const statusMsg = document.getElementById('discovery-status-message');
    if (statusMsg) {
        statusMsg.textContent = data.message || '';
    }

    // Append to log
    appendToLog('discovery-log', data.message);
});

// Listen for discovery completion
socket.on('discovery_complete', function(data) {
    if (data.job_id !== currentDiscoveryJobId) return;

    wizardState.discoveryComplete = true;

    M.toast({html: `✓ Discovered ${data.device_count} devices!`, classes: 'green'});

    // Load device summary
    loadDeviceSummary(currentDiscoveryJobId);
});

// Listen for discovery failure
socket.on('discovery_failed', function(data) {
    if (data.job_id !== currentDiscoveryJobId) return;

    M.toast({html: `Discovery failed: ${data.error}`, classes: 'red'});

    // Allow retry
    document.getElementById('discovery-form').style.display = 'block';
    document.getElementById('discovery-progress').style.display = 'none';
});

// ============================================================================
// STEP 2: FINGERPRINTING
// ============================================================================

function loadDeviceSummary(jobId) {
    // Fetch discovered devices
    fetch(`/discovery/${jobId}/devices`)
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                // Update device count
                document.getElementById('device-count').textContent = data.total;
                document.getElementById('fingerprint-summary').style.display = 'block';

                // Show fingerprint step
                showStep('fingerprint');

                // Pre-fill username if available
                const username = document.getElementById('discovery-username')?.value;
                if (username) {
                    document.getElementById('ssh-username').value = username;
                    M.updateTextFields(); // Update Materialize labels
                }
            } else {
                throw new Error(data.error || 'Failed to load devices');
            }
        })
        .catch(err => {
            console.error('Error loading devices:', err);
            M.toast({html: `Error: ${err.message}`, classes: 'red'});
        });
}

document.getElementById('start-fingerprint-btn')?.addEventListener('click', function() {
    const username = document.getElementById('ssh-username').value.trim();
    const password = document.getElementById('ssh-password').value.trim();
    const sshKeyPath = document.getElementById('ssh-key-path').value.trim();

    if (!username || !password) {
        M.toast({html: 'Username and password required', classes: 'red'});
        return;
    }

    // Hide form, show progress
    document.getElementById('credentials-form').style.display = 'none';
    document.getElementById('fingerprint-progress').style.display = 'block';

    // Start fingerprinting
    fetch(`/discovery/fingerprint/${currentDiscoveryJobId}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            username: username,
            password: password,
            ssh_key_path: sshKeyPath || null
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            currentFingerprintJobId = data.fingerprint_job_id;
            console.log('Fingerprinting started:', currentFingerprintJobId);
        } else {
            throw new Error(data.error || 'Failed to start fingerprinting');
        }
    })
    .catch(err => {
        console.error('Fingerprinting start error:', err);
        M.toast({html: `Error: ${err.message}`, classes: 'red'});
        document.getElementById('credentials-form').style.display = 'block';
        document.getElementById('fingerprint-progress').style.display = 'none';
    });
});

// Listen for fingerprint progress
socket.on('fingerprint_progress', function(data) {
    console.log('Fingerprint progress:', data);

    if (data.job_id !== currentFingerprintJobId) return;

    // Update progress bar
    const progressBar = document.getElementById('fingerprint-progress-bar');
    if (progressBar) {
        progressBar.style.width = data.progress + '%';
    }

    // Update status message
    const statusMsg = document.getElementById('fingerprint-status-message');
    if (statusMsg) {
        statusMsg.textContent = data.message || '';
    }

    // Update current device
    if (data.current_device) {
        const deviceName = document.getElementById('current-device-name');
        if (deviceName) {
            deviceName.textContent = data.current_device;
        }
    }

    // Update counters
    if (data.devices_completed !== undefined) {
        const completed = document.getElementById('devices-completed');
        if (completed) {
            completed.textContent = data.devices_completed;
        }
    }

    if (data.devices_total !== undefined) {
        const total = document.getElementById('devices-total');
        if (total) {
            total.textContent = data.devices_total;
        }
    }

    // Append to log
    appendToLog('fingerprint-log', data.message);
});

// Listen for fingerprint completion
socket.on('fingerprint_complete', function(data) {
    console.log('Fingerprint complete:', data);

    if (data.job_id !== currentFingerprintJobId) return;

    wizardState.fingerprintComplete = true;

    // Hide progress, show results
    document.getElementById('fingerprint-progress').style.display = 'none';
    document.getElementById('fingerprint-results').style.display = 'block';

    // Update counters
    document.getElementById('fingerprint-success-count').textContent = data.fingerprinted || 0;
    document.getElementById('fingerprint-failed-count').textContent = data.failed || 0;
    document.getElementById('fingerprint-db-count').textContent = data.loaded_to_db || 0;

    // Show failed devices if any
    if (data.failed > 0 && data.failed_devices) {
        showFailedDevices(data.failed_devices);
    }

    M.toast({html: `✓ Fingerprinted ${data.fingerprinted} devices!`, classes: 'green'});
});

// Listen for fingerprint errors
socket.on('fingerprint_error', function(data) {
    console.error('Fingerprint error:', data);

    if (data.job_id !== currentFingerprintJobId) return;

    M.toast({html: `Fingerprinting failed: ${data.error}`, classes: 'red'});

    // Show error in progress section
    const statusMsg = document.getElementById('fingerprint-status-message');
    if (statusMsg) {
        statusMsg.textContent = `Error: ${data.error}`;
        statusMsg.style.color = 'red';
    }
});

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function appendToLog(logElementId, message) {
    const logDiv = document.getElementById(logElementId);
    if (!logDiv) return;

    const timestamp = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.textContent = `[${timestamp}] ${message}`;

    logDiv.appendChild(logEntry);

    // Auto-scroll to bottom
    logDiv.scrollTop = logDiv.scrollHeight;

    // Limit log entries (keep last 100)
    while (logDiv.children.length > 100) {
        logDiv.removeChild(logDiv.firstChild);
    }
}

function showFailedDevices(failedDevices) {
    const section = document.getElementById('failed-devices-section');
    const tbody = document.getElementById('failed-devices-tbody');

    if (!section || !tbody) return;

    // Clear existing rows
    tbody.innerHTML = '';

    // Add failed devices
    failedDevices.forEach(device => {
        const row = tbody.insertRow();
        row.insertCell(0).textContent = device.name || '-';
        row.insertCell(1).textContent = device.ip || '-';
        row.insertCell(2).textContent = device.error || 'Unknown error';
    });

    section.style.display = 'block';
}

// ============================================================================
// BUTTON HANDLERS
// ============================================================================

// View devices button
document.getElementById('view-devices-btn')?.addEventListener('click', function() {
    window.location.href = '/assets/devices';
});

// Continue to collection button (placeholder for Phase 3)
document.getElementById('continue-to-collection-btn')?.addEventListener('click', function() {
    M.toast({html: 'Data collection coming in Phase 3!', classes: 'blue'});
    // TODO: showStep('collection');
});

// Retry failed devices button
document.getElementById('retry-failed-btn')?.addEventListener('click', function() {
    M.toast({html: 'Retry functionality coming soon!', classes: 'blue'});
    // TODO: Implement retry logic
});

// ============================================================================
// INITIALIZATION
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Materialize components
    M.AutoInit();

    // Show discovery step by default
    showStep('discovery');

    console.log('Discovery wizard initialized');
});
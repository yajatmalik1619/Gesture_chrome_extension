/**
 * script.js - Aesthetic Gesture Dashboard Logic
 * Integrates with WebSocket (8765) and Watchdog API (8766)
 */

const CONFIG = {
    WS_URL: 'ws://localhost:8765',
    WATCHDOG_URL: 'http://localhost:8766',
    RECONNECT_INTERVAL: 3000
};

// ── State Management ──
let state = {
    connected: false,
    pipelineRunning: false,
    detectionsToday: 0,
    startTime: null,
    currentSection: 'status',
    gestures: {},
    bindings: {}
};

// ── DOM Elements ──
const elements = {
    navItems: document.querySelectorAll('.nav-item'),
    sections: document.querySelectorAll('.content-section'),
    sectionTitle: document.getElementById('section-title'),
    pipelineDot: document.getElementById('pipeline-dot'),
    pipelineText: document.getElementById('pipeline-status-text'),
    toggleBtn: document.getElementById('toggle-pipeline'),
    bindingsList: document.getElementById('bindings-list'),
    currentGestureName: document.getElementById('current-gesture-name'),
    currentActionName: document.getElementById('current-action-name'),
    currentGestureIcon: document.getElementById('current-gesture-icon'),
    statDetections: document.getElementById('stat-detections'),
    statRuntime: document.getElementById('stat-runtime')
};

// ── Initialization ──
function init() {
    setupNavigation();
    setupWatchdogPolling();
    connectWebSocket();
    updateRuntimeUI();

    elements.toggleBtn.addEventListener('click', togglePipeline);
}

// ── Navigation ──
function setupNavigation() {
    elements.navItems.forEach(item => {
        item.addEventListener('click', () => {
            const section = item.dataset.section;
            switchSection(section);
        });
    });
}

function switchSection(sectionId) {
    elements.navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.section === sectionId);
    });

    elements.sections.forEach(section => {
        section.classList.toggle('active', section.id === `section-${sectionId}`);
    });

    state.currentSection = sectionId;
    elements.sectionTitle.textContent = sectionId.charAt(0).toUpperCase() + sectionId.slice(1);

    // Logic specific to certain sections
    if (sectionId === 'camera') {
        setupCameraStream();
    }
}

// ── WebSocket Integration ──
let ws = null;
function connectWebSocket() {
    ws = new WebSocket(CONFIG.WS_URL);

    ws.onopen = () => {
        console.log('WS Connected');
        state.connected = true;
        showToast('Connected to Pipeline');
        updateConnectionUI();
        ws.send(JSON.stringify({ type: 'GET_CONFIG' }));
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg);
        } catch (e) {
            console.error('WS Message Parse Error:', e);
        }
    };

    ws.onclose = () => {
        state.connected = false;
        updateConnectionUI();
        setTimeout(connectWebSocket, CONFIG.RECONNECT_INTERVAL);
    };
}

function handleWSMessage(msg) {
    switch (msg.type) {
        case 'ACTION':
            handleAction(msg);
            break;
        case 'STATUS':
            handleStatus(msg);
            break;
        case 'CONFIG_SNAPSHOT':
            handleConfig(msg);
            break;
    }
}

function handleAction(msg) {
    state.detectionsToday++;
    elements.statDetections.textContent = state.detectionsToday;

    // Update active gesture display
    elements.currentGestureName.textContent = msg.gesture_id.replace(/_/g, ' ');
    elements.currentActionName.textContent = msg.action_id.replace(/_/g, ' ');

    // Visual feedback
    elements.currentGestureIcon.classList.add('pulse');
    setTimeout(() => elements.currentGestureIcon.classList.remove('pulse'), 500);

    showToast(`Detected: ${msg.gesture_id}`);
}

function handleStatus(msg) {
    // Pipeline is live and sending frames/status
}

function handleConfig(msg) {
    state.gestures = msg.gestures;
    state.bindings = msg.bindings;
    renderBindings();
}

// ── Watchdog API ──
async function setupWatchdogPolling() {
    updatePipelineStatus();
    setInterval(updatePipelineStatus, 2000);
}

async function updatePipelineStatus() {
    try {
        const resp = await fetch(`${CONFIG.WATCHDOG_URL}/status`);
        const data = await resp.json();

        state.pipelineRunning = data.running;
        updatePipelineUI();
    } catch (e) {
        state.pipelineRunning = false;
        updatePipelineUI();
    }
}

async function togglePipeline() {
    const endpoint = state.pipelineRunning ? 'stop' : 'start';
    try {
        elements.toggleBtn.disabled = true;
        const resp = await fetch(`${CONFIG.WATCHDOG_URL}/${endpoint}`, { method: 'POST' });
        const data = await resp.json();

        if (data.ok) {
            showToast(state.pipelineRunning ? 'Stopping Pipeline...' : 'Starting Pipeline...');
            if (endpoint === 'start') {
                state.startTime = Date.now();
            }
        }
    } catch (e) {
        showToast('Error communicating with Watchdog', 'error');
    } finally {
        setTimeout(() => elements.toggleBtn.disabled = false, 1000);
    }
}

// ── UI Helpers ──
function updateConnectionUI() {
    const camStatus = document.getElementById('cam-status');
    if (camStatus) {
        camStatus.textContent = state.connected ? 'WebSocket: Connected' : 'WebSocket: Disconnected';
        camStatus.className = state.connected ? 'text-success' : 'text-danger';
    }
}

function updatePipelineUI() {
    if (state.pipelineRunning) {
        elements.pipelineDot.className = 'dot connected';
        elements.pipelineText.textContent = 'Pipeline Active';
        elements.toggleBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Pipeline';
        elements.toggleBtn.className = 'btn btn-danger';
    } else {
        elements.pipelineDot.className = 'dot disconnected';
        elements.pipelineText.textContent = 'Pipeline Offline';
        elements.toggleBtn.innerHTML = '<i class="fas fa-play"></i> Start Pipeline';
        elements.toggleBtn.className = 'btn btn-primary';
    }
}

function renderBindings() {
    if (!elements.bindingsList) return;

    elements.bindingsList.innerHTML = '';

    const relevantGestures = Object.keys(state.bindings);
    if (relevantGestures.length === 0) {
        elements.bindingsList.innerHTML = '<div class="empty-state">No active bindings found</div>';
        return;
    }

    relevantGestures.forEach(gid => {
        const aid = state.bindings[gid];
        const row = document.createElement('div');
        row.className = 'binding-row';
        row.innerHTML = `
            <div class="gesture-info">
                <div class="gesture-id">${gid}</div>
                <div class="action-id">${aid}</div>
            </div>
            <div class="badge badge-purple">Active</div>
        `;
        elements.bindingsList.appendChild(row);
    });
}

function updateRuntimeUI() {
    setInterval(() => {
        if (!state.pipelineRunning || !state.startTime) {
            elements.statRuntime.textContent = '00:00:00';
            return;
        }

        const diff = Date.now() - state.startTime;
        const h = Math.floor(diff / 3600000).toString().padStart(2, '0');
        const m = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
        const s = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');

        elements.statRuntime.textContent = `${h}:${m}:${s}`;
    }, 1000);
}

function setupCameraStream() {
    const container = document.querySelector('.video-container');
    if (!container) return;

    if (state.pipelineRunning) {
        // MJPEG stream from python if we were doing that, 
        // but watchdog usually runs in --no-preview mode.
        // For a true dashboard, we'd need a stream endpoint or use WebRTC.
        // For now, we'll show a message or use the local camera as a placeholder
        // if the user wants real-time local feedback.
        container.innerHTML = `
            <div class="video-placeholder">
                <i class="fas fa-check-circle" style="color: var(--success); font-size: 4rem;"></i>
                <h3 style="margin-top: 1rem">Pipeline Running</h3>
                <p>Watching for gestures in the background...</p>
            </div>
        `;
    }
}

function showToast(msg, type = 'info') {
    const toast = document.getElementById('toast');
    if (!toast) return;

    toast.textContent = msg;
    toast.style.display = 'block';
    toast.style.borderLeft = `5px solid ${type === 'error' ? 'var(--danger)' : 'var(--accent)'}`;

    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

// Start
init();

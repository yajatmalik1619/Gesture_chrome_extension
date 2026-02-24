/**
 * popup.js — GestureSelect Popup Controller (FIXED CAMERA VERSION)
 */

'use strict';

// ── Helpers ────────────────────────────────────────────────────────────────────

function showToast(msg, duration = 2000) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.style.display = 'none'; }, duration);
}

// ── Tab Switching ──────────────────────────────────────────────────────────────

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');

    // Tab-specific initialization
    if (tab.dataset.tab === 'gestures') { loadGestureBindings(); loadExtMappings(); }
    if (tab.dataset.tab === 'record') { loadRecordedGesturesList(); }
    if (tab.dataset.tab === 'camera') { startCamStream(); }
    else { stopCamStream(); }
  });
});

// ── Status Tab ─────────────────────────────────────────────────────────────────

const statusDot = document.getElementById('status-dot');
const connectionStatus = document.getElementById('connection-status');
const wsUrlEl = document.getElementById('ws-url');
const statFps = document.getElementById('stat-fps');
const statMessages = document.getElementById('stat-messages');
const statCommands = document.getElementById('stat-commands');
const gestureCard = document.getElementById('gesture-card');
const gestureName = document.getElementById('gesture-name');
const gestureAction = document.getElementById('gesture-action');
const gestureHand = document.getElementById('gesture-hand');
const alertEl = document.getElementById('alert');
const reconnectBtn = document.getElementById('reconnect-btn');
const footerStatus = document.getElementById('footer-status');

async function updateStatus() {
  try {
    const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
    if (!response) { showDisconnected(); return; }

    const { connectionState, stats, lastGesture, wsUrl, gesturesEnabled } = response;
    statusDot.className = `dot ${connectionState}`;
    connectionStatus.textContent = connectionState.charAt(0).toUpperCase() + connectionState.slice(1);
    wsUrlEl.textContent = wsUrl;
    alertEl.style.display = connectionState === 'disconnected' ? 'block' : 'none';
    statMessages.textContent = stats.messagesReceived;
    statCommands.textContent = stats.commandsExecuted;

    if (typeof gesturesEnabled === 'boolean') applyToggleState(gesturesEnabled, false);

    if (lastGesture) {
      gestureCard.style.display = 'block';
      gestureName.textContent = lastGesture.gesture_id || '--';
      gestureAction.textContent = lastGesture.action_id || '--';
      gestureHand.textContent = lastGesture.hand || '--';
    }

    const stored = await chrome.storage.local.get(['pipelineStatus', 'fps']);
    if (stored.fps) statFps.textContent = Math.round(stored.fps);
    if (stored.pipelineStatus) footerStatus.textContent = stored.pipelineStatus;
  } catch { showDisconnected(); }
}

function showDisconnected() {
  statusDot.className = 'dot disconnected';
  connectionStatus.textContent = 'Disconnected';
  alertEl.style.display = 'block';
}

reconnectBtn.addEventListener('click', async () => {
  reconnectBtn.disabled = true;
  reconnectBtn.textContent = 'Reconnecting…';
  await chrome.runtime.sendMessage({ type: 'RECONNECT' });
  setTimeout(() => { reconnectBtn.disabled = false; reconnectBtn.textContent = 'Reconnect'; updateStatus(); }, 1200);
});

// ── Gesture Actions Toggle ─────────────────────────────────────────────────────

const gesturesToggle = document.getElementById('gestures-toggle');
const toggleHint = document.getElementById('toggle-hint');

function applyToggleState(enabled, persist = true) {
  gesturesToggle.checked = enabled;
  toggleHint.textContent = enabled
    ? 'Detecting gestures — actions active'
    : 'Actions paused — still detecting gestures';
  toggleHint.style.color = enabled ? 'var(--green)' : 'var(--text-faint)';
  if (persist) chrome.runtime.sendMessage({ type: 'SET_GESTURES_ENABLED', enabled });
}

gesturesToggle.addEventListener('change', () => applyToggleState(gesturesToggle.checked));

// ── Pipeline Power Buttons ────────────────────────────────────────────────────

document.getElementById('start-pipeline-btn').addEventListener('click', async () => {
  const btn = document.getElementById('start-pipeline-btn');
  btn.disabled = true; btn.textContent = 'Starting…';
  const r = await chrome.runtime.sendMessage({ type: 'START_PIPELINE' });
  if (r?.ok) {
    showToast('▶ Pipeline starting…');
  } else {
    showToast(r?.error || 'Could not start — is watchdog.py running?', 4000);
  }
  setTimeout(() => { btn.disabled = false; btn.textContent = '▶ Start Pipeline'; updateStatus(); }, 1500);
});

document.getElementById('stop-pipeline-btn').addEventListener('click', async () => {
  const btn = document.getElementById('stop-pipeline-btn');
  btn.disabled = true; btn.textContent = 'Stopping…';
  const r = await chrome.runtime.sendMessage({ type: 'STOP_PIPELINE' });
  if (r?.ok) showToast('■ Pipeline stopped.');
  else showToast(r?.error || 'Could not stop.', 3000);
  setTimeout(() => { btn.disabled = false; btn.textContent = '■ Stop Pipeline'; updateStatus(); }, 1000);
});

updateStatus();
setInterval(updateStatus, 1500);

// ── Storage change listener ────────────────────────────────────────────────────

chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastGesture?.newValue) {
    const g = changes.lastGesture.newValue;
    gestureCard.style.display = 'block';
    gestureName.textContent = g.gesture_id || '--';
    gestureAction.textContent = g.action_id || '--';
    gestureHand.textContent = g.hand || '--';
    // Update camera overlay
    if (camGesture) camGesture.textContent = `${g.gesture_id || ''} (${g.hand || ''})`;
  }
  if (changes.fps?.newValue) {
    statFps.textContent = Math.round(changes.fps.newValue);
    if (camFpsLbl) camFpsLbl.textContent = Math.round(changes.fps.newValue) + ' FPS';
  }
  if (changes.recordingEvent?.newValue) handleRecordingEvent(changes.recordingEvent.newValue);

  if (changes.cfgBindings || changes.cfgGestures || changes.cfgCustom) {
    const activeTab = document.querySelector('.tab.active')?.dataset?.tab;
    if (activeTab === 'gestures') loadGestureBindings();
    if (activeTab === 'record') loadRecordedGesturesList();
  }
});

// ── Camera Stream (FIXED VERSION) ──────────────────────────────────────────────
// Two modes:
// 1. MJPEG: Pipeline running → stream from Python (annotated frames)
// 2. Local: Pipeline off → getUserMedia browser camera (raw preview)

const camFeed = document.getElementById('cam-feed');           // <img> for MJPEG
const camLocal = document.getElementById('cam-local');         // <video> for getUserMedia
const camOffline = document.getElementById('cam-offline');
const camOverlay = document.getElementById('cam-overlay');
const camGesture = document.getElementById('cam-last-gesture');
const camFpsLbl = document.getElementById('cam-fps-label');
const camModeLabel = document.getElementById('cam-mode-label');

let _localStream = null;  // MediaStream from getUserMedia

function _setCamMode(mode) {
  // mode: 'mjpeg' | 'local' | 'offline'
  camFeed.style.display = mode === 'mjpeg' ? 'block' : 'none';
  camLocal.style.display = mode === 'local' ? 'block' : 'none';
  camOverlay.style.display = (mode === 'mjpeg' || mode === 'local') ? 'flex' : 'none';
  camOffline.style.display = mode === 'offline' ? 'flex' : 'none';

  if (camModeLabel) {
    camModeLabel.textContent =
      mode === 'mjpeg' ? '🤖 Pipeline ML' :
        mode === 'local' ? '📷 Local Camera' : '—';
    camModeLabel.style.color =
      mode === 'mjpeg' ? 'var(--green)' :
        mode === 'local' ? 'var(--accent)' : 'var(--text-faint)';
  }
}

async function startCamStream() {
  // Check if pipeline is running
  let pipelineRunning = false;
  try {
    const s = await fetch('http://localhost:8766/status').then(r => r.json());
    pipelineRunning = !!s?.running;
  } catch { /* watchdog not reachable */ }

  if (pipelineRunning) {
    // ── MJPEG mode: Stream from Python ──
    _stopLocalCamera();

    camFeed.onerror = () => {
      console.warn('[Camera] MJPEG stream failed, falling back to local');
      _startLocalCamera();
    };

    camFeed.src = '';
    setTimeout(() => {
      camFeed.src = 'http://localhost:8767/stream?t=' + Date.now();
      _setCamMode('mjpeg');
    }, 100);

  } else {
    // ── Local mode: getUserMedia ──
    await _startLocalCamera();
  }
}

async function _startLocalCamera() {
  if (!navigator.mediaDevices?.getUserMedia) {
    _showCamPermDenied('Camera API not available in this browser.');
    return;
  }

  // ── Check current permission status ────────────────────────────────────────
  let permStatus = 'prompt';
  try {
    const perm = await navigator.permissions.query({ name: 'camera' });
    permStatus = perm.state;

    // Auto-restart if user grants permission via browser settings later
    perm.onchange = () => {
      if (perm.state === 'granted') startCamStream();
    };
  } catch { /* Permissions API unavailable — proceed optimistically */ }

  if (permStatus === 'denied') {
    // Chrome won't show prompt again — guide user to reset in settings
    _showCamPermDenied('denied');
    return;
  }

  // ── 'prompt' or 'granted': call getUserMedia → Chrome shows native prompt ──
  try {
    _localStream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
    });
    camLocal.srcObject = _localStream;
    await camLocal.play();
    _clearCamPermUI();   // remove any stale permission buttons
    _setCamMode('local');
  } catch (err) {
    console.warn('[Camera] getUserMedia failed:', err.name);
    if (err.name === 'NotAllowedError') {
      _showCamPermDenied('denied');
    } else {
      _showCamPermDenied(`Camera error: ${err.message}`);
    }
  }
}

function _showCamPermDenied(reason) {
  _setCamMode('offline');
  const txt = camOffline?.querySelector('.cam-offline-text');
  if (txt) {
    txt.textContent = reason === 'denied'
      ? 'Camera access blocked'
      : (reason || 'Camera unavailable');
  }

  // Show permission grant button (avoid duplicates)
  if (!camOffline?.querySelector('.cam-perm-btn') && reason === 'denied') {
    const grantBtn = document.createElement('button');
    grantBtn.className = 'btn btn-sm btn-primary cam-perm-btn';
    grantBtn.style.cssText = 'margin-top:6px;font-size:11px;';
    grantBtn.textContent = '📷 Grant Camera Access';
    grantBtn.addEventListener('click', () => {
      // Open dedicated permission page — auto-triggers Chrome's native prompt
      // (works even when popup's own permission was previously denied)
      chrome.tabs.create({ url: chrome.runtime.getURL('camera_permission.html') });
    });
    camOffline?.appendChild(grantBtn);
  }
}

function _clearCamPermUI() {
  camOffline?.querySelectorAll('.cam-perm-btn').forEach(el => el.remove());
  const txt = camOffline?.querySelector('.cam-offline-text');
  if (txt) txt.textContent = 'Camera unavailable';
}





function _stopLocalCamera() {
  if (_localStream) {
    _localStream.getTracks().forEach(t => t.stop());
    _localStream = null;
    camLocal.srcObject = null;
  }
}

function stopCamStream() {
  camFeed.src = '';  // Stops MJPEG
  _stopLocalCamera();
  _setCamMode('offline');
}

// Start pipeline button in camera tab
const camStartBtn = document.getElementById('cam-start-btn');
if (camStartBtn) {
  camStartBtn.addEventListener('click', async () => {
    camStartBtn.disabled = true;
    camStartBtn.textContent = 'Starting...';
    const r = await chrome.runtime.sendMessage({ type: 'START_PIPELINE' });
    if (r?.ok) {
      setTimeout(startCamStream, 2500);
    } else {
      showToast(r?.error || 'Could not start pipeline.', 3000);
    }
    camStartBtn.disabled = false;
    camStartBtn.textContent = '▶ Start Pipeline';
  });
}

// ── Gesture Bindings Tab ───────────────────────────────────────────────────────

const builtinList = document.getElementById('builtin-bindings-list');
const customList = document.getElementById('custom-bindings-list');

async function getConfig() {
  const r = await chrome.storage.local.get(['cfgBindings', 'cfgActions', 'cfgGestures', 'cfgCustom']);
  let bindings = r.cfgBindings || {};
  let actions = r.cfgActions || {};
  let gestures = r.cfgGestures || {};
  let custom = r.cfgCustom || {};

  if (Object.keys(actions).length === 0) {
    try {
      const resp = await fetch('http://localhost:8766/config');
      if (resp.ok) {
        const data = await resp.json();
        bindings = data.bindings || {};
        actions = data.actions || {};
        gestures = data.gestures || {};
        custom = data.custom_gestures || {};
        await chrome.storage.local.set({ cfgBindings: bindings, cfgActions: actions, cfgGestures: gestures, cfgCustom: custom });
      }
    } catch { /* watchdog not reachable */ }
  }
  return { bindings, actions, gestures, custom };
}

function buildActionOptions(actions, currentActionId) {
  const none = `<option value="none"${!currentActionId || currentActionId === 'none' ? ' selected' : ''}>— none —</option>`;
  const opts = Object.entries(actions)
    .map(([id]) => `<option value="${id}"${id === currentActionId ? ' selected' : ''}>${id}</option>`)
    .join('');
  return none + opts;
}

const TYPE_BADGE = {
  static: { cls: 'badge-builtin', label: '✋ static' },
  dynamic: { cls: 'badge-dynamic', label: '💨 dynamic' },
  combo: { cls: 'badge-dynamic', label: '✌ combo' },
  custom_static: { cls: 'badge-static', label: '✋ custom' },
  custom_dynamic: { cls: 'badge-dynamic', label: '💨 custom' },
};

async function loadGestureBindings() {
  const { bindings, actions, gestures, custom } = await getConfig();
  const tbody = document.getElementById('mapping-table-body');
  if (!tbody) return;

  const allGestures = [
    ...Object.entries(gestures).filter(([id]) => !id.startsWith('_') && id !== "INDEX_ONLY").map(([id, g]) => ({ id, g, isCustom: false })),
    ...Object.entries(custom).filter(([id]) => !id.startsWith('_') && id !== "INDEX_ONLY").map(([id, g]) => ({ id, g, isCustom: true })),
  ];

  if (allGestures.length === 0) {
    tbody.innerHTML = '<div class="empty-state" style="padding:16px;"><div class="empty-icon" style="font-size:18px;">⋯</div><div style="font-size:11px;">Connect pipeline or start watchdog to load gestures.</div></div>';
    return;
  }

  const actionKeys = Object.keys(actions).filter(k => !k.startsWith('_'));
  const taskOpts = `<option value="none">— none —</option>` +
    actionKeys.map(id => {
      const label = actions[id]?.label || id;
      return `<option value="${id}">${label} (${id})</option>`;
    }).join('');

  tbody.innerHTML = '';
  allGestures.forEach(({ id, g, isCustom }) => {
    const bnd = bindings[id] || 'none';
    const typeInfo = TYPE_BADGE[g?.type] || { cls: 'badge-builtin', label: g?.type || '?' };

    const row = document.createElement('div');
    row.style.cssText = 'display:grid;grid-template-columns:1fr 60px 1fr 32px;gap:4px;padding:6px 10px;border-bottom:1px solid var(--border);align-items:center;';
    row.innerHTML = `
      <div title="${g?.description || id}" style="overflow:hidden;">
        <div style="font-size:11px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${g?.label || id} <span style="font-weight:400;color:var(--text-faint);">(${id})</span></div>
        ${isCustom ? '<div style="font-size:9px;color:var(--text-faint);">custom</div>' : ''}
      </div>
      <span class="gesture-type-badge ${typeInfo.cls}" style="font-size:9px;padding:2px 5px;width:fit-content;">${typeInfo.label}</span>
      <select class="binding-select task-sel" data-gid="${id}" style="font-size:11px;padding:3px 6px;">
        ${taskOpts.replace(`value="${bnd}"`, `value="${bnd}" selected`)}
      </select>
      <button class="btn btn-sm btn-success save-row-btn" data-gid="${id}" style="padding:2px 7px;font-size:13px;">✓</button>
    `;

    const sel = row.querySelector('.task-sel');
    const btn = row.querySelector('.save-row-btn');

    sel.addEventListener('change', () => {
      btn.style.background = sel.value !== bnd ? 'rgba(124,58,237,0.4)' : '';
    });

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      await saveBinding(id, sel.value);
      btn.style.background = '';
      btn.disabled = false;
    });

    if (isCustom) {
      row.title = 'Right-click to delete this custom gesture';
      row.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        if (confirm(`Delete custom gesture "${id}"?`)) deleteCustomGesture(id);
      });
    }

    tbody.appendChild(row);
  });

  loadTasksReference(actions);
}

function loadTasksReference(actions) {
  const ref = document.getElementById('tasks-reference');
  const cnt = document.getElementById('tasks-count');
  if (!ref) return;
  const entries = Object.entries(actions).filter(([k]) => !k.startsWith('_'));
  if (cnt) cnt.textContent = `(${entries.length})`;
  ref.innerHTML = entries.map(([id, a]) =>
    `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid var(--border);">
       <span style="font-size:11px;color:var(--text);font-weight:500;">${a.label || id}</span>
       <span style="font-size:10px;color:var(--text-faint);font-family:monospace;">${id}</span>
     </div>`
  ).join('');
}

document.getElementById('reset-bindings-btn')?.addEventListener('click', async () => {
  if (!confirm('Reset ALL gesture-task mappings to factory defaults?')) return;
  const r = await chrome.runtime.sendMessage({ type: 'RESET_BINDINGS' });
  if (r?.ok) {
    showToast('All bindings reset to defaults.', 2500);
    await chrome.storage.local.remove(['cfgBindings']);
    setTimeout(loadGestureBindings, 400);
  } else {
    showToast(r?.error || 'Could not reset — pipeline must be connected.', 3000);
  }
});

async function saveBinding(gestureId, actionId) {
  const result = await chrome.runtime.sendMessage({ type: 'UPDATE_BINDING', gesture_id: gestureId, action_id: actionId });
  if (result?.ok) {
    showToast(`✓ ${gestureId} → ${actionId}`);
  } else {
    showToast('⚠ Pipeline not connected — binding saved locally only.', 3000);
  }
}

async function deleteCustomGesture(gestureId) {
  const result = await chrome.runtime.sendMessage({ type: 'DELETE_CUSTOM_GESTURE', gesture_id: gestureId });
  if (result?.ok) {
    showToast(`🗑 Deleted: ${gestureId}`);
  } else {
    showToast('⚠ Pipeline not connected — reload to sync.', 3000);
  }
  loadGestureBindings();
  loadRecordedGesturesList();
}

loadGestureBindings();

// ── Extension-side URL / Shortcut Mappings ────────────────────────────────────

const addMappingBtn = document.getElementById('add-mapping-btn');
const addForm = document.getElementById('add-form');
const cancelFormBtn = document.getElementById('cancel-form-btn');
const saveMappingBtn = document.getElementById('save-mapping-btn');
const newGestureId = document.getElementById('new-gesture-id');
const newUrl = document.getElementById('new-url');
const newTabMode = document.getElementById('new-tab-mode');
const newShortcut = document.getElementById('new-shortcut');
const urlFields = document.getElementById('url-fields');
const shortcutFields = document.getElementById('shortcut-fields');
const extMappingList = document.getElementById('ext-mapping-list');
let currentMappingType = 'url';

document.querySelectorAll('.toggle-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentMappingType = btn.dataset.type;
    urlFields.style.display = currentMappingType === 'url' ? 'block' : 'none';
    shortcutFields.style.display = currentMappingType === 'shortcut' ? 'block' : 'none';
  });
});

addMappingBtn.addEventListener('click', () => {
  addForm.style.display = addForm.style.display === 'none' ? 'block' : 'none';
});
cancelFormBtn.addEventListener('click', () => { addForm.style.display = 'none'; clearForm(); });

saveMappingBtn.addEventListener('click', async () => {
  const gestureId = newGestureId.value.trim();
  if (!gestureId) { newGestureId.focus(); return; }
  const mapping = { gestureId, mappingType: currentMappingType };
  if (currentMappingType === 'url') {
    const url = newUrl.value.trim();
    if (!url) { newUrl.focus(); return; }
    mapping.url = url.startsWith('http') ? url : 'https://' + url;
    mapping.newTab = newTabMode.value === 'new';
  } else {
    const sc = newShortcut.value.trim();
    if (!sc) { newShortcut.focus(); return; }
    mapping.shortcut = sc.toLowerCase();
  }
  await chrome.runtime.sendMessage({ type: 'SAVE_CUSTOM_MAPPING', mapping });

  // Tell backend to route this gesture as 'extension_custom'
  await chrome.runtime.sendMessage({ type: 'UPDATE_BINDING', gesture_id: gestureId, action_id: 'extension_custom' });

  addForm.style.display = 'none';
  clearForm();
  loadExtMappings();
  loadGestureBindings(); // refresh the dropdowns above too
  showToast('Mapping saved.');
});

function clearForm() {
  newGestureId.value = ''; newUrl.value = ''; newShortcut.value = ''; newTabMode.value = 'same';
}

async function loadExtMappings() {
  const response = await chrome.runtime.sendMessage({ type: 'GET_CUSTOM_MAPPINGS' });
  const mappings = response?.mappings || [];

  if (mappings.length === 0) {
    extMappingList.innerHTML = '<div class="empty-state" style="padding:10px 0 4px;"><span style="font-size:11px;">No URL/shortcut actions yet.</span></div>';
    return;
  }

  extMappingList.innerHTML = '';
  mappings.forEach(m => {
    const desc = m.mappingType === 'url'
      ? (m.url.length > 38 ? m.url.substring(0, 38) + '…' : m.url) + (m.newTab ? ' (new tab)' : '')
      : m.shortcut;

    const item = document.createElement('div');
    item.className = 'gesture-row';
    item.innerHTML = `
      <div class="gesture-row-id" style="width:110px;min-width:90px;flex:1;overflow:hidden;">
        <div class="gesture-id-label" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${m.gestureId}</div>
        <div style="font-size:10px;color:var(--text-faint);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${desc}</div>
      </div>
      <span class="gesture-type-badge ${m.mappingType === 'url' ? 'badge-static' : 'badge-dynamic'}" style="flex-shrink:0;">${m.mappingType}</span>
      <button class="btn btn-sm btn-danger del-ext-btn" data-id="${m.gestureId}" style="padding:4px 8px;flex-shrink:0;">✕</button>
    `;
    extMappingList.appendChild(item);
  });

  extMappingList.querySelectorAll('.del-ext-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      await chrome.runtime.sendMessage({ type: 'DELETE_CUSTOM_MAPPING', gestureId: btn.dataset.id });

      // Reset Python backend binding to none
      await chrome.runtime.sendMessage({ type: 'UPDATE_BINDING', gesture_id: btn.dataset.id, action_id: 'none' });

      loadExtMappings();
      loadGestureBindings();
      showToast('Mapping removed.');
    });
  });
}

loadExtMappings();

// ── Record Tab ─────────────────────────────────────────────────────────────────

const recGestureId = document.getElementById('rec-gesture-id');
const recLabel = document.getElementById('rec-label');
const recType = document.getElementById('rec-type');
const recHand = document.getElementById('rec-hand');
const startRecordBtn = document.getElementById('start-record-btn');
const cancelRecordBtn = document.getElementById('cancel-record-btn');
const recordActive = document.getElementById('record-active');
const recordForm = document.getElementById('record-form');
const recordMessage = document.getElementById('record-message');
const recordProgressBar = document.getElementById('record-progress-bar');
const recordProgressText = document.getElementById('record-progress-text');
const typeHint = document.getElementById('type-hint');
const recStatus = document.getElementById('rec-status');
const recCustomList = document.getElementById('rec-custom-list');

recType.addEventListener('change', () => {
  typeHint.textContent = recType.value === 'static'
    ? 'Hold a fixed hand pose. 6 samples × 2 seconds each.'
    : 'Perform a clear motion (swipe, wave). 6 samples required.';
});

let isRecording = false;

chrome.storage.local.get(['recordingActive', 'recordingEvent'], (result) => {
  if (result.recordingActive) {
    isRecording = true;
    recordActive.classList.add('on');
    recordForm.style.display = 'none';
    if (result.recordingEvent) handleRecordingEvent(result.recordingEvent);
  }
});

startRecordBtn.addEventListener('click', async () => {
  const gestureId = recGestureId.value.trim().replace(/\s+/g, '_').toLowerCase();
  const label = recLabel.value.trim() || gestureId;
  if (!gestureId) { showRecStatus('Enter a Gesture ID first.', true); return; }

  const result = await chrome.runtime.sendMessage({
    type: 'START_RECORDING',
    gesture_id: gestureId, label,
    gesture_type: recType.value,
    hand: recHand.value
  });

  if (result?.ok) {
    isRecording = true;
    chrome.storage.local.set({ recordingActive: true });
    recordActive.classList.add('on');
    recordForm.style.display = 'none';
    recStatus.style.display = 'none';
  } else {
    showRecStatus('Pipeline not connected. Start main.py first.', true);
  }
});

cancelRecordBtn.addEventListener('click', async () => {
  await chrome.runtime.sendMessage({ type: 'CANCEL_RECORDING' });
  stopRecording();
});

function stopRecording() {
  isRecording = false;
  chrome.storage.local.set({ recordingActive: false });
  recordActive.classList.remove('on');
  recordForm.style.display = 'block';
  recordProgressBar.style.width = '0%';
  recordProgressText.textContent = '0 / 6 samples';
  recordMessage.textContent = 'Show your gesture to the camera';
  loadRecordedGesturesList();
}

function showRecStatus(msg, isError) {
  recStatus.style.display = 'block';
  recStatus.textContent = msg;
  recStatus.style.cssText += isError
    ? ';border:1px solid rgba(248,113,113,0.3);color:#fca5a5;background:rgba(248,113,113,0.1);'
    : ';border:1px solid rgba(52,211,153,0.3);color:#6ee7b7;background:rgba(52,211,153,0.1);';
  setTimeout(() => { recStatus.style.display = 'none'; }, 4000);
}

function handleRecordingEvent(event) {
  if (!isRecording && event.event !== 'complete') return;

  const { message, samples_done, samples_total, countdown } = event;

  if (message) {
    recordMessage.textContent = countdown != null ? `${message} — ${countdown}` : message;
  }

  if (typeof samples_done === 'number' && typeof samples_total === 'number') {
    const pct = (samples_done / samples_total) * 100;
    recordProgressBar.style.width = pct + '%';
    recordProgressText.textContent = `${samples_done} / ${samples_total} samples`;
  }

  if (event.event === 'complete') {
    stopRecording();
    showRecStatus('✓ Gesture saved! Map it in the Gestures tab.', false);
    loadGestureBindings();
  } else if (event.event === 'cancelled') {
    stopRecording();
  }
}

async function loadRecordedGesturesList() {
  const { custom } = await getConfig();
  const entries = Object.entries(custom);

  if (entries.length === 0) {
    recCustomList.innerHTML = '<div class="empty-state"><div class="empty-icon">🤚</div>No recorded gestures yet.</div>';
    return;
  }

  recCustomList.innerHTML = '';
  entries.forEach(([gid, g]) => {
    const item = document.createElement('div');
    item.className = 'gesture-row';
    const badgeClass = g.type === 'dynamic' ? 'badge-dynamic' : 'badge-static';
    item.innerHTML = `
      <div style="flex:1;min-width:0;">
        <div class="gesture-id-label" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${gid}</div>
        <div style="font-size:10px;color:var(--text-faint);margin-top:2px;">${g.label || ''} &nbsp; ${(g.recording?.num_samples || '?')} samples</div>
      </div>
      <span class="gesture-type-badge ${badgeClass}">${g.type || 'static'}</span>
      <button class="btn btn-sm btn-danger rec-del-btn" data-id="${gid}" style="padding:4px 8px;">✕</button>
    `;
    recCustomList.appendChild(item);
  });

  recCustomList.querySelectorAll('.rec-del-btn').forEach(btn => {
    let confirm = false;
    btn.addEventListener('click', () => {
      if (!confirm) {
        confirm = true;
        btn.textContent = '?';
        setTimeout(() => { confirm = false; btn.textContent = '✕'; }, 2500);
      } else {
        deleteCustomGesture(btn.dataset.id);
      }
    });
  });
}

loadRecordedGesturesList();
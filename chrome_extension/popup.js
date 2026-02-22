/**
 * popup.js - GestureSelect Popup Controller
 */

// ── Tab Switching ─────────────────────────────────────────────────────────────

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
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

    const { connectionState, stats, lastGesture, wsUrl } = response;

    statusDot.className = `dot ${connectionState}`;
    connectionStatus.textContent = connectionState.charAt(0).toUpperCase() + connectionState.slice(1);
    wsUrlEl.textContent = wsUrl;
    alertEl.style.display = connectionState === 'disconnected' ? 'block' : 'none';

    statMessages.textContent = stats.messagesReceived;
    statCommands.textContent = stats.commandsExecuted;

    if (lastGesture) {
      gestureCard.style.display = 'block';
      gestureName.textContent = lastGesture.gesture_id || '--';
      gestureAction.textContent = lastGesture.action_id || '--';
      gestureHand.textContent = lastGesture.hand || '--';
    }

    const stored = await chrome.storage.local.get(['pipelineStatus', 'fps']);
    if (stored.fps) statFps.textContent = Math.round(stored.fps);
    if (stored.pipelineStatus) footerStatus.textContent = stored.pipelineStatus;

  } catch (err) {
    showDisconnected();
  }
}

function showDisconnected() {
  statusDot.className = 'dot disconnected';
  connectionStatus.textContent = 'Disconnected';
  alertEl.style.display = 'block';
}

reconnectBtn.addEventListener('click', async () => {
  reconnectBtn.disabled = true;
  reconnectBtn.textContent = 'Reconnecting...';
  await chrome.runtime.sendMessage({ type: 'RECONNECT' });
  setTimeout(() => {
    reconnectBtn.disabled = false;
    reconnectBtn.textContent = 'Reconnect';
    updateStatus();
  }, 1200);
});

updateStatus();
setInterval(updateStatus, 1500);

chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastGesture?.newValue) {
    const g = changes.lastGesture.newValue;
    gestureCard.style.display = 'block';
    gestureName.textContent = g.gesture_id || '--';
    gestureAction.textContent = g.action_id || '--';
    gestureHand.textContent = g.hand || '--';
  }
  if (changes.fps?.newValue) {
    statFps.textContent = Math.round(changes.fps.newValue);
  }
  if (changes.recordingEvent?.newValue) {
    handleRecordingEvent(changes.recordingEvent.newValue);
  }
});

// ── Mappings Tab ───────────────────────────────────────────────────────────────

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
const gestureList = document.getElementById('gesture-list');

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

cancelFormBtn.addEventListener('click', () => {
  addForm.style.display = 'none';
  clearForm();
});

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
  addForm.style.display = 'none';
  clearForm();
  loadMappings();
});

function clearForm() {
  newGestureId.value = '';
  newUrl.value = '';
  newShortcut.value = '';
  newTabMode.value = 'same';
}

async function loadMappings() {
  const response = await chrome.runtime.sendMessage({ type: 'GET_CUSTOM_MAPPINGS' });
  const mappings = response?.mappings || [];

  if (mappings.length === 0) {
    gestureList.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">[ _ ]</div>
        No custom mappings yet.<br>Record a gesture, then map it here.
      </div>`;
    return;
  }

  gestureList.innerHTML = '';
  mappings.forEach(m => {
    const item = document.createElement('div');
    item.className = 'gesture-item';

    const desc = m.mappingType === 'url'
      ? (m.url.length > 35 ? m.url.substring(0, 35) + '...' : m.url) + (m.newTab ? ' (new tab)' : '')
      : m.shortcut;

    item.innerHTML = `
      <div class="gesture-item-name">
        <div class="gesture-item-label">${m.gestureId}</div>
        <div class="gesture-item-mapping">${desc}</div>
      </div>
      <div class="type-badge ${m.mappingType === 'url' ? 'type-url' : 'type-shortcut'}">${m.mappingType}</div>
      <button class="btn btn-danger btn-sm delete-btn" data-id="${m.gestureId}">Del</button>
    `;
    gestureList.appendChild(item);
  });

  document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      await chrome.runtime.sendMessage({ type: 'DELETE_CUSTOM_MAPPING', gestureId: btn.dataset.id });
      loadMappings();
    });
  });
}

loadMappings();

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

recType.addEventListener('change', () => {
  if (recType.value === 'static') {
    typeHint.textContent = 'Hold a fixed hand pose. 6 samples x 2 seconds each.';
  } else {
    typeHint.textContent = 'Perform a clear motion (swipe, wave). 6 samples required.';
  }
});

let isRecording = false;

// Restore recording state if pipeline was mid-recording when popup was last closed
chrome.storage.local.get(['recordingActive', 'recordingEvent'], (result) => {
  if (result.recordingActive) {
    isRecording = true;
    recordActive.classList.add('active');
    recordForm.style.display = 'none';
    if (result.recordingEvent) handleRecordingEvent(result.recordingEvent);
  }
});

startRecordBtn.addEventListener('click', async () => {
  const gestureId = recGestureId.value.trim().replace(/\s+/g, '_').toLowerCase();
  const label = recLabel.value.trim() || gestureId;

  if (!gestureId) {
    showRecStatus('Enter a gesture ID first.', true);
    return;
  }

  const msg = {
    type: 'START_RECORDING',
    gesture_id: gestureId,
    label,
    gesture_type: recType.value,
    hand: recHand.value
  };

  const result = await chrome.runtime.sendMessage(msg);

  if (result?.ok) {
    isRecording = true;
    chrome.storage.local.set({ recordingActive: true });
    recordActive.classList.add('active');
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
  recordActive.classList.remove('active');
  recordForm.style.display = 'block';
  recordProgressBar.style.width = '0%';
  recordProgressText.textContent = '0 / 6 samples';
  recordMessage.textContent = 'Show your gesture to the camera';
}

function showRecStatus(msg, isError) {
  recStatus.style.display = 'block';
  recStatus.innerHTML = msg;
  recStatus.style.borderColor = isError ? 'rgba(248,113,113,0.3)' : 'rgba(52,211,153,0.3)';
  recStatus.style.color = isError ? '#fca5a5' : '#6ee7b7';
  recStatus.style.background = isError ? 'rgba(248,113,113,0.1)' : 'rgba(52,211,153,0.1)';
  setTimeout(() => { recStatus.style.display = 'none'; }, 4000);
}

function handleRecordingEvent(event) {
  if (!isRecording) return;

  const { phase, message, samples_done, samples_total, countdown } = event;

  if (message) {
    recordMessage.textContent = countdown ? `${message} — ${countdown}` : message;
  }

  if (typeof samples_done === 'number' && typeof samples_total === 'number') {
    const pct = (samples_done / samples_total) * 100;
    recordProgressBar.style.width = pct + '%';
    recordProgressText.textContent = `${samples_done} / ${samples_total} samples`;
  }

  if (phase === 'done') {
    stopRecording();
    showRecStatus('Gesture captured successfully. Map it in the Mappings tab.', false);
    loadMappings();
  } else if (phase === 'cancelled') {
    stopRecording();
  }
}

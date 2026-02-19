/**
 * popup.js - Popup UI Controller
 */

// ─── DOM Elements ─────────────────────────────────────────────────────────────

const statusDot = document.getElementById('status-dot');
const connectionStatus = document.getElementById('connection-status');
const wsUrl = document.getElementById('ws-url');
const fpsDisplay = document.getElementById('fps');
const gestureDisplay = document.getElementById('gesture-display');
const gestureName = document.getElementById('gesture-name');
const gestureAction = document.getElementById('gesture-action');
const gestureHand = document.getElementById('gesture-hand');
const statMessages = document.getElementById('stat-messages');
const statCommands = document.getElementById('stat-commands');
const reconnectBtn = document.getElementById('reconnect-btn');
const warning = document.getElementById('warning');

// ─── Update UI ────────────────────────────────────────────────────────────────

async function updateUI() {
  try {
    // Get status from background script
    const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
    
    if (!response) {
      showDisconnected();
      return;
    }
    
    const { connectionState, stats, lastGesture, wsUrl: url } = response;
    
    // Connection status
    statusDot.className = `status-dot ${connectionState}`;
    connectionStatus.textContent = connectionState.charAt(0).toUpperCase() + connectionState.slice(1);
    wsUrl.textContent = url;
    
    // Show/hide warning
    warning.style.display = connectionState === 'disconnected' ? 'block' : 'none';
    
    // Stats
    statMessages.textContent = stats.messagesReceived;
    statCommands.textContent = stats.commandsExecuted;
    
    // Last gesture
    if (lastGesture) {
      gestureDisplay.style.display = 'block';
      gestureName.textContent = lastGesture.gesture_id || '—';
      gestureAction.textContent = lastGesture.action_id || '—';
      gestureHand.textContent = lastGesture.hand || '—';
    }
    
    // Get pipeline status from storage
    const { pipelineStatus, fps } = await chrome.storage.local.get(['pipelineStatus', 'fps']);
    if (fps) {
      fpsDisplay.textContent = Math.round(fps) + ' fps';
    }
    
  } catch (err) {
    console.error('Error updating UI:', err);
    showDisconnected();
  }
}

function showDisconnected() {
  statusDot.className = 'status-dot disconnected';
  connectionStatus.textContent = 'Disconnected';
  warning.style.display = 'block';
}

// ─── Reconnect Button ─────────────────────────────────────────────────────────

reconnectBtn.addEventListener('click', async () => {
  reconnectBtn.disabled = true;
  reconnectBtn.textContent = 'Reconnecting...';
  
  await chrome.runtime.sendMessage({ type: 'RECONNECT' });
  
  setTimeout(() => {
    reconnectBtn.disabled = false;
    reconnectBtn.textContent = 'Reconnect';
    updateUI();
  }, 1000);
});

// ─── Auto-refresh ─────────────────────────────────────────────────────────────

updateUI();
setInterval(updateUI, 1000);

// Listen for storage changes (real-time updates)
chrome.storage.onChanged.addListener((changes) => {
  if (changes.lastGesture) {
    const g = changes.lastGesture.newValue;
    if (g) {
      gestureDisplay.style.display = 'block';
      gestureName.textContent = g.gesture_id || '—';
      gestureAction.textContent = g.action_id || '—';
      gestureHand.textContent = g.hand || '—';
    }
  }
  
  if (changes.fps) {
    const fps = changes.fps.newValue;
    fpsDisplay.textContent = Math.round(fps) + ' fps';
  }
});

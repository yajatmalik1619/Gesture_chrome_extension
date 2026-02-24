/**
 * background.js - Service Worker
 *
 * Connects to Python WebSocket server (ws://localhost:8765)
 * Receives EXECUTION commands and routes them to appropriate handlers.
 * Forwards binding updates and custom gesture deletions back to the pipeline.
 */

const WS_URL = 'ws://localhost:8765';
const WATCHDOG_URL = 'http://localhost:8766';
let ws = null;
let reconnectTimer = null;
let connectionState = 'disconnected';
let userDisconnected = false; // true after user manually stops — suppresses auto-reconnect
let lastGesture = null;
let stats = { messagesReceived: 0, commandsExecuted: 0, errors: 0 };
let gesturesEnabled = true;

// Restore persisted toggle state
chrome.storage.local.get(['gesturesEnabled'], (r) => {
  if (typeof r.gesturesEnabled === 'boolean') gesturesEnabled = r.gesturesEnabled;
});

// Load config from watchdog HTTP on startup (populates gestures/actions without needing WS)
async function loadConfigFromHttp() {
  try {
    const r = await fetch(`${WATCHDOG_URL}/config`);
    if (!r.ok) return;
    const data = await r.json();
    chrome.storage.local.set({
      config: data,
      cfgBindings: data.bindings || {},
      cfgActions: data.actions || {},
      cfgGestures: data.gestures || {},
      cfgCustom: data.custom_gestures || {},
    });
  } catch { /* watchdog not running yet */ }
}
loadConfigFromHttp();
setInterval(loadConfigFromHttp, 30000); // refresh every 30s

// ── WebSocket Connection ───────────────────────────────────────────────────────

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  connectionState = 'connecting';
  updateBadge();
  console.log('[GestureSelect] Connecting to', WS_URL);

  try {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[GestureSelect] Connected');
      connectionState = 'connected';
      stats.errors = 0;
      updateBadge();
      clearTimeout(reconnectTimer);
    };

    ws.onmessage = (event) => {
      stats.messagesReceived++;
      try {
        const data = JSON.parse(event.data);
        handleMessage(data);
      } catch (err) {
        console.error('[GestureSelect] Parse error:', err);
        stats.errors++;
      }
    };

    ws.onerror = (error) => {
      console.error('[GestureSelect] WebSocket error:', error);
      stats.errors++;
    };

    ws.onclose = () => {
      console.log('[GestureSelect] Disconnected');
      connectionState = 'disconnected';
      updateBadge();
      if (!userDisconnected) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

  } catch (err) {
    console.error('[GestureSelect] Connection failed:', err);
    connectionState = 'disconnected';
    stats.errors++;
    updateBadge();
    reconnectTimer = setTimeout(connect, 5000);
  }
}

// ── Message Router ─────────────────────────────────────────────────────────────

function handleMessage(data) {
  const type = data.type;

  if (type === 'ACTION') {
    lastGesture = {
      gesture_id: data.gesture_id,
      action_id: data.action_id,
      hand: data.hand,
      timestamp: data.timestamp
    };
    chrome.storage.local.set({ lastGesture });

    // Execute any extension-side custom mappings (URL open / keyboard shortcut)
    // ONLY if the backend confirms this gesture is mapped to 'extension_custom'
    if (gesturesEnabled && data.action_id === 'extension_custom') {
      chrome.storage.local.get(['customMappings'], (result) => {
        const mappings = result.customMappings || [];
        const match = mappings.find(m => m.gestureId === data.gesture_id);
        if (match) {
          if (match.mappingType === 'url') {
            navigateToUrl({ url: match.url, new_tab: match.newTab || false });
          } else if (match.mappingType === 'shortcut') {
            executeKeyboardShortcut({ shortcut: match.shortcut });
          }
        }
      });
    }

  } else if (type === 'EXECUTION') {
    stats.commandsExecuted++;
    if (gesturesEnabled) executeCommand(data);

  } else if (type === 'STATUS') {
    chrome.storage.local.set({ pipelineStatus: data.status, fps: data.fps });

  } else if (type === 'CONFIG_SNAPSHOT') {
    // Store full config and each sub-section individually for easy popup access
    chrome.storage.local.set({
      config: data,
      cfgBindings: data.bindings || {},
      cfgActions: data.actions || {},
      cfgGestures: data.gestures || {},
      cfgCustom: data.custom_gestures || {},
    });

  } else if (type === 'RECORDING_EVENT') {
    // data.event: "state_change" | "sample_saved" | "complete" | "cancelled"
    const isActive = data.event !== 'complete' && data.event !== 'cancelled';
    chrome.storage.local.set({ recordingEvent: data, recordingActive: isActive });
  }
}

// ── Command Execution ──────────────────────────────────────────────────────────

async function executeCommand(exec) {
  const { command, params } = exec;
  console.log(`[Exec] ${command}`, params);

  try {
    switch (command) {
      case 'KEYBOARD_SHORTCUT': await executeKeyboardShortcut(params); break;
      case 'SCROLL': await executeScroll(params); break;
      case 'SCROLL_STOP': await executeScrollStop(); break;
      case 'MINIMIZE_WINDOW': await minimizeWindow(); break;
      case 'MAXIMIZE_WINDOW': await maximizeWindow(); break;
      case 'NAVIGATE_URL': await navigateToUrl(params); break;
      default: console.warn('[Exec] Unknown command:', command);
    }
  } catch (err) {
    console.error(`[Exec] Error executing ${command}:`, err);
    stats.errors++;
  }
}

// ── Keyboard Shortcuts ─────────────────────────────────────────────────────────

async function executeKeyboardShortcut(params) {
  const { shortcut: rawShortcut, repeat = 1 } = params;
  const shortcut = rawShortcut.toLowerCase().trim(); // normalise case from Python
  const keys = shortcut.split('+').map(k => k.trim());
  const modifiers = {
    ctrl: keys.includes('ctrl'),
    alt: keys.includes('alt'),
    shift: keys.includes('shift'),
    meta: keys.includes('cmd') || keys.includes('meta')
  };
  const mainKey = keys.find(k => !['ctrl', 'alt', 'shift', 'cmd', 'meta'].includes(k));

  if (shortcut.match(/ctrl\+(shift\+)?tab/i)) await switchTab(shortcut.includes('shift') ? -repeat : repeat);
  else if (shortcut === 'ctrl+w' || shortcut === 'cmd+w') await closeCurrentTab();
  else if (shortcut === 'ctrl+t' || shortcut === 'cmd+t') await openNewTab();
  else if (shortcut === 'ctrl+shift+t' || shortcut === 'cmd+shift+t') await reopenClosedTab();
  else if (shortcut === 'f5' || shortcut === 'ctrl+r' || shortcut === 'cmd+r') await refreshPage();
  else if (shortcut === 'f11' || shortcut === 'ctrl+shift+f') await toggleFullscreen();
  else if (shortcut === 'alt+left' || shortcut === 'cmd+[') await goBack();
  else if (shortcut === 'alt+right' || shortcut === 'cmd+]') await goForward();
  else await sendToContent({ type: 'KEYBOARD_SHORTCUT', shortcut, modifiers, key: mainKey, repeat });
}

// ── Tab Management ─────────────────────────────────────────────────────────────

async function switchTab(delta) {
  const tabs = await chrome.tabs.query({ currentWindow: true });
  const cur = tabs.find(t => t.active);
  if (!cur) return;
  let next = tabs.indexOf(cur) + delta;
  if (next < 0) next = tabs.length - 1;
  if (next >= tabs.length) next = 0;
  await chrome.tabs.update(tabs[next].id, { active: true });
}
async function closeCurrentTab() { const [t] = await chrome.tabs.query({ active: true, currentWindow: true }); if (t) await chrome.tabs.remove(t.id); }
async function openNewTab() { await chrome.tabs.create({}); }
async function reopenClosedTab() { const s = await chrome.sessions.getRecentlyClosed({ maxResults: 1 }); if (s.length) await chrome.sessions.restore(s[0].sessionId); }
async function refreshPage() { const [t] = await chrome.tabs.query({ active: true, currentWindow: true }); if (t) await chrome.tabs.reload(t.id); }

// ── Scrolling ──────────────────────────────────────────────────────────────────

async function executeScroll(params) { await sendToContent({ type: 'SCROLL', ...params }); }
async function executeScrollStop() { await sendToContent({ type: 'SCROLL_STOP' }); }

// ── Window Management ──────────────────────────────────────────────────────────

async function minimizeWindow() {
  const w = await chrome.windows.getCurrent();
  await chrome.windows.update(w.id, { state: 'minimized' });
}
async function maximizeWindow() {
  const w = await chrome.windows.getCurrent();
  await chrome.windows.update(w.id, { state: w.state === 'maximized' ? 'normal' : 'maximized' });
}
async function toggleFullscreen() {
  // Chrome API for fullscreen — synthetic F11 keydown blocked by browser security
  const w = await chrome.windows.getCurrent();
  const next = w.state === 'fullscreen' ? 'normal' : 'fullscreen';
  await chrome.windows.update(w.id, { state: next });
}

async function goBack() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (t) await chrome.tabs.goBack(t.id);
}

async function goForward() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (t) await chrome.tabs.goForward(t.id);
}

// ── Text Selection & Search ────────────────────────────────────────────────────

async function searchSelectedText() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => window.getSelection().toString()
  });
  const text = result?.result?.trim();
  if (text) await chrome.tabs.create({ url: `https://www.google.com/search?q=${encodeURIComponent(text)}` });
}

// ── URL Navigation ─────────────────────────────────────────────────────────────

async function navigateToUrl(params) {
  const { url, new_tab } = params;
  if (new_tab) {
    await chrome.tabs.create({ url });
  } else {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await chrome.tabs.update(tab.id, { url });
  }
}

// ── Content Script Bridge ──────────────────────────────────────────────────────

async function sendToContent(message) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  try {
    await chrome.tabs.sendMessage(tab.id, message);
  } catch (err) {
    console.log('[GestureSelect] Injecting content script');
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content_script.js'] });
    setTimeout(() => chrome.tabs.sendMessage(tab.id, message).catch(() => { }), 100);
  }
}

// ── Badge & Status ─────────────────────────────────────────────────────────────

function updateBadge() {
  const colors = { connected: '#10b981', connecting: '#f59e0b', disconnected: '#ef4444' };
  const texts = { connected: '●', connecting: '…', disconnected: '○' };
  chrome.action.setBadgeBackgroundColor({ color: colors[connectionState] });
  chrome.action.setBadgeText({ text: texts[connectionState] });
}

// ── Popup Communication ────────────────────────────────────────────────────────

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handlePopupMessage(message).then(sendResponse).catch(err => {
    console.error('[GestureSelect] Message handler error:', err);
    sendResponse({ ok: false, error: err.message });
  });
  return true;
});

function wsSend(payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(payload));
    return true;
  }
  return false;
}

async function handlePopupMessage(message) {
  switch (message.type) {

    case 'GET_STATUS':
      return { connectionState, stats, lastGesture, wsUrl: WS_URL, gesturesEnabled };

    case 'SET_GESTURES_ENABLED':
      gesturesEnabled = !!message.enabled;
      chrome.storage.local.set({ gesturesEnabled });
      return { ok: true, gesturesEnabled };

    case 'RESET_BINDINGS': {
      const sent = wsSend({ type: 'RESET_BINDINGS' });
      if (!sent) return { ok: false, error: 'Pipeline not connected — start it first then retry.' };
      // Clear local cache so next load refreshes from Python
      await chrome.storage.local.remove(['cfgBindings']);
      return { ok: true };
    }


    case 'START_PIPELINE': {
      try {
        userDisconnected = false; // Re-enable auto-reconnect after start
        const r = await fetch(`${WATCHDOG_URL}/start`, { method: 'POST' });
        const d = await r.json();
        // Give pipeline 2s to boot then attempt WS connect
        setTimeout(connect, 2000);
        return { ok: d.ok, status: d.status, pid: d.pid };
      } catch {
        return { ok: false, error: 'Watchdog not running. Run setup_autostart.ps1 first.' };
      }
    }

    case 'STOP_PIPELINE': {
      try {
        userDisconnected = true; // Suppress auto-reconnect after stop
        clearTimeout(reconnectTimer);
        if (ws) { ws.close(); ws = null; }
        const r = await fetch(`${WATCHDOG_URL}/stop`, { method: 'POST' });
        const d = await r.json();
        return { ok: d.ok, status: d.status };
      } catch {
        return { ok: false, error: 'Watchdog not reachable.' };
      }
    }

    case 'RECONNECT':
      userDisconnected = false;
      connect();
      return { ok: true };

    // ── Recording ──────────────────────────────────────────────────────────
    case 'START_RECORDING':
      return { ok: wsSend(message) };

    case 'CANCEL_RECORDING':
      wsSend({ type: 'CANCEL_RECORDING' });
      return { ok: true };

    // ── Binding / Gesture management (forwarded to Python via WS) ──────────
    case 'UPDATE_BINDING': {
      // message: { type, gesture_id, action_id }
      const sent = wsSend(message);
      if (sent) {
        // Optimistically update local cache so popup reflects change immediately
        const r = await chrome.storage.local.get(['cfgBindings']);
        const b = r.cfgBindings || {};
        b[message.gesture_id] = message.action_id;
        await chrome.storage.local.set({ cfgBindings: b });
      }
      return { ok: sent };
    }

    case 'DELETE_CUSTOM_GESTURE': {
      // message: { type, gesture_id }
      const sent = wsSend(message);
      if (sent) {
        const r = await chrome.storage.local.get(['cfgCustom', 'cfgBindings']);
        const cg = r.cfgCustom || {};
        const b = r.cfgBindings || {};
        delete cg[message.gesture_id];
        delete b[message.gesture_id];
        await chrome.storage.local.set({ cfgCustom: cg, cfgBindings: b });
      }
      return { ok: sent };
    }

    // ── Extension-side custom URL/shortcut mappings ────────────────────────
    case 'GET_CUSTOM_MAPPINGS': {
      const r = await chrome.storage.local.get(['customMappings']);
      return { mappings: r.customMappings || [] };
    }

    case 'SAVE_CUSTOM_MAPPING': {
      const r = await chrome.storage.local.get(['customMappings']);
      const mappings = r.customMappings || [];
      const idx = mappings.findIndex(m => m.gestureId === message.mapping.gestureId);
      if (idx >= 0) mappings[idx] = message.mapping; else mappings.push(message.mapping);
      await chrome.storage.local.set({ customMappings: mappings });
      return { ok: true };
    }

    case 'DELETE_CUSTOM_MAPPING': {
      const r = await chrome.storage.local.get(['customMappings']);
      const mappings = (r.customMappings || []).filter(m => m.gestureId !== message.gestureId);
      await chrome.storage.local.set({ customMappings: mappings });
      return { ok: true };
    }

    default:
      return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

// ── Initialization ─────────────────────────────────────────────────────────────

console.log('[GestureSelect] Service worker started');
connect();

async function checkPipelineStatus() {
  try {
    const resp = await fetch('http://localhost:8766/status');
    if (resp.ok) {
      const data = await resp.json();
      chrome.storage.local.set({ pipelineHttpStatus: data.running ? 'running' : 'stopped' });
    }
  } catch {
    chrome.storage.local.set({ pipelineHttpStatus: 'stopped' });
  }
}
checkPipelineStatus();
setInterval(checkPipelineStatus, 5000);

chrome.alarms.create('keepAlive', { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'keepAlive' && connectionState === 'disconnected') connect();
});

setInterval(() => {
  if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'PING' }));
}, 20000);

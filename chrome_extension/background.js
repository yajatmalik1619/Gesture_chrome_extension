/**
 * background.js - Service Worker
 * 
 * Connects to Python WebSocket server (ws://localhost:8765)
 * Receives EXECUTION commands and routes them to appropriate handlers
 */

const WS_URL = 'ws://localhost:8765';
let ws = null;
let reconnectTimer = null;
let connectionState = 'disconnected'; // 'connected' | 'disconnected' | 'connecting'
let lastGesture = null;
let stats = { messagesReceived: 0, commandsExecuted: 0, errors: 0 };

//  WebSocket Connection 
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
      // Auto-reconnect after 3 seconds
      reconnectTimer = setTimeout(connect, 3000);
    };
    
  } catch (err) {
    console.error('[GestureSelect] Connection failed:', err);
    connectionState = 'disconnected';
    stats.errors++;
    updateBadge();
    reconnectTimer = setTimeout(connect, 5000);
  }
}

//  Message Router

function handleMessage(data) {
  const type = data.type;
  
  if (type === 'ACTION') {
    // Gesture detection event - update UI only
    lastGesture = {
      gesture_id: data.gesture_id,
      action_id: data.action_id,
      hand: data.hand,
      timestamp: data.timestamp
    };
    chrome.storage.local.set({ lastGesture });
    
    // Check custom gesture mappings
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
    
  } else if (type === 'EXECUTION') {
    // Command to execute
    stats.commandsExecuted++;
    executeCommand(data);
    
  } else if (type === 'STATUS') {
    // Pipeline status heartbeat
    chrome.storage.local.set({ pipelineStatus: data.status, fps: data.fps });
    
  } else if (type === 'CONFIG_SNAPSHOT') {
    // Initial config sent on connection
    chrome.storage.local.set({ config: data });
    
  } else if (type === 'RECORDING_EVENT') {
    // Custom gesture recording progress
    const isActive = data.phase !== 'done' && data.phase !== 'cancelled';
    chrome.storage.local.set({ recordingEvent: data, recordingActive: isActive });
  }
}

//Command Execution

async function executeCommand(exec) {
  const { command, params, action_id } = exec;
  
  console.log(`[Exec] ${command}`, params);
  
  try {
    switch (command) {
      case 'KEYBOARD_SHORTCUT':
        await executeKeyboardShortcut(params);
        break;
        
      case 'SCROLL':
        await executeScroll(params);
        break;
        
      case 'SCROLL_STOP':
        await executeScrollStop();
        break;
        
      case 'MINIMIZE_WINDOW':
        await minimizeWindow();
        break;
        
      case 'MAXIMIZE_WINDOW':
        await maximizeWindow();
        break;
        
      case 'TEXT_SELECT_START':
        await sendToContent({ type: 'TEXT_SELECT_START', params });
        break;
        
      case 'TEXT_SELECT_DRAG':
        await sendToContent({ type: 'TEXT_SELECT_DRAG', params });
        break;
        
      case 'TEXT_SEARCH_GOOGLE':
        await searchSelectedText();
        break;
        
      case 'NAVIGATE_URL':
        await navigateToUrl(params);
        break;
        
      default:
        console.warn('[Exec] Unknown command:', command);
    }
  } catch (err) {
    console.error(`[Exec] Error executing ${command}:`, err);
    stats.errors++;
  }
}

// Keyboard Shortcuts 

async function executeKeyboardShortcut(params) {
  const { shortcut, repeat = 1 } = params;
  
  // Map shortcut string to key codes
  const keys = shortcut.toLowerCase().split('+').map(k => k.trim());
  const modifiers = {
    ctrl: keys.includes('ctrl'),
    alt: keys.includes('alt'),
    shift: keys.includes('shift'),
    meta: keys.includes('cmd') || keys.includes('meta')
  };
  
  const mainKey = keys.find(k => !['ctrl', 'alt', 'shift', 'cmd', 'meta'].includes(k));
  
  // Execute based on shortcut type
  if (shortcut.match(/ctrl\+(shift\+)?tab/i)) {
    // Tab switching
    await switchTab(shortcut.includes('shift') ? -repeat : repeat);
  } else if (shortcut === 'ctrl+w' || shortcut === 'cmd+w') {
    // Close tab
    await closeCurrentTab();
  } else if (shortcut === 'ctrl+t' || shortcut === 'cmd+t') {
    // New tab
    await openNewTab();
  } else if (shortcut === 'ctrl+shift+t' || shortcut === 'cmd+shift+t') {
    // Reopen closed tab
    await reopenClosedTab();
  } else if (shortcut === 'f5' || shortcut === 'ctrl+r' || shortcut === 'cmd+r') {
    // Refresh
    await refreshPage();
  } else {
    // Generic shortcut - send to content script
    await sendToContent({
      type: 'KEYBOARD_SHORTCUT',
      shortcut,
      modifiers,
      key: mainKey,
      repeat
    });
  }
}

//  Tab Management 

async function switchTab(delta) {
  const tabs = await chrome.tabs.query({ currentWindow: true });
  const currentTab = tabs.find(t => t.active);
  if (!currentTab) return;
  
  const currentIndex = tabs.indexOf(currentTab);
  let newIndex = currentIndex + delta;
  
  // Wrap around
  if (newIndex < 0) newIndex = tabs.length - 1;
  if (newIndex >= tabs.length) newIndex = 0;
  
  await chrome.tabs.update(tabs[newIndex].id, { active: true });
}

async function closeCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) await chrome.tabs.remove(tab.id);
}

async function openNewTab() {
  await chrome.tabs.create({});
}

async function reopenClosedTab() {
  const sessions = await chrome.sessions.getRecentlyClosed({ maxResults: 1 });
  if (sessions.length > 0) {
    await chrome.sessions.restore(sessions[0].sessionId);
  }
}

async function refreshPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) await chrome.tabs.reload(tab.id);
}

// Scrolling 

async function executeScroll(params) {
  await sendToContent({ type: 'SCROLL', ...params });
}

async function executeScrollStop() {
  await sendToContent({ type: 'SCROLL_STOP' });
}

// Window Management 

async function minimizeWindow() {
  const window = await chrome.windows.getCurrent();
  await chrome.windows.update(window.id, { state: 'minimized' });
}

async function maximizeWindow() {
  const window = await chrome.windows.getCurrent();
  const newState = window.state === 'maximized' ? 'normal' : 'maximized';
  await chrome.windows.update(window.id, { state: newState });
}

//  Text Selection & Search 

async function searchSelectedText() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return;
  
  // Get selected text from content script
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => window.getSelection().toString()
  });
  
  const text = result?.result?.trim();
  if (text) {
    const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(text)}`;
    await chrome.tabs.create({ url: searchUrl });
  }
}

// URL Navigation 

async function navigateToUrl(params) {
  const { url, new_tab } = params;
  if (new_tab) {
    await chrome.tabs.create({ url });
  } else {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) await chrome.tabs.update(tab.id, { url });
  }
}

//  Content Script Bridge

async function sendToContent(message) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  
  try {
    await chrome.tabs.sendMessage(tab.id, message);
  } catch (err) {
    // Content script not ready - inject it
    console.log('[GestureSelect] Injecting content script');
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content_script.js']
    });
    // Retry
    setTimeout(() => chrome.tabs.sendMessage(tab.id, message).catch(() => {}), 100);
  }
}

// Badge & Status 

function updateBadge() {
  const colors = {
    connected: '#10b981',
    connecting: '#f59e0b',
    disconnected: '#ef4444'
  };
  
  const texts = {
    connected: '●',
    connecting: '…',
    disconnected: '○'
  };
  
  chrome.action.setBadgeBackgroundColor({ color: colors[connectionState] });
  chrome.action.setBadgeText({ text: texts[connectionState] });
}

//  Popup Communication 

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Always return true to keep the message channel open for async responses
  handlePopupMessage(message).then(sendResponse).catch(err => {
    console.error('[GestureSelect] Message handler error:', err);
    sendResponse({ ok: false, error: err.message });
  });
  return true;
});

async function handlePopupMessage(message) {
  switch (message.type) {
    case 'GET_STATUS':
      return { connectionState, stats, lastGesture, wsUrl: WS_URL };

    case 'RECONNECT':
      connect();
      return { ok: true };

    case 'START_RECORDING':
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message));
        return { ok: true };
      }
      return { ok: false, error: 'Not connected to pipeline' };

    case 'CANCEL_RECORDING':
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'CANCEL_RECORDING' }));
      }
      return { ok: true };

    case 'GET_CUSTOM_MAPPINGS': {
      const result = await chrome.storage.local.get(['customMappings']);
      return { mappings: result.customMappings || [] };
    }

    case 'SAVE_CUSTOM_MAPPING': {
      const result = await chrome.storage.local.get(['customMappings']);
      const mappings = result.customMappings || [];
      const idx = mappings.findIndex(m => m.gestureId === message.mapping.gestureId);
      if (idx >= 0) mappings[idx] = message.mapping;
      else mappings.push(message.mapping);
      await chrome.storage.local.set({ customMappings: mappings });
      return { ok: true };
    }

    case 'DELETE_CUSTOM_MAPPING': {
      const result = await chrome.storage.local.get(['customMappings']);
      const mappings = (result.customMappings || []).filter(m => m.gestureId !== message.gestureId);
      await chrome.storage.local.set({ customMappings: mappings });
      return { ok: true };
    }

    default:
      return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

// Initialization 

console.log('[GestureSelect] Service worker started');
connect();

// Check if pipeline is running via HTTP control server
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
  if (alarm.name === 'keepAlive') {
    if (connectionState === 'disconnected') {
      connect();
    }
  }
});

// Keep service worker alive
setInterval(() => {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'PING' }));
  }
}, 20000);

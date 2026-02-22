/**
 * content_script.js
 * 
 * Executes page-level commands (scrolling, cursor, text selection)
 * Injected into every tab
 */

(function() {
  'use strict';
  
  // Prevent double injection
  if (window.__gestureSelectInjected) return;
  window.__gestureSelectInjected = true;
  
  // ─── State ──────────────────────────────────────────────────────────────────
  
  let scrollInterval = null;
  let textSelectionActive = false;
  let selectionStart = null;
  
  // ─── Message Handler ────────────────────────────────────────────────────────
  
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const { type } = message;
    
    try {
      switch (type) {
        case 'SCROLL':
          handleScroll(message);
          break;
        case 'SCROLL_STOP':
          stopScroll();
          break;
        case 'TEXT_SELECT_START':
          startTextSelection(message.params);
          break;
        case 'TEXT_SELECT_DRAG':
          dragTextSelection(message.params);
          break;
        case 'KEYBOARD_SHORTCUT':
          simulateKeyboardShortcut(message);
          break;
      }
      sendResponse({ success: true });
    } catch (err) {
      console.error('[GestureSelect Content] Error:', err);
      sendResponse({ success: false, error: err.message });
    }
    
    return true;
  });
  
  // ─── Scrolling ──────────────────────────────────────────────────────────────
  
  function handleScroll(params) {
    const { direction, amount } = params;
    const delta = direction === 'up' ? -amount : amount;
    
    // Clear any existing scroll
    if (scrollInterval) {
      clearInterval(scrollInterval);
    }
    
    // Smooth continuous scroll
    scrollInterval = setInterval(() => {
      window.scrollBy({
        top: delta,
        left: 0,
        behavior: 'smooth'
      });
    }, 50);
  }
  
  function stopScroll() {
    if (scrollInterval) {
      clearInterval(scrollInterval);
      scrollInterval = null;
    }
  }
  
  // ─── Text Selection ─────────────────────────────────────────────────────────
  
  function startTextSelection(params) {
    textSelectionActive = true;
    selectionStart = params.position;
    
    // Clear any existing selection
    window.getSelection().removeAllRanges();
    
    console.log('[GestureSelect] Text selection started');
  }
  
  function dragTextSelection(params) {
    if (!textSelectionActive) return;
    
    const { units_to_select, selection_type, move_direction } = params;
    
    // Get element at cursor position
    const x = params.current.x * window.innerWidth;
    const y = params.current.y * window.innerHeight;
    const element = document.elementFromPoint(x, y);
    
    if (!element) return;
    
    const selection = window.getSelection();
    
    try {
      if (selection_type === 'lines') {
        // Vertical selection - select lines
        selectLines(element, units_to_select, move_direction);
      } else {
        // Horizontal selection - select characters
        selectChars(element, units_to_select, move_direction);
      }
    } catch (err) {
      console.error('[GestureSelect] Selection error:', err);
    }
  }
  
  function selectLines(element, lines, direction) {
    const selection = window.getSelection();
    
    if (selection.rangeCount === 0) {
      // Start new selection
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.addRange(range);
    }
    
    // Extend selection by lines (approximate)
    const currentRange = selection.getRangeAt(0);
    try {
      if (direction === 'down') {
        selection.modify('extend', 'forward', 'line');
      } else {
        selection.modify('extend', 'backward', 'line');
      }
    } catch (e) {
      // Fallback for browsers that don't support modify
      console.warn('Selection.modify not supported');
    }
  }
  
  function selectChars(element, chars, direction) {
    const selection = window.getSelection();
    
    if (selection.rangeCount === 0) {
      const range = document.createRange();
      range.selectNodeContents(element);
      selection.addRange(range);
    }
    
    // Extend selection by characters
    try {
      for (let i = 0; i < chars; i++) {
        if (direction === 'right') {
          selection.modify('extend', 'forward', 'character');
        } else {
          selection.modify('extend', 'backward', 'character');
        }
      }
    } catch (e) {
      console.warn('Selection.modify not supported');
    }
  }
  
  // ─── Keyboard Shortcuts ─────────────────────────────────────────────────────
  
  function simulateKeyboardShortcut(message) {
    const { shortcut, modifiers, key, repeat = 1 } = message;
    
    // Create synthetic keyboard event
    const event = new KeyboardEvent('keydown', {
      key: key,
      code: key,
      ctrlKey: modifiers.ctrl,
      altKey: modifiers.alt,
      shiftKey: modifiers.shift,
      metaKey: modifiers.meta,
      bubbles: true,
      cancelable: true
    });
    
    // Dispatch to active element
    const target = document.activeElement || document.body;
    for (let i = 0; i < repeat; i++) {
      target.dispatchEvent(event);
    }
  }
  
  // ─── Cleanup ────────────────────────────────────────────────────────────────
  
  window.addEventListener('unload', () => {
    stopScroll();
  });
  
  console.log('[GestureSelect] Content script loaded');
  
})();
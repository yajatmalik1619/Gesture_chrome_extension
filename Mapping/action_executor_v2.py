"""
action_executor.py 
1. Index finger (landmark 8) tracking for text selection
2. Vertical (line-wise) and horizontal (char-wise) text selection
3. Higher sensitivity for vertical selection
4. Modified cursor workflow: PEACE activates, INDEX-ONLY copies, OK pastes
"""

import logging
import platform
from typing import Optional, Dict, Any
from dataclasses import dataclass
import math
import time
import pyautogui
pyautogui.FAILSAFE = False # Prevent accidental aborts if mouse hits corner

from pipeline.config_manager import ConfigManager
from pipeline.gesture_router import ActionEvent

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of executing an action."""
    success: bool
    action_id: str
    command: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "action_id": self.action_id,
            "command": self.command,
            "params": self.params or {},
            "error": self.error
        }
class ActionExecutor:
    """
    Translates ActionEvents into executable browser commands.
    
    Updated to use index finger tracking for text selection.
    """

    def __init__(self, config: ConfigManager):
        self.cfg = config
        self._os_type = self._detect_os()
        self._text_selection_state = {
            "active": False,
            "start_pos": None,
            "current_pos": None,
            "selected_text": "",
            "direction": None  # "horizontal" or "vertical"
        }
        self._last_execution_times: Dict[str, float] = {}
        logger.info(f"ActionExecutor initialized for {self._os_type}")

    def _detect_os(self) -> str:
        """Detect operating system for platform-specific shortcuts."""
        system = platform.system()
        if system == "Darwin":
            return "mac"
        elif system == "Windows":
            return "windows"
        else:
            return "linux"

    def execute(self, event: ActionEvent) -> ExecutionResult:
        """Execute an ActionEvent and return the result."""
        action_def = self.cfg.get_action(event.action_id)
        
        if not action_def:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=f"Action not found: {event.action_id}"
            )
            
        action_type = action_def.get("type", "unknown")

        # ── State Lock: Area Screenshot ──
        # If an area screenshot is currently active, WE MUST ONLY ALLOW "area_screenshot" actions (like drag to crop).
        # Any other gesture should be completely ignored until the screenshot state is stopped.
        if self._text_selection_state.get("active", False):
            if action_type != "area_screenshot":
                # The user stopped the drag gesture. Let go of the mouse to finalize the crop.
                logger.info("Area screenshot state ended by different gesture. Releasing mouse.")
                pyautogui.mouseUp(button='left')
                self._text_selection_state["active"] = False
                
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Area screenshot is active. Other actions are locked."
                )

        # ── Debounce non-repeatable actions ──
        is_repeatable = action_def.get("repeatable", False)
        if not is_repeatable:
            now = time.time()
            last_time = self._last_execution_times.get(event.action_id, 0.0)
            cooldown = 1.5  # 1.5 seconds cooldown for non-repeatable actions
            if now - last_time < cooldown:
                # Silently ignore to prevent spam
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Cooldown active"
                )
            self._last_execution_times[event.action_id] = now

        action_type = action_def.get("type", "unknown")
        
        try:
            if action_type == "extension":
                # Extension handles this natively via WebSocket
                return ExecutionResult(
                    success=True,
                    action_id=event.action_id,
                    command="EXTENSION_CUSTOM",
                    params={}
                )
            elif action_type == "system":
                return self._execute_system(event, action_def)
            elif action_type == "keyboard":
                return self._execute_keyboard(event, action_def)
            elif action_type == "scroll":
                return self._execute_scroll(event, action_def)
            elif action_type == "area_screenshot":
                return self._execute_area_screenshot(event, action_def)
            elif action_type == "url_navigation":
                return self._execute_url_navigation(event, action_def)
            elif action_type == "paste_and_enter":
                return self._execute_paste_and_enter(event, action_def)
            else:
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error=f"Unknown action type: {action_type}"
                )
        except Exception as e:
            logger.error(f"Error executing {event.action_id}: {e}")
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=str(e)
            )

    # System Actions 

    def _execute_system(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Handle system-level actions like minimize/maximize window."""
        command = action_def.get("command")
        
        if command == "minimize_window":
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="MINIMIZE_WINDOW",
                params={}
            )
        elif command == "maximize_window":
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="MAXIMIZE_WINDOW",
                params={}
            )
        else:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=f"Unknown system command: {command}"
            )

    # Keyboard Shortcuts 

    def _execute_keyboard(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Execute keyboard shortcuts with OS-specific handling."""
        
        # Get the appropriate shortcut for the current OS
        if self._os_type == "mac":
            shortcut = action_def.get("shortcut_mac", action_def.get("shortcut"))
        else:
            shortcut = action_def.get("shortcut")
        
        if not shortcut:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error="No shortcut defined"
            )
            
        magnitude = event.magnitude
        
        # Some shortcuts might need to be repeated (e.g., volume up, next tab)
        for _ in range(magnitude):
            keys = shortcut.split('+')
            pyautogui.hotkey(*keys)
            
        params = {
            "shortcut": shortcut,
            "repeat": magnitude
        }
        
        return ExecutionResult(
            success=True,
            action_id=event.action_id,
            command="KEYBOARD_SHORTCUT",
            params=params
        )

    # Paste and Enter Action
    
    def _execute_paste_and_enter(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Paste contents from clipboard and immediately press enter."""
        if self._os_type == "mac":
            pyautogui.hotkey('command', 'v')
        else:
            pyautogui.hotkey('ctrl', 'v')
            
        # Give OS a brief moment to paste before pressing enter
        time.sleep(5)
        pyautogui.press('enter')
        
        return ExecutionResult(
            success=True,
            action_id=event.action_id,
            command="PASTE_AND_ENTER",
            params={}
        )

    #Scroll Actions

    def _execute_scroll(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Handle page scrolling."""
        direction = action_def.get("direction", "down")
        
        # Special case for scroll_stop
        if direction == "stop":
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="SCROLL_STOP",
                params={}
            )
        
        amount = action_def.get("amount", 100)
        scroll_speed = self.cfg.get_setting("scroll_speed", 3)
        
        # Adjust scroll amount by speed setting
        adjusted_amount = amount * scroll_speed
        
        params = {
            "direction": direction,
            "amount": adjusted_amount
        }
        
        return ExecutionResult(
            success=True,
            action_id=event.action_id,
            command="SCROLL",
            params=params
        )

    #  Area Screenshot Workflow 

    def _execute_area_screenshot(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """
        Handle area screenshots using index finger (landmark 8) for cropping.
        
        - start: Triggers Win+Shift+S and moves mouse to starting position.
        - drag: Drags mouse from starting position down to crop rectangular area.
        """
        selection_action = action_def.get("selection_action")
        
        # Get screen size to scale normalized coordinates
        screen_width, screen_height = pyautogui.size()
        
        if selection_action == "start":
            self._text_selection_state["active"] = True
            
            # Trigger Windows Snipping Tool natively
            if self._os_type == "windows":
                pyautogui.hotkey('win', 'shift', 's')
                # Brief delay to allow snipping tool overlay to appear
                time.sleep(0.5)
            elif self._os_type == "mac":
                pyautogui.hotkey('command', 'shift', '4')
                time.sleep(0.3)
            
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]  # Index finger tip (x, y normalized 0-1)
                
                # Convert normalized coords (0-1) to screen pixels. 
                # Note: Assuming camera is horizontally flipped (mirror), adjust x if needed.
                start_x = int(index_tip[0] * screen_width)
                start_y = int(index_tip[1] * screen_height)
                
                # Store the NORMALIZED starting position for delta calculations
                self._text_selection_state["start_pos"] = {"x": index_tip[0], "y": index_tip[1]}
                self._text_selection_state["current_pos"] = {"x": index_tip[0], "y": index_tip[1]}
                
                # Move to start position
                pyautogui.moveTo(start_x, start_y)
                # Press the left mouse button down to start the crop
                pyautogui.mouseDown(button='left')
            
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="AREA_SCREENSHOT_START",
                params=self._text_selection_state.get("start_pos")
            )
        
        elif selection_action == "drag":
            if not self._text_selection_state.get("active", False):
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Area screenshot not active"
                )
            
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]  # Index finger tip
                
                last_pos = self._text_selection_state["current_pos"]
                
                # Calculate normalized delta movement
                dx_norm = index_tip[0] - last_pos["x"]
                dy_norm = index_tip[1] - last_pos["y"]
                
                # Scale delta to screen pixels (using a sensitivity multiplier)
                sensitivity = 1.2
                dx_pixels = int(dx_norm * screen_width * sensitivity)
                dy_pixels = int(dy_norm * screen_height * sensitivity)
                
                # If we're dragging, move the mouse relatively while the button is down
                if dx_pixels != 0 or dy_pixels != 0:
                    pyautogui.move(dx_pixels, dy_pixels, _pause=False)
                
                # Update current position for next frame delta
                self._text_selection_state["current_pos"] = {"x": index_tip[0], "y": index_tip[1]}
                
                return ExecutionResult(
                    success=True,
                    action_id=event.action_id,
                    command="AREA_SCREENSHOT_DRAG",
                    params={"current": self._text_selection_state["current_pos"]}
                )
            
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error="No landmark data available"
            )
            
        elif selection_action == "stop" or event.action_id == "area_screenshot_stop":
             # This lets go of the mouse click, finalizing the crop
             if self._text_selection_state.get("active", False):
                 pyautogui.mouseUp(button='left')
                 self._text_selection_state["active"] = False
             
             return ExecutionResult(
                 success=True,
                 action_id=event.action_id,
                 command="AREA_SCREENSHOT_STOP"
             )
        else:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=f"Unknown screenshot action: {selection_action}"
            )

    # URL Navigation 

    def _execute_url_navigation(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Navigate to a custom URL (for frequently accessed websites)."""
        url = action_def.get("url")
        
        if not url:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error="No URL specified"
            )
        
        # Ensure URL has protocol
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        params = {
            "url": url,
            "new_tab": True  # Open in new tab by default
        }
        
        return ExecutionResult(
            success=True,
            action_id=event.action_id,
            command="NAVIGATE_URL",
            params=params
        )

    # Custom Gesture Utilities

    def create_custom_url_action(
        self, 
        gesture_id: str, 
        url: str, 
        label: str
    ) -> bool:
        """Create a custom action that navigates to a specific URL."""
        action_id = f"custom_url_{gesture_id}"
        
        action_data = {
            "label": label,
            "type": "url_navigation",
            "repeatable": False,
            "url": url
        }
        
        self.cfg.set("actions", action_id, action_data, persist=True)
        self.cfg.set_binding(gesture_id, action_id)
        
        logger.info(f"Created custom URL action: {gesture_id} â†’ {url}")
        return True

    def create_custom_shortcut_action(
        self,
        gesture_id: str,
        shortcut: str,
        label: str,
        shortcut_mac: Optional[str] = None
    ) -> bool:
        """Create a custom action that executes a keyboard shortcut."""
        action_id = f"custom_shortcut_{gesture_id}"
        
        action_data = {
            "label": label,
            "type": "keyboard",
            "repeatable": False,
            "shortcut": shortcut
        }
        
        if shortcut_mac:
            action_data["shortcut_mac"] = shortcut_mac
        
        self.cfg.set("actions", action_id, action_data, persist=True)
        self.cfg.set_binding(gesture_id, action_id)
        
        logger.info(f"Created custom shortcut action: {gesture_id} â†’ {shortcut}")
        return True

    def bind_gesture_to_library_shortcut(
        self,
        gesture_id: str,
        shortcut_name: str
    ) -> bool:
        """Bind a gesture to a shortcut from the keyboard shortcuts library."""
        library = self.cfg.get("keyboard_shortcuts_library", default={})
        
        if shortcut_name not in library:
            logger.error(f"Shortcut '{shortcut_name}' not found in library")
            return False
        
        shortcut_def = library[shortcut_name]
        
        return self.create_custom_shortcut_action(
            gesture_id=gesture_id,
            shortcut=shortcut_def.get("shortcut"),
            label=shortcut_def.get("label"),
            shortcut_mac=shortcut_def.get("shortcut_mac")
        )

    def change_gesture_type_for_action(
        self,
        old_gesture_id: str,
        new_gesture_id: str,
        action_id: str
    ) -> bool:
        """Change which gesture is bound to an action."""
        self.cfg.set_binding(old_gesture_id, "none")
        self.cfg.set_binding(new_gesture_id, action_id)
        
        logger.info(f"Rebound action '{action_id}': {old_gesture_id} â†’ {new_gesture_id}")
        return True

    # State Management

    def reset_text_selection_state(self):
        """Reset text selection state."""
        self._text_selection_state = {
            "active": False,
            "start_pos": None,
            "current_pos": None,
            "selected_text": "",
            "direction": None
        }

    def get_state(self) -> dict:
        """Get current action executor state."""
        return {
            "text_selection": self._text_selection_state,
            "os_type": self._os_type
        }
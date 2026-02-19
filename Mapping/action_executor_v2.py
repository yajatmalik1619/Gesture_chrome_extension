"""
action_executor.py (UPDATED)
──────────────────
Updated version with:
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
        self._cursor_state = {
            "active": False,
            "position": {"x": 0, "y": 0},
            "last_landmarks": None
        }
        
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

    # ── Main Execution ────────────────────────────────────────────────────

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
        
        try:
            if action_type == "system":
                return self._execute_system(event, action_def)
            elif action_type == "keyboard":
                return self._execute_keyboard(event, action_def)
            elif action_type == "scroll":
                return self._execute_scroll(event, action_def)
            elif action_type == "cursor":
                return self._execute_cursor(event, action_def)
            elif action_type == "text_selection":
                return self._execute_text_selection(event, action_def)
            elif action_type == "url_navigation":
                return self._execute_url_navigation(event, action_def)
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

    # ── System Actions ────────────────────────────────────────────────────

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

    # ── Keyboard Shortcuts ────────────────────────────────────────────────

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
                error="No shortcut defined for this action"
            )
        
        # Handle finger count modifier for tab switching
        magnitude = event.magnitude if event.magnitude > 1 else 1
        
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

    # ── Scroll Actions ────────────────────────────────────────────────────

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

    # ── Cursor Control ────────────────────────────────────────────────────

    def _execute_cursor(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """Handle web cursor (ghost cursor) control."""
        cursor_action = action_def.get("cursor_action")
        
        if cursor_action == "activate":
            self._cursor_state["active"] = True
            
            # Initialize cursor position from index finger tip (landmark 8)
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]  # Index finger tip
                self._cursor_state["position"] = {
                    "x": index_tip[0],
                    "y": index_tip[1]
                }
            
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="CURSOR_ACTIVATE",
                params=self._cursor_state["position"]
            )
        
        elif cursor_action == "move":
            if not self._cursor_state["active"]:
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Cursor not active"
                )
            
            # Update cursor position based on index finger movement
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]
                
                cursor_config = self.cfg.cursor_config
                smoothing = cursor_config.get("smoothing", 0.7)
                speed = cursor_config.get("speed_multiplier", 1.5)
                
                # Smooth cursor movement
                new_x = index_tip[0] * speed
                new_y = index_tip[1] * speed
                
                self._cursor_state["position"]["x"] = (
                    smoothing * self._cursor_state["position"]["x"] + 
                    (1 - smoothing) * new_x
                )
                self._cursor_state["position"]["y"] = (
                    smoothing * self._cursor_state["position"]["y"] + 
                    (1 - smoothing) * new_y
                )
            
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="CURSOR_MOVE",
                params=self._cursor_state["position"]
            )
        
        elif cursor_action == "click":
            if not self._cursor_state["active"]:
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Cursor not active"
                )
            
            # Check if pinch gesture is detected
            pinch_distance = event.meta.get("pinch_distance", 1.0)
            pinch_threshold = self.cfg.cursor_config.get("pinch_threshold", 0.05)
            
            if pinch_distance < pinch_threshold:
                return ExecutionResult(
                    success=True,
                    action_id=event.action_id,
                    command="CURSOR_CLICK",
                    params=self._cursor_state["position"]
                )
            
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error="Pinch not detected"
            )
        
        else:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=f"Unknown cursor action: {cursor_action}"
            )

    # ── Text Selection Workflow ───────────────────────────────────────────

    def _execute_text_selection(self, event: ActionEvent, action_def: dict) -> ExecutionResult:
        """
        UPDATED: Handle text selection using index finger (landmark 8).
        
        - Horizontal movement = character-wise selection
        - Vertical movement = line-wise selection (higher sensitivity)
        """
        selection_action = action_def.get("selection_action")
        
        if selection_action == "start":
            # Initialize text selection state using index finger tip
            self._text_selection_state["active"] = True
            
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]  # Index finger tip
                
                self._text_selection_state["start_pos"] = {
                    "x": index_tip[0], 
                    "y": index_tip[1]
                }
                self._text_selection_state["current_pos"] = {
                    "x": index_tip[0], 
                    "y": index_tip[1]
                }
            
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="TEXT_SELECT_START",
                params=self._text_selection_state["start_pos"]
            )
        
        elif selection_action == "drag":
            if not self._text_selection_state["active"]:
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Text selection not active"
                )
            
            if "landmarks" in event.meta:
                landmarks = event.meta["landmarks"]
                index_tip = landmarks[8]  # Index finger tip
                
                start = self._text_selection_state["start_pos"]
                
                # Calculate horizontal and vertical distances
                dx = index_tip[0] - start["x"]
                dy = index_tip[1] - start["y"]
                
                # Determine if movement is primarily horizontal or vertical
                abs_dx = abs(dx)
                abs_dy = abs(dy)
                
                # Get sensitivities from config
                char_sensitivity = action_def.get("char_sensitivity", 50)
                line_sensitivity = action_def.get("line_sensitivity", 15)  # Lower = more sensitive
                
                if abs_dx > abs_dy:
                    # Horizontal movement - character-wise selection
                    direction = "horizontal"
                    distance = abs_dx
                    units_to_select = int(distance * 1000 / char_sensitivity)
                    selection_type = "chars"
                    move_direction = "right" if dx > 0 else "left"
                else:
                    # Vertical movement - line-wise selection
                    direction = "vertical"
                    distance = abs_dy
                    units_to_select = int(distance * 1000 / line_sensitivity)
                    selection_type = "lines"
                    move_direction = "down" if dy > 0 else "up"
                
                self._text_selection_state["current_pos"] = {
                    "x": index_tip[0], 
                    "y": index_tip[1]
                }
                self._text_selection_state["direction"] = direction
                
                params = {
                    "start": self._text_selection_state["start_pos"],
                    "current": self._text_selection_state["current_pos"],
                    "distance": float(distance),
                    "units_to_select": units_to_select,
                    "selection_type": selection_type,
                    "direction": direction,
                    "move_direction": move_direction
                }
                
                logger.info(
                    f"Text selection: {direction} movement, "
                    f"selecting {units_to_select} {selection_type}"
                )
                
                return ExecutionResult(
                    success=True,
                    action_id=event.action_id,
                    command="TEXT_SELECT_DRAG",
                    params=params
                )
            
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error="No landmark data available"
            )
        
        elif selection_action == "search":
            if not self._text_selection_state["active"]:
                return ExecutionResult(
                    success=False,
                    action_id=event.action_id,
                    error="Text selection not active"
                )
            
            # Reset selection state
            self._text_selection_state["active"] = False
            
            return ExecutionResult(
                success=True,
                action_id=event.action_id,
                command="TEXT_SEARCH_GOOGLE",
                params={}
            )
        
        else:
            return ExecutionResult(
                success=False,
                action_id=event.action_id,
                error=f"Unknown selection action: {selection_action}"
            )

    # ── URL Navigation ────────────────────────────────────────────────────

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

    # ── Custom Gesture Utilities ──────────────────────────────────────────

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
        
        logger.info(f"Created custom URL action: {gesture_id} → {url}")
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
        
        logger.info(f"Created custom shortcut action: {gesture_id} → {shortcut}")
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
        
        logger.info(f"Rebound action '{action_id}': {old_gesture_id} → {new_gesture_id}")
        return True

    # ── State Management ──────────────────────────────────────────────────

    def reset_cursor_state(self):
        """Reset cursor state (useful when hand is lost)."""
        self._cursor_state = {
            "active": False,
            "position": {"x": 0, "y": 0},
            "last_landmarks": None
        }

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
        """Get current state of cursor and text selection."""
        return {
            "cursor": self._cursor_state,
            "text_selection": self._text_selection_state,
            "os_type": self._os_type
        }

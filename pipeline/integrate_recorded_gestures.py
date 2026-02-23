#!/usr/bin/env python3
"""
integrate_recorded_gestures.py
───────────────────────────────
Integrates gesture_landmark_recorder gestures into the existing pipeline.

This script:
1. Loads recorded gestures from gesture_dataset.json
2. Updates gestures_config.json with new custom gestures
3. Creates gesture entries compatible with the existing pipeline

Usage:
    python integrate_recorded_gestures.py
"""

import json
from pathlib import Path
from datetime import datetime

class GestureIntegrator:
    def __init__(
        self,
        dataset_path="gesture_dataset.json",
        config_path="gestures_config_v2.json"
    ):
        self.dataset_path = Path(dataset_path)
        self.config_path = Path(config_path)
        self.dataset = {}
        self.config = {}
        
        self._load_files()
    
    def _load_files(self):
        """Load both dataset and config files."""
        # Load recorded gestures
        if self.dataset_path.exists():
            with open(self.dataset_path, 'r') as f:
                self.dataset = json.load(f)
            print(f"✓ Loaded {len(self.dataset.get('gestures', []))} recorded gestures")
        else:
            print(f"⚠ No recorded gestures found at {self.dataset_path}")
            self.dataset = {"gestures": []}
        
        # Load pipeline config
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
            print(f"✓ Loaded config from {self.config_path}")
        else:
            print(f"❌ Config not found: {self.config_path}")
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
    
    def integrate(self):
        """Integrate recorded gestures into config."""
        if not self.dataset.get("gestures"):
            print("⚠ No gestures to integrate")
            return
        
        # Get or create custom_gestures section
        if "custom_gestures" not in self.config:
            self.config["custom_gestures"] = {"_metadata": {"next_id": 1}}
        
        custom_gestures = self.config["custom_gestures"]
        gestures_section = self.config.get("gestures", {})
        bindings_section = self.config.get("bindings", {})
        
        added_count = 0
        updated_count = 0
        
        for recorded in self.dataset["gestures"]:
            gesture_name = recorded["name"]
            gesture_type = recorded["type"]
            gesture_id = f"recorded_{gesture_name.lower()}"
            
            # Check if already exists
            if gesture_id in custom_gestures:
                print(f"↻ Updating existing: {gesture_id}")
                updated_count += 1
            else:
                print(f"+ Adding new: {gesture_id}")
                added_count += 1
            
            # Build gesture entry based on type
            gesture_entry = self._build_gesture_entry(recorded, gesture_id)
            
            # Add to custom_gestures
            custom_gestures[gesture_id] = gesture_entry
            
            # Add to gestures section if not exists
            if gesture_id not in gestures_section:
                gestures_section[gesture_id] = {
                    "label": gesture_name.replace("_", " ").title(),
                    "type": "custom_" + gesture_type,
                    "hand": recorded.get("hand", "any"),
                    "enabled": True,
                    "description": f"Recorded {gesture_type} gesture: {gesture_name}"
                }
            
            # Add placeholder binding if not exists
            if gesture_id not in bindings_section:
                bindings_section[gesture_id] = "none"
        
        # Update config
        self.config["custom_gestures"] = custom_gestures
        self.config["gestures"] = gestures_section
        self.config["bindings"] = bindings_section
        
        # Save
        self._save_config()
        
        print(f"\n✓ Integration complete:")
        print(f"   Added: {added_count} new gestures")
        print(f"   Updated: {updated_count} existing gestures")
        print(f"   Total custom gestures: {len(custom_gestures) - 1}")  # -1 for _metadata
    
    def _build_gesture_entry(self, recorded, gesture_id):
        """Build custom gesture entry from recorded data."""
        entry = {
            "label": recorded["name"].replace("_", " ").title(),
            "type": recorded["type"],
            "hand": recorded.get("hand", "single"),
            "created_at": recorded.get("recorded_at", datetime.now().isoformat()),
            "enabled": True,
            "deletable": True,
            "dtw_threshold": 0.15,
            "samples": []
        }
        
        # Add recording metadata
        entry["recording"] = {
            "duration_seconds": recorded.get("duration_seconds", 0),
            "num_frames": recorded.get("num_frames", 0),
        }
        
        # Format samples based on type
        if recorded["type"] == "static":
            # Single landmark frame
            sample = {
                "recorded_at": recorded.get("recorded_at"),
                "landmarks": recorded["landmarks"]
            }
            entry["samples"].append(sample)
        
        elif recorded["type"] == "dynamic":
            # Sequence of frames
            sample = {
                "recorded_at": recorded.get("recorded_at"),
                "landmarks": recorded.get("landmarks_sequence", [])
            }
            entry["samples"].append(sample)
            
            # Add motion stats if available
            if "motion_stats" in recorded:
                entry["motion_stats"] = recorded["motion_stats"]
        
        elif recorded["type"] == "combo":
            # Two-hand landmark frame
            sample = {
                "recorded_at": recorded.get("recorded_at"),
                "landmarks": recorded["landmarks"]
            }
            entry["samples"].append(sample)
            entry["hand"] = "both"
        
        return entry
    
    def _save_config(self):
        """Save updated config."""
        # Backup original
        backup_path = self.config_path.with_suffix('.json.backup')
        if self.config_path.exists():
            import shutil
            shutil.copy(self.config_path, backup_path)
            print(f"📋 Backup created: {backup_path}")
        
        # Save updated config
        with open(self.config_path, 'w') as f:
            json.dump(self.config, indent=2, fp=f)
        print(f"💾 Config saved: {self.config_path}")
    
    def list_integrated(self):
        """List all integrated custom gestures."""
        custom = self.config.get("custom_gestures", {})
        
        print("\n" + "="*70)
        print("INTEGRATED CUSTOM GESTURES")
        print("="*70)
        
        static_count = 0
        dynamic_count = 0
        combo_count = 0
        
        for gid, gesture in custom.items():
            if gid.startswith("_"):
                continue
            
            gtype = gesture.get("type", "unknown")
            label = gesture.get("label", gid)
            enabled = gesture.get("enabled", False)
            samples = len(gesture.get("samples", []))
            
            status = "✓" if enabled else "✗"
            print(f"\n{status} {gid}")
            print(f"   Label: {label}")
            print(f"   Type: {gtype}")
            print(f"   Samples: {samples}")
            
            if gtype == "static":
                static_count += 1
            elif gtype == "dynamic":
                dynamic_count += 1
                if "motion_stats" in gesture:
                    stats = gesture["motion_stats"]
                    print(f"   Motion: {stats.get('direction')} ({stats.get('displacement', 0):.3f})")
            elif gtype == "combo":
                combo_count += 1
        
        print("\n" + "="*70)
        print(f"Total: {static_count} static, {dynamic_count} dynamic, {combo_count} combo")
        print("="*70 + "\n")


def main():
    print("\n" + "="*70)
    print("GESTURE INTEGRATION TOOL")
    print("="*70 + "\n")
    
    integrator = GestureIntegrator()
    integrator.integrate()
    integrator.list_integrated()
    
    print("\n💡 Next steps:")
    print("   1. The pipeline will now recognize your recorded gestures")
    print("   2. Use the extension UI to bind gestures to actions")
    print("   3. Recorded gestures use DTW matching automatically")
    print("\n✓ Integration complete!\n")


if __name__ == "__main__":
    main()

# 🖐️ GestureSelect — Control Chrome With Your Hand

> A Chrome Extension that lets you navigate your browser using hand gestures — no clicks, no keyboard. Just your hand and a webcam.

![MediaPipe](https://img.shields.io/badge/MediaPipe-Hands-blue) ![JavaScript](https://img.shields.io/badge/JavaScript-ES6-yellow) ![Chrome Extension](https://img.shields.io/badge/Chrome-Extension-green)

---

## 📌 What It Does

GestureSelect maps hand gestures detected through your webcam to browser actions — opening links, switching tabs, or triggering any custom action you define. Everything is configurable and stored locally via JSON.

---

## ✨ Features

- 🔗 **Map gestures to links** — Point, pinch, or wave to open any URL
- ✏️ **Customize gesture actions** — Reassign what any gesture does at any time
- ➕ **Add new gesture-action pairs** — Extend the gesture library to suit your workflow
- 🗑️ **Delete gesture mappings** — Remove gestures you no longer need
- 💾 **Persistent configuration** — All mappings saved locally in JSON; survive browser restarts

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| Gesture Detection | [MediaPipe Hands](https://developers.google.com/mediapipe/solutions/vision/hand_landmarker) |
| Extension Logic | JavaScript (ES6), Chrome Extension APIs |
| Configuration Storage | JSON (local) |
| UI | HTML, CSS |

---

## 🚀 Installation

> No npm, no build step. Load directly into Chrome.

1. **Clone the repository**
   ```bash
   git clone https://github.com/yajatmalik1619/Gesture_chrome_extension.git
   ```

2. **Open Chrome Extensions page**
   ```
   chrome://extensions/
   ```

3. **Enable Developer Mode** (toggle in top-right)

4. **Click "Load Unpacked"** and select the cloned folder

5. **Pin the extension** from the Chrome toolbar

6. **Allow camera access** when prompted

---

## 🎮 How to Use

1. Click the GestureSelect icon in your Chrome toolbar
2. The extension opens your webcam feed and starts detecting gestures
3. Perform a registered gesture → the mapped action triggers automatically
4. Open **Settings** to add, edit, or delete gesture mappings

---

## ⚙️ Configuration

Gesture-to-action mappings are stored in a local JSON file. Example structure:

```json
{
  "gestures": [
    {
      "id": "thumbs_up",
      "action": "open_url",
      "value": "https://github.com"
    },
    {
      "id": "peace_sign",
      "action": "open_url",
      "value": "https://youtube.com"
    }
  ]
}
```

You can edit this directly or use the in-extension UI to manage mappings.

---

## 📁 Project Structure

```
Gesture_chrome_extension/
│
├── manifest.json          # Chrome extension manifest (v3)
├── background.js          # Service worker for extension lifecycle
├── content.js             # Injected script for gesture detection
├── popup.html             # Extension popup UI
├── popup.js               # Popup logic
├── gestures.json          # Default gesture-action mappings
└── libs/
    └── mediapipe/         # MediaPipe Hands library
```

---

## 🔮 Roadmap

- [ ] Support for multi-gesture sequences (combos)
- [ ] Tab switching and scrolling via gestures
- [ ] Visual gesture feedback overlay
- [ ] Export/import gesture configs
- [ ] Support for left-hand vs right-hand disambiguation

---

## 📄 License

MIT License — feel free to fork, build, and extend.

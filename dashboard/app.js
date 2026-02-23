import { GestureRecorder } from './gesture_recorder.js';

class DashboardApp {
    constructor() {
        this.socket = null;
        this.recorder = null;
        this.currentActiveWebcam = 'shortcuts';

        this.init();
    }

    async init() {
        this.initWebSocket();
        this.initNavigation();
        this.initShortcuts();
        this.initUrls();
        this.initRecorder();
    }

    initWebSocket() {
        this.socket = new WebSocket('ws://localhost:8765');
        this.socket.onopen = () => {
            document.getElementById('statusDot').className = 'w-2 h-2 rounded-full bg-green-500';
            document.getElementById('statusText').innerText = 'Connected';
        };
        this.socket.onclose = () => {
            document.getElementById('statusDot').className = 'w-2 h-2 rounded-full bg-red-500';
            document.getElementById('statusText').innerText = 'Disconnected';
        };
    }

    initNavigation() {
        const navLinks = document.querySelectorAll('nav a');
        navLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                navLinks.forEach(l => l.classList.remove('bg-indigo-500/10', 'text-indigo-400', 'border-indigo-500/20'));
                navLinks.forEach(l => l.classList.add('text-slate-400', 'border-transparent'));

                link.classList.add('bg-indigo-500/10', 'text-indigo-400', 'border-indigo-500/20');
                link.classList.remove('text-slate-400', 'border-transparent');

                const sectionId = link.getAttribute('href').substring(1);
                this.switchSection(sectionId);
            });
        });
    }

    switchSection(id) {
        if (id === 'section-shortcuts') {
            this.currentActiveWebcam = 'shortcuts';
            this.recorder.setTargetElements('webcam-shortcuts', 'canvas-shortcuts');
        } else if (id === 'section-urls') {
            this.currentActiveWebcam = 'urls';
            this.recorder.setTargetElements('webcam-urls', 'canvas-urls');
        }
    }

    async initRecorder() {
        const { GestureRecorder } = await import('./gesture_recorder.js');
        this.recorder = new GestureRecorder();
        await this.recorder.initialize('webcam-shortcuts', 'canvas-shortcuts');
    }

    initShortcuts() {
        const recordBtn = document.getElementById('recordShortcutBtn');
        recordBtn.addEventListener('click', () => this.startRecording('shortcut'));
    }

    initUrls() {
        const recordBtn = document.getElementById('recordUrlBtn');
        recordBtn.addEventListener('click', () => this.startRecording('url'));
    }

    async startRecording(type) {
        if (!this.recorder || !this.recorder.webcamRunning) {
            this.showToast('Webcam not ready', 'error');
            return;
        }

        const btn = type === 'shortcut' ? document.getElementById('recordShortcutBtn') : document.getElementById('recordUrlBtn');
        const overlay = document.getElementById('countdown-overlay');
        const countText = document.getElementById('countdown-text');

        // Countdown
        overlay.style.opacity = '1';
        for (let i = 3; i > 0; i--) {
            countText.innerText = i;
            await new Promise(r => setTimeout(r, 800));
        }
        overlay.style.opacity = '0';

        // Capturing
        btn.innerText = 'Capturing...';
        btn.classList.add('animate-pulse', 'bg-red-600');
        this.recorder.startRecording();

        await new Promise(r => setTimeout(r, 2000));

        const samples = this.recorder.stopRecording();
        btn.innerText = 'Record Gesture';
        btn.classList.remove('animate-pulse', 'bg-red-600');

        if (samples.length < 5) {
            this.showToast('Recording failed: Too few frames captured', 'error');
            return;
        }

        this.saveGesture(type, samples);
    }

    saveGesture(type, samples) {
        let actionId, gestureId, label;

        if (type === 'shortcut') {
            actionId = document.getElementById('shortcutSelect').value;
            gestureId = document.getElementById('shortcutSlot').value;
            label = `Custom Shortcut: ${actionId}`;
        } else {
            const name = document.getElementById('urlName').value || 'Custom URL';
            const url = document.getElementById('urlTarget').value;
            if (!url) {
                this.showToast('Please enter a URL', 'error');
                return;
            }
            gestureId = `custom_url_${Date.now()}`;
            actionId = `open_url_${Date.now()}`;
            label = name;

            // In a real implementation, we'd define the action in config too.
            // For now, let's assume the backend handles creating the action if missing.
        }

        const gestureData = {
            label: label,
            type: "static", // Defaulting to static for simplicity in DTW matching
            enabled: true,
            samples: samples.map(s => ({ landmarks: s }))
        };

        const payload = {
            type: "SAVE_GESTURE",
            gesture_id: gestureId,
            gesture_data: gestureData,
            action_id: actionId
        };

        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(json.dumps(payload));
            this.showToast('Gesture saved successfully!');
            if (type === 'url') this.addUrlCard(label, document.getElementById('urlTarget').value);
        } else {
            this.showToast('Not connected to backend', 'error');
        }
    }

    addUrlCard(name, url) {
        const list = document.getElementById('customMappingsList');
        const card = document.createElement('div');
        card.className = 'p-4 rounded-2xl bg-slate-800/40 border border-slate-700/50 flex flex-col gap-2';
        card.innerHTML = `
            <div class="flex items-center justify-between">
                <p class="text-[10px] uppercase text-slate-500 font-bold">Custom URL</p>
                <div class="w-2 h-2 rounded-full bg-indigo-500"></div>
            </div>
            <h4 class="text-white font-bold">${name}</h4>
            <p class="text-xs text-slate-400 truncate">${url}</p>
        `;
        list.appendChild(card);
    }

    showToast(message, type = 'success') {
        const toast = document.getElementById('toast');
        const toastMsg = document.getElementById('toastMessage');
        toastMsg.innerText = message;
        toast.querySelector('.bg-indigo-600').classList.toggle('bg-red-600', type === 'error');

        toast.classList.remove('translate-y-20', 'opacity-0');
        setTimeout(() => {
            toast.classList.add('translate-y-20', 'opacity-0');
        }, 3000);
    }
}

// Global helper for JSON (since app.js might not have access to a library if not bundled)
const json = { dumps: JSON.stringify, loads: JSON.parse };

window.addEventListener('DOMContentLoaded', () => {
    new DashboardApp();
});

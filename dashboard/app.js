import { GestureRecorder } from './gesture_recorder.js';

class DashboardApp {
    constructor() {
        this.gestures = [];
        this.activeActionType = 'url';
        this.recorder = null;

        this.initElements();
        this.initEventListeners();
        this.loadGestures();
        this.initRecorder();
    }

    initElements() {
        this.gestureList = document.getElementById('gestureList');
        this.addGestureBtn = document.getElementById('addGestureBtn');
        this.configOverlay = document.getElementById('configOverlay');
        this.closeConfigBtn = document.getElementById('closeConfigBtn');
        this.gestureForm = document.getElementById('gestureForm');
        this.actionTypeBtns = document.querySelectorAll('.action-type-btn');
        this.urlGroup = document.getElementById('urlInputGroup');
        this.shortcutGroup = document.getElementById('shortcutInputGroup');
        this.shortcutInput = document.getElementById('shortcutInput');
        this.recordBtn = document.getElementById('recordBtn');
    }

    initEventListeners() {
        this.addGestureBtn.addEventListener('click', () => this.toggleConfig(true));
        this.closeConfigBtn.addEventListener('click', () => this.toggleConfig(false));

        this.actionTypeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                this.setActiveActionType(btn.dataset.type);
            });
        });

        this.gestureForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleFormSubmit();
        });

        this.recordBtn.addEventListener('click', () => {
            this.startRecording();
        });

        // Shortcut recording logic
        this.shortcutInput.addEventListener('keydown', (e) => {
            e.preventDefault();
            const keys = [];
            if (e.ctrlKey) keys.push('ctrl');
            if (e.shiftKey) keys.push('shift');
            if (e.altKey) keys.push('alt');
            if (e.metaKey) keys.push('cmd');

            const key = e.key.toLowerCase();
            if (!['control', 'shift', 'alt', 'meta'].includes(key)) {
                keys.push(key);
            }

            this.shortcutInput.value = keys.join('+');
        });
    }

    async initRecorder() {
        this.recorder = new GestureRecorder();
        await this.recorder.initialize();
    }

    toggleConfig(show) {
        if (show) {
            this.configOverlay.classList.add('show');
        } else {
            this.configOverlay.classList.remove('show');
        }
    }

    setActiveActionType(type) {
        this.activeActionType = type;
        this.actionTypeBtns.forEach(btn => {
            if (btn.dataset.type === type) {
                btn.classList.add('active', 'border-indigo-500', 'bg-indigo-500/10', 'text-white');
                btn.classList.remove('border-slate-700', 'bg-slate-800/50', 'text-slate-400');
            } else {
                btn.classList.remove('active', 'border-indigo-500', 'bg-indigo-500/10', 'text-white');
                btn.classList.add('border-slate-700', 'bg-slate-800/50', 'text-slate-400');
            }
        });

        if (type === 'url') {
            this.urlGroup.classList.remove('hidden');
            this.shortcutGroup.classList.add('hidden');
        } else {
            this.urlGroup.classList.add('hidden');
            this.shortcutGroup.classList.remove('hidden');
        }
    }

    handleFormSubmit() {
        const name = document.getElementById('gestureName').value;
        const target = this.activeActionType === 'url' ?
            document.getElementById('targetUrl').value :
            this.shortcutInput.value;

        if (!name || !target) {
            alert('Please fill in all fields');
            return;
        }

        const newGesture = {
            id: Date.now(),
            name,
            type: this.activeActionType,
            target,
            enabled: true
        };

        this.gestures.push(newGesture);
        this.renderGestures();
        this.toggleConfig(false);
        this.gestureForm.reset();

        // Auto-scroll to preview and highlight record button
        document.getElementById('mainTitle').innerText = `Recording: ${name}`;
        this.recordBtn.classList.add('ring-4', 'ring-indigo-500/50', 'scale-110');
    }

    renderGestures() {
        this.gestureList.innerHTML = this.gestures.map(g => `
            <div class="gesture-card p-4 rounded-xl flex items-center justify-between group">
                <div class="flex items-center gap-3">
                    <div class="w-2 h-2 rounded-full ${g.enabled ? 'bg-indigo-500' : 'bg-slate-600'}"></div>
                    <div>
                        <h4 class="text-sm font-semibold text-white">${g.name}</h4>
                        <p class="text-[10px] text-slate-500 uppercase tracking-tight">${g.type}: ${g.target}</p>
                    </div>
                </div>
                <div class="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button class="p-1.5 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                    </button>
                </div>
            </div>
        `).join('');
    }

    loadGestures() {
        // Mock data for initial look
        this.gestures = [
            { id: 1, name: 'Open Google', type: 'url', target: 'https://google.com', enabled: true },
            { id: 2, name: 'New Tab', type: 'shortcut', target: 'ctrl+t', enabled: true }
        ];
        this.renderGestures();
    }

    async startRecording() {
        if (!this.recorder) return;

        this.recorder.startRecording();
        this.recordBtn.innerText = 'Capturing...';
        this.recordBtn.classList.add('bg-indigo-600', 'animate-pulse');
        this.recordBtn.classList.remove('bg-red-600');

        // Record for 2 seconds
        setTimeout(() => {
            const data = this.recorder.stopRecording();
            this.recordBtn.innerText = 'Record Gesture';
            this.recordBtn.classList.remove('bg-indigo-600', 'animate-pulse', 'ring-4', 'scale-110');
            this.recordBtn.classList.add('bg-red-600');

            console.log('Recorded Landamrks:', data);

            // In a real app, we would send this to the backend/extension
            this.showToast('Gesture recorded & saved locally!');
        }, 2000);
    }

    showToast(message) {
        const toast = document.createElement('div');
        toast.className = 'fixed bottom-8 right-8 bg-indigo-600 text-white px-6 py-3 rounded-xl shadow-2xl z-[100] transform transition-all duration-300 translate-y-20';
        toast.innerText = message;
        document.body.appendChild(toast);

        setTimeout(() => toast.classList.remove('translate-y-20'), 100);
        setTimeout(() => {
            toast.classList.add('translate-y-20');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
}

// Initialize App
window.addEventListener('DOMContentLoaded', () => {
    new DashboardApp();
});

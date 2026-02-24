const preview = document.getElementById('preview');
const statusEl = document.getElementById('status');
const allowBtn = document.getElementById('allowBtn');
const countdown = document.getElementById('countdown');

async function requestCamera() {
    allowBtn.disabled = true;
    statusEl.textContent = 'Requesting camera access…';
    statusEl.className = '';

    try {
        const stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 360 }, facingMode: 'user' },
            audio: false
        });

        // Show live preview
        preview.srcObject = stream;
        preview.style.display = 'block';
        allowBtn.style.display = 'none';

        // Success message
        statusEl.textContent = '✓ Camera access granted!';
        statusEl.className = 'success';

        // Count down and close
        let secs = 3;
        countdown.style.display = 'block';
        countdown.textContent = `Closing in ${secs}s…`;

        const tick = setInterval(() => {
            secs--;
            if (secs <= 0) {
                clearInterval(tick);
                stream.getTracks().forEach(t => t.stop());
                chrome.tabs.getCurrent((tab) => {
                    if (tab) chrome.tabs.remove(tab.id);
                    else window.close(); // Fallback
                });
            } else {
                countdown.textContent = `Closing in ${secs}s…`;
            }
        }, 1000);

    } catch (err) {
        allowBtn.disabled = false;
        statusEl.className = 'error';
        statusEl.textContent = err.name === 'NotAllowedError'
            ? '❌ Permission denied — click the 🔒 icon in the address bar to allow.'
            : `❌ ${err.name}: ${err.message}`;
    }
}

allowBtn.addEventListener('click', requestCamera);

// Auto-trigger on load so Chrome shows the prompt immediately
window.addEventListener('load', requestCamera);

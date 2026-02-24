// options.js — camera permission button handler
// Opens camera_permission.html in a new tab to trigger Chrome's permission prompt.
// source: https://stackoverflow.com/a/74132795 (CC BY-SA 4.0) — adapted

document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('requestPermission');
    if (!btn) return;

    btn.addEventListener('click', () => {
        // Open the dedicated permission page in a new tab.
        // That page immediately calls getUserMedia which triggers Chrome's native
        // permission prompt. Since all extension pages share the same origin,
        // granting access there grants it for the popup too.
        chrome.tabs.create({ url: chrome.runtime.getURL('camera_permission.html') });
    });
});

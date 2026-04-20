/**
 * kube-foresight dashboard app utilities.
 */

// HTMX configuration
document.addEventListener('DOMContentLoaded', function() {
    // Add HTMX loading indicator class management
    document.body.addEventListener('htmx:beforeRequest', function(evt) {
        const indicator = evt.detail.elt.getAttribute('hx-indicator');
        if (indicator) {
            const el = document.querySelector(indicator);
            if (el) el.classList.add('htmx-request');
        }
    });

    document.body.addEventListener('htmx:afterRequest', function(evt) {
        const indicator = evt.detail.elt.getAttribute('hx-indicator');
        if (indicator) {
            const el = document.querySelector(indicator);
            if (el) el.classList.remove('htmx-request');
        }
    });
});

// --- Settings panel toggle ---
function toggleSettings() {
    const panel = document.getElementById('settings-panel');
    if (panel) panel.classList.toggle('hidden');
}

// --- Patch row toggle (recommendations page) ---
function togglePatch(rowId) {
    const row = document.getElementById(rowId);
    if (row) row.classList.toggle('hidden');
}

// --- Apply patch with confirmation ---
function confirmApply(name, idx) {
    if (!confirm('Apply patch to "' + name + '"?\n\nThis will modify resource requests/limits on your live cluster.')) {
        return;
    }
    var target = document.getElementById('patch-status-' + idx);
    target.innerHTML = '<span class="text-gray-500 text-sm">Applying...</span>';
    fetch('/partials/patches/' + encodeURIComponent(name) + '/apply', { method: 'POST' })
        .then(function(r) { return r.text(); })
        .then(function(html) { target.innerHTML = html; })
        .catch(function() { target.innerHTML = '<span class="text-red-500 text-sm">Network error</span>'; });
}

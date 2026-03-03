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

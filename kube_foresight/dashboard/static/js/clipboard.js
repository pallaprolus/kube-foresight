/**
 * Clipboard utilities for kube-foresight dashboard.
 */

function copyToClipboard(buttonEl, elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const text = el.textContent || el.innerText;
    navigator.clipboard.writeText(text).then(() => {
        const originalHTML = buttonEl.innerHTML;
        buttonEl.innerHTML = '<svg class="w-4 h-4 mr-1.5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> Copied!';
        buttonEl.classList.add('text-green-600');
        setTimeout(() => {
            buttonEl.innerHTML = originalHTML;
            buttonEl.classList.remove('text-green-600');
        }, 2000);
    }).catch(err => {
        console.error('Copy failed:', err);
    });
}

function copyKubectlCommand(deploymentName) {
    const cmd = `kubectl patch deployment ${deploymentName} -n <namespace> --type strategic -p "$(cat ${deploymentName}-patch.yaml)"`;
    navigator.clipboard.writeText(cmd).then(() => {
        // Brief visual feedback via an alert — in production we'd use a toast
        const btn = event.currentTarget;
        const originalHTML = btn.innerHTML;
        btn.innerHTML = '<svg class="w-4 h-4 mr-1.5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> Copied!';
        btn.classList.add('text-green-600');
        setTimeout(() => {
            btn.innerHTML = originalHTML;
            btn.classList.remove('text-green-600');
        }, 2000);
    }).catch(err => {
        console.error('Copy failed:', err);
    });
}

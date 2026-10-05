// Popup controller for title/URL redaction mode.
// Talks to the service worker via messages; mirrors state from chrome.storage
// so the UI is correct even if the worker was just woken up.
const dot = document.getElementById('dot');
const statusEl = document.getElementById('status');
const input = document.getElementById('activity');
const btn = document.getElementById('toggleBtn');
const errEl = document.getElementById('err');

let current = { on: false, activity: '', since: 0 };

function fmtSince(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `since ${hh}:${mm}`;
}

function render() {
  dot.classList.toggle('on', current.on);
  if (current.on) {
    statusEl.innerHTML = `Redacting <b>ON</b> ${fmtSince(current.since)} — logging as:<br>“${escapeHtml(current.activity)}”`;
    input.value = current.activity;
    btn.textContent = 'Stop redacting';
    btn.className = 'stop';
  } else {
    statusEl.textContent = 'Redacting OFF — normal title + URL tracking.';
    btn.textContent = 'Start redacting';
    btn.className = 'start';
  }
  errEl.textContent = '';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function refresh() {
  try {
    const data = await chrome.storage.local.get(['privacyRedact']);
    if (data.privacyRedact && typeof data.privacyRedact === 'object') {
      current = {
        on: !!data.privacyRedact.on,
        activity: String(data.privacyRedact.activity || ''),
        since: Number(data.privacyRedact.since || 0),
      };
    }
  } catch (e) {}
  render();
}

btn.addEventListener('click', async () => {
  btn.disabled = true;
  try {
    if (!current.on) {
      const activity = input.value.trim();
      if (!activity) {
        errEl.textContent = 'Type what you are doing first.';
        btn.disabled = false;
        return;
      }
      const res = await chrome.runtime.sendMessage({ type: 'privacy-start', activity });
      if (!res || !res.ok) throw new Error((res && res.error) || 'worker unreachable');
      current = res.state;
    } else {
      const res = await chrome.runtime.sendMessage({ type: 'privacy-stop' });
      if (!res || !res.ok) throw new Error((res && res.error) || 'worker unreachable');
      current = res.state;
    }
  } catch (e) {
    errEl.textContent = 'Could not reach tracker worker: ' + e.message;
  }
  btn.disabled = false;
  render();
});

// Editing the text mid-span starts a clean split under the new text.
input.addEventListener('change', async () => {
  if (!current.on) return;
  const activity = input.value.trim();
  if (!activity || activity === current.activity) return;
  try {
    const res = await chrome.runtime.sendMessage({ type: 'privacy-update', activity });
    if (res && res.ok) current = res.state;
  } catch (e) {}
  render();
});

refresh();

// Configuration defaults
const DEFAULT_SETTINGS = {
  collectorUrl: 'http://127.0.0.1:8765',
  minDuration: 2,
  trackInternal: false,
  stripParams: true
};

// State variables
let settings = { ...DEFAULT_SETTINGS };
let currentSession = null;
let eventQueue = [];
let isProcessingQueue = false;
let stateLoaded = false;  // Guard: block event handlers until state is restored

// Debounce timer for title changes
let titleDebounceTimer = null;

// ── HEARTBEAT & CHUNKING ──────────────────────────────────────────────────
// The heartbeat is a rolling timestamp updated every HEARTBEAT_INTERVAL_MS
// while a session is live AND the browser window is actually focused.
// When ending a session, if (now - lastHeartbeat) > STALE_THRESHOLD_MS,
// the session end is CAPPED at lastHeartbeat instead of "now",
// preventing ghost sessions from OS sleep, minimized windows, etc.
const HEARTBEAT_INTERVAL_MS = 15_000;       // 15 seconds fast active check
const STALE_THRESHOLD_MS    = 180_000;      // 3 minutes (allows for alarm jitter/throttling)
const CHUNK_DURATION_S      = 300;          // 5 minutes: long sessions flush chunks incrementally
const MAX_SESSION_DURATION_S = 3600;        // Hard safety cap: 1 hour per raw event
const HEARTBEAT_ALARM_NAME  = 'session-heartbeat';

// Initialization
async function init() {
  await loadSettings();
  await loadState();
  stateLoaded = true;
  
  // Register alarm for periodic heartbeat (survives service worker suspension)
  chrome.alarms.create(HEARTBEAT_ALARM_NAME, { periodInMinutes: 0.5 });

  // Flush any offline queued events immediately
  processQueue();
  
  // Synchronize state immediately upon worker startup
  await checkActiveSession();
}

// Load settings from storage
async function loadSettings() {
  const data = await chrome.storage.local.get(['settings']);
  if (data.settings) {
    settings = { ...DEFAULT_SETTINGS, ...data.settings };
  }
}

// Load session state from storage
async function loadState() {
  const data = await chrome.storage.local.get(['currentSession', 'eventQueue']);
  if (data.currentSession) {
    currentSession = data.currentSession;
  }
  if (data.eventQueue) {
    eventQueue = data.eventQueue;
  }
}

// Save session state to storage
async function saveState() {
  await chrome.storage.local.set({ currentSession, eventQueue });
}

// Listen for settings changes
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.settings) {
    settings = { ...settings, ...changes.settings.newValue };
  }
});

// Determine browser
function getBrowserName() {
  if (navigator.brave) {
    return 'brave';
  }
  return 'chrome'; // Default for manifest v3 in Chromium
}

// Process URL based on settings
function processUrl(rawUrl) {
  if (!rawUrl) return null;
  
  let urlObj;
  try {
    urlObj = new URL(rawUrl);
  } catch (e) {
    return { url: rawUrl, domain: 'unknown' };
  }

  // Handle local file URLs
  if (urlObj.protocol === 'file:') {
    return {
      url: rawUrl,
      domain: 'local-file'
    };
  }

  const isInternal = urlObj.protocol.includes('chrome') || urlObj.protocol.includes('about');
  if (isInternal && !settings.trackInternal) {
    return null; // Skip tracking
  }

  let finalUrl = rawUrl;
  if (settings.stripParams) {
    finalUrl = `${urlObj.origin}${urlObj.pathname}`;
  }

  let domain = urlObj.hostname;
  if (isInternal) {
    domain = 'chrome-internal';
  }

  return { url: finalUrl, domain };
}

// Start a new session
async function startSession(tab, windowId) {
  if (!stateLoaded) return;  // Guard: don't act before state is restored

  // Clear any existing debounce timer
  if (titleDebounceTimer) {
    clearTimeout(titleDebounceTimer);
    titleDebounceTimer = null;
  }

  // End existing session if there is one
  if (currentSession) {
    await endCurrentSession();
  }

  if (!tab || !tab.url) {
    return;
  }

  const processedInfo = processUrl(tab.url);
  if (!processedInfo) return; // Skip internal pages if configured

  const now = Date.now();
  currentSession = {
    id: crypto.randomUUID(),
    start: new Date(now).toISOString(),
    tabId: tab.id,
    windowId: windowId,
    url: processedInfo.url,
    domain: processedInfo.domain,
    title: tab.title || '',
    audible: tab.audible || false,
    audibleIdleStart: null,
    lastHeartbeat: now,       // Heartbeat: tracks last known user activity in this session
  };

  await saveState();
}

// End current session and queue event
// Core improvement: caps session at lastHeartbeat if the gap is too large
async function endCurrentSession(explicitEndTime = null) {
  if (!currentSession) return;

  const now = Date.now();
  const startTime = new Date(currentSession.start).getTime();
  const lastHB = currentSession.lastHeartbeat || startTime;

  // Determine the true session end:
  let effectiveEndMs;
  if (explicitEndTime !== null && explicitEndTime !== undefined) {
    effectiveEndMs = typeof explicitEndTime === 'number' ? explicitEndTime : new Date(explicitEndTime).getTime();
    if (effectiveEndMs < startTime) {
      effectiveEndMs = startTime;
    }
  } else {
    const gapSinceHeartbeat = now - lastHB;
    if (gapSinceHeartbeat > STALE_THRESHOLD_MS) {
      effectiveEndMs = lastHB + Math.round(HEARTBEAT_INTERVAL_MS / 2);
    } else {
      effectiveEndMs = now;
    }
  }

  let durationSeconds = (effectiveEndMs - startTime) / 1000;

  // Hard cap: no single raw event can exceed MAX_SESSION_DURATION_S
  if (durationSeconds > MAX_SESSION_DURATION_S) {
    durationSeconds = MAX_SESSION_DURATION_S;
    effectiveEndMs = startTime + MAX_SESSION_DURATION_S * 1000;
  }

  if (durationSeconds >= settings.minDuration) {
    const event = {
      id: currentSession.id,
      start: currentSession.start,
      end: new Date(effectiveEndMs).toISOString(),
      duration_seconds: Math.round(durationSeconds * 1000) / 1000,
      source: 'browser',
      context: {
        browser: getBrowserName(),
        domain: currentSession.domain,
        title: currentSession.title,
        url: currentSession.url,
        audible: currentSession.audible || false,
        tab_id: currentSession.tabId,
        window_id: currentSession.windowId
      }
    };

    eventQueue.push(event);
    if (eventQueue.length > 1000) {
      eventQueue.shift(); // Keep queue at max 1000
    }
    
    // Attempt to flush queue
    processQueue();
  }

  currentSession = null;
  await saveState();
}

// Check and synchronize tracking session with the currently focused Chrome window
async function checkActiveSession() {
  if (!stateLoaded) return;

  try {
    let win = null;
    try {
      win = await chrome.windows.getLastFocused({ populate: false });
    } catch (e) {
      try {
        const wins = await chrome.windows.getAll({ populate: false });
        win = wins.find(w => w.focused) || null;
      } catch (err) {}
    }

    const isChromeFocused = win && win.focused && win.state !== 'minimized' && win.id !== chrome.windows.WINDOW_ID_NONE;

    if (!isChromeFocused) {
      // Browser is not the focused foreground window
      if (currentSession) {
        await endCurrentSession();
      }
      return;
    }

    // Browser is focused. Query active tab in this window.
    const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
    if (!tabs || tabs.length === 0 || !tabs[0].url) {
      if (currentSession) {
        await endCurrentSession();
      }
      return;
    }

    const activeTab = tabs[0];
    const processed = processUrl(activeTab.url);
    if (!processed) {
      // Internal or excluded page
      if (currentSession) {
        await endCurrentSession();
      }
      return;
    }

    const now = Date.now();

    // Check if continuing current session
    if (currentSession && currentSession.tabId === activeTab.id && currentSession.url === processed.url) {
      const staleness = now - (currentSession.lastHeartbeat || new Date(currentSession.start).getTime());
      if (staleness > STALE_THRESHOLD_MS) {
        // Gap indicates sleep or system suspend: end old session capped at last heartbeat, start fresh
        await endCurrentSession();
        await startSession(activeTab, win.id);
        return;
      }

      // Update in-place properties if changed
      if (activeTab.title && activeTab.title !== currentSession.title) {
        currentSession.title = activeTab.title;
      }
      if (activeTab.audible !== undefined) {
        currentSession.audible = currentSession.audible || activeTab.audible;
      }

      currentSession.lastHeartbeat = now;

      // Flush long sessions incrementally every CHUNK_DURATION_S (300s = 5m)
      const sessionAge = (now - new Date(currentSession.start).getTime()) / 1000;
      if (sessionAge >= CHUNK_DURATION_S) {
        const tab = activeTab;
        const wid = win.id;
        await endCurrentSession(now);
        await startSession(tab, wid);
        return;
      }

      await saveState();
      return;
    }

    // Active tab or URL changed, or no currentSession existed
    if (currentSession) {
      await endCurrentSession();
    }
    await startSession(activeTab, win.id);
  } catch (err) {
    console.error('Error in checkActiveSession:', err);
  }
}

// Send queued events to collector
async function processQueue() {
  if (isProcessingQueue || eventQueue.length === 0) return;
  isProcessingQueue = true;

  const url = `${settings.collectorUrl}/event`;
  
  while (eventQueue.length > 0) {
    const event = eventQueue[0];
    try {
      const headers = {
        'Content-Type': 'application/json'
      };
      if (settings.authToken) {
        headers['Authorization'] = `Bearer ${settings.authToken}`;
      }
      const response = await fetch(url, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(event)
      });

      if (response.ok) {
        eventQueue.shift(); // Remove on success
        await saveState();
      } else {
        break;
      }
    } catch (e) {
      break;
    }
  }

  isProcessingQueue = false;
}

// Retry queue periodically
setInterval(() => {
  processQueue();
}, 30000);

// Fast 15-second heartbeat while service worker is active
setInterval(() => {
  if (stateLoaded) {
    checkActiveSession();
  }
}, HEARTBEAT_INTERVAL_MS);

// ── ALARM-BASED HEARTBEAT ──────────────────────────────────────────────
// chrome.alarms survive service worker suspension (unlike setInterval).
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== HEARTBEAT_ALARM_NAME) return;
  if (!stateLoaded) return;
  await checkActiveSession();
});

// --- Event Listeners ---

// Window focus changed
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (!stateLoaded) return;

  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Browser lost focus entirely
    await endCurrentSession();
  } else {
    // Browser gained focus, sync session
    await checkActiveSession();
  }
});

// Tab activated (switched)
chrome.tabs.onActivated.addListener(async (activeInfo) => {
  if (!stateLoaded) return;
  await checkActiveSession();
});

// Tab highlighted (clicked active tab or switched tab selection)
chrome.tabs.onHighlighted.addListener(async (highlightInfo) => {
  if (!stateLoaded) return;
  await checkActiveSession();
});

// Tab updated (URL navigation or in-place title update)
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!stateLoaded) return;
  if (!tab.active) return; // Only care about active tabs

  if (changeInfo.audible !== undefined && currentSession && currentSession.tabId === tabId) {
    currentSession.audible = currentSession.audible || changeInfo.audible;
    if (changeInfo.audible === false && currentSession.audibleIdleStart) {
      // Stopped playing audio while idle
      if (chrome.idle) {
        chrome.idle.queryState(300, async (idleState) => {
          if (idleState === 'idle') {
            await endCurrentSession(Date.now() - 300_000);
          } else if (idleState === 'locked') {
            await endCurrentSession();
          }
        });
      }
    }
    await saveState();
  }

  if (changeInfo.url || changeInfo.title || changeInfo.status === 'complete') {
    await checkActiveSession();
  }
});

// Tab closed
chrome.tabs.onRemoved.addListener(async (tabId, removeInfo) => {
  if (!stateLoaded) return;
  if (currentSession && currentSession.tabId === tabId) {
    await endCurrentSession();
  }
});

// Window closed
chrome.windows.onRemoved.addListener(async (windowId) => {
  if (!stateLoaded) return;
  if (currentSession && currentSession.windowId === windowId) {
    await endCurrentSession();
  }
});

// Idle detection: stop tracking if zero user activity for 5 minutes (300 seconds),
// unless audio/video is playing on the active tab (capped at 2 hours).
const MAX_AUDIBLE_IDLE_OVERRIDE_MS = 2 * 60 * 60 * 1000; // 2 hours

if (chrome.idle) {
  chrome.idle.setDetectionInterval(300);
  chrome.idle.onStateChanged.addListener(async (newState) => {
    if (!stateLoaded) return;

    if (newState === 'locked') {
      // Screen locked -> immediately end session
      await endCurrentSession();
    } else if (newState === 'idle') {
      // Inactive for 5 minutes -> check if active tab is currently playing audio
      if (currentSession) {
        let isAudible = currentSession.audible || false;
        try {
          const tab = await chrome.tabs.get(currentSession.tabId);
          if (tab && tab.audible) {
            isAudible = true;
            currentSession.audible = true;
          }
        } catch (e) {}

        if (isAudible) {
          const now = Date.now();
          if (!currentSession.audibleIdleStart) {
            currentSession.audibleIdleStart = now;
          }
          if (now - currentSession.audibleIdleStart <= MAX_AUDIBLE_IDLE_OVERRIDE_MS) {
            // Keep heartbeat alive within cap
            currentSession.lastHeartbeat = now;
            await saveState();
            return;
          } else {
            // Cap exceeded: end session
            await endCurrentSession(currentSession.audibleIdleStart + MAX_AUDIBLE_IDLE_OVERRIDE_MS);
            return;
          }
        }
      }
      // When idle, end the session at now - 300s
      await endCurrentSession(Date.now() - 300_000);
    } else if (newState === 'active') {
      // User resumed activity
      if (currentSession) {
        currentSession.audibleIdleStart = null;
      }
      await checkActiveSession();
    }
  });
}

// Initialize on load
init();

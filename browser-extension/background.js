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

// ── HEARTBEAT ──────────────────────────────────────────────────────────
// The heartbeat is a rolling timestamp updated every HEARTBEAT_INTERVAL_MS
// while a session is live AND the browser window is actually focused.
// When ending a session, if (now - lastHeartbeat) > STALE_THRESHOLD_MS,
// the session end is CAPPED at lastHeartbeat instead of "now",
// preventing ghost sessions from OS sleep, minimized windows, etc.
const HEARTBEAT_INTERVAL_MS = 15_000;       // 15 seconds
const STALE_THRESHOLD_MS    = 90_000;       // 90 seconds of no heartbeat → stale
const MAX_SESSION_DURATION_S = 3600;        // Hard cap: 1 hour per raw event
const HEARTBEAT_ALARM_NAME  = 'session-heartbeat';

// Initialization
async function init() {
  await loadSettings();
  await loadState();
  stateLoaded = true;
  
  // Register alarm for periodic heartbeat (survives service worker suspension)
  chrome.alarms.create(HEARTBEAT_ALARM_NAME, { periodInMinutes: 0.25 }); // Every 15 seconds

  // Flush any offline queued events immediately
  processQueue();
  
  try {
    const win = await chrome.windows.getCurrent();
    if (win && win.focused) {
      const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
      if (tabs.length > 0) {
        const activeTab = tabs[0];
        if (currentSession && activeTab.id === currentSession.tabId) {
          const processed = processUrl(activeTab.url);
          if (processed && processed.url === currentSession.url) {
            // Session still valid — but validate it isn't stale from a previous wake
            const staleness = Date.now() - (currentSession.lastHeartbeat || new Date(currentSession.start).getTime());
            if (staleness > STALE_THRESHOLD_MS) {
              // Stale session from before sleep/restart — end it capped, start fresh
              await endCurrentSession();
              await startSession(activeTab, win.id);
            } else {
              // Still fresh, continue and refresh heartbeat
              currentSession.lastHeartbeat = Date.now();
              await saveState();
            }
            return;
          }
        }
        await endCurrentSession();
        await startSession(activeTab, win.id);
        return;
      }
    }
    // Browser not focused or no active tab
    await endCurrentSession();
  } catch (err) {
    console.error('Error during init:', err);
  }
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

  if (!tab || tab.url === '') {
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

// ── ALARM-BASED HEARTBEAT ──────────────────────────────────────────────
// chrome.alarms survive service worker suspension (unlike setInterval).
// Every 15 seconds: check if we have an active session and if Chrome is
// still the focused window. If yes, bump the heartbeat. If not, end session.
chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== HEARTBEAT_ALARM_NAME) return;
  if (!stateLoaded) return;
  if (!currentSession) return;

  try {
    // Check 1: Is our window still focused?
    const win = await chrome.windows.get(currentSession.windowId);
    if (!win || !win.focused) {
      // Chrome window lost focus without onFocusChanged firing (common on Windows)
      await endCurrentSession();
      return;
    }

    // Check 2: Is the window minimized?
    if (win.state === 'minimized') {
      await endCurrentSession();
      return;
    }

    // Check 3: Is the tab still active?
    const tabs = await chrome.tabs.query({ active: true, windowId: currentSession.windowId });
    if (!tabs.length || tabs[0].id !== currentSession.tabId) {
      // Active tab changed without onActivated firing
      await endCurrentSession();
      if (tabs.length > 0) {
        await startSession(tabs[0], currentSession?.windowId || win.id);
      }
      return;
    }

    // All good — bump heartbeat
    currentSession.lastHeartbeat = Date.now();

    // Check for max session duration (split long sessions into chunks)
    const sessionAge = (Date.now() - new Date(currentSession.start).getTime()) / 1000;
    if (sessionAge >= MAX_SESSION_DURATION_S) {
      // End current and immediately start a new one for the same tab
      const tab = tabs[0];
      const wid = currentSession.windowId;
      await endCurrentSession();
      await startSession(tab, wid);
      return;
    }

    await saveState();
  } catch (e) {
    // Window/tab might have been closed
    await endCurrentSession();
  }
});


// --- Event Listeners ---

// Window focus changed
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (!stateLoaded) return;

  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Browser lost focus entirely
    await endCurrentSession();
  } else {
    // Browser gained focus, start session for active tab
    try {
      const tabs = await chrome.tabs.query({ active: true, windowId: windowId });
      if (tabs.length > 0) {
        await startSession(tabs[0], windowId);
      }
    } catch (e) {
      // Window might have closed or not accessible
    }
  }
});

// Tab activated (switched)
chrome.tabs.onActivated.addListener(async (activeInfo) => {
  if (!stateLoaded) return;

  try {
    const win = await chrome.windows.get(activeInfo.windowId);
    if (win && win.focused) {
      const tab = await chrome.tabs.get(activeInfo.tabId);
      await startSession(tab, activeInfo.windowId);
    }
  } catch (e) {
    // Tab or window might be closing
  }
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

  try {
    const win = await chrome.windows.get(tab.windowId);
    if (!win || !win.focused) return;

    if (currentSession && currentSession.tabId === tabId) {
      const processed = processUrl(tab.url);
      const urlChanged = processed && processed.url !== currentSession.url;

      if (urlChanged) {
        // Navigated to a different URL -> start new session
        await startSession(tab, tab.windowId);
      } else if (tab.title && tab.title !== currentSession.title) {
        // Same page, title dynamically updated -> update title in place
        currentSession.title = tab.title;
        currentSession.lastHeartbeat = Date.now(); // User interaction implied
        await saveState();
      }
    } else {
      await startSession(tab, tab.windowId);
    }
  } catch (e) {}
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
      try {
        const win = await chrome.windows.getCurrent();
        if (win && win.focused) {
          const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
          if (tabs.length > 0) {
            if (!currentSession || currentSession.tabId !== tabs[0].id) {
              await startSession(tabs[0], win.id);
            } else {
              // Same tab, refresh heartbeat
              currentSession.lastHeartbeat = Date.now();
              await saveState();
            }
          }
        }
      } catch (e) {}
    }
  });
}

// Initialize on load
init();

// Configuration defaults
const DEFAULT_SETTINGS = {
  collectorUrl: 'http://127.0.0.1:8765',
  minDuration: 1,
  trackInternal: false,
  stripParams: true
};

// State variables
let settings = { ...DEFAULT_SETTINGS };
let currentSession = null;
let eventQueue = [];
let isProcessingQueue = false;

// Debounce timer for title changes
let titleDebounceTimer = null;

// Initialization
async function init() {
  await loadSettings();
  await loadState();
  
  // Flush any offline queued events immediately
  processQueue();
  
  try {
    const win = await chrome.windows.getCurrent();
    if (win && win.focused) {
      const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
      if (tabs.length > 0) {
        const activeTab = tabs[0];
        if (currentSession && activeTab.id === currentSession.tabId && activeTab.url === currentSession.url) {
          // Session is still valid, continue
          return;
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

  const now = new Date().toISOString();
  currentSession = {
    id: crypto.randomUUID(),
    start: now,
    tabId: tab.id,
    windowId: windowId,
    url: processedInfo.url,
    domain: processedInfo.domain,
    title: tab.title || ''
  };

  await saveState();
}

// End current session and queue event
async function endCurrentSession() {
  if (!currentSession) return;

  const end = new Date().toISOString();
  const startTime = new Date(currentSession.start).getTime();
  const endTime = new Date(end).getTime();
  const durationSeconds = (endTime - startTime) / 1000;

  if (durationSeconds >= settings.minDuration) {
    const event = {
      id: currentSession.id,
      start: currentSession.start,
      end: end,
      duration_seconds: durationSeconds,
      source: 'browser',
      context: {
        browser: getBrowserName(),
        domain: currentSession.domain,
        title: currentSession.title,
        url: currentSession.url,
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
  
  // We'll process items one by one for simplicity, though bulk might be better depending on collector API
  while (eventQueue.length > 0) {
    const event = eventQueue[0];
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(event)
      });

      if (response.ok) {
        eventQueue.shift(); // Remove on success
        await saveState();
      } else {
        // Stop processing on error, wait for next attempt
        break;
      }
    } catch (e) {
      // Network error, collector unreachable
      break;
    }
  }

  isProcessingQueue = false;
}

// Retry queue periodically
setInterval(() => {
  processQueue();
}, 30000);

// --- Event Listeners ---

// Window focus changed
chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) {
    // Browser lost focus
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
  if (!tab.active) return; // Only care about active tabs

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
        // Same page, title dynamically updated (e.g. notifications) -> update title in place, do NOT restart session
        currentSession.title = tab.title;
        await saveState();
      }
    } else {
      await startSession(tab, tab.windowId);
    }
  } catch (e) {}
});

// Tab closed
chrome.tabs.onRemoved.addListener(async (tabId, removeInfo) => {
  if (currentSession && currentSession.tabId === tabId) {
    await endCurrentSession();
  }
});

// Window closed
chrome.windows.onRemoved.addListener(async (windowId) => {
  if (currentSession && currentSession.windowId === windowId) {
    await endCurrentSession();
  }
});

// Idle detection: stop tracking if zero user activity for 5 minutes (300 seconds)
if (chrome.idle) {
  chrome.idle.setDetectionInterval(300);
  chrome.idle.onStateChanged.addListener(async (newState) => {
    if (newState === 'idle' || newState === 'locked') {
      // Inactive for 5 minutes -> end current session
      await endCurrentSession();
    } else if (newState === 'active') {
      // User resumed activity -> start tracking active tab if window focused
      try {
        const win = await chrome.windows.getCurrent();
        if (win && win.focused) {
          const tabs = await chrome.tabs.query({ active: true, windowId: win.id });
          if (tabs.length > 0) {
            await startSession(tabs[0], win.id);
          }
        }
      } catch (e) {}
    }
  });
}

// Initialize on load
init();

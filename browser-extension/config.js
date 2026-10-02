document.addEventListener('DOMContentLoaded', async () => {
  const form = document.getElementById('settingsForm');
  const urlInput = document.getElementById('collectorUrl');
  const authTokenInput = document.getElementById('authToken');
  const minDurationInput = document.getElementById('minDuration');
  const trackInternalInput = document.getElementById('trackInternal');
  const stripParamsInput = document.getElementById('stripParams');
  const testBtn = document.getElementById('testBtn');
  const saveMessage = document.getElementById('saveMessage');
  
  const statusIndicator = document.getElementById('statusIndicator');
  const statusText = document.getElementById('statusText');

  // Load settings
  const data = await chrome.storage.local.get(['settings']);
  const settings = data.settings || {
    collectorUrl: 'http://127.0.0.1:8765',
    authToken: '',
    minDuration: 2,
    trackInternal: false,
    stripParams: true
  };

  urlInput.value = settings.collectorUrl;
  authTokenInput.value = settings.authToken || '';
  minDurationInput.value = settings.minDuration;
  trackInternalInput.checked = settings.trackInternal;
  stripParamsInput.checked = settings.stripParams;

  // Initial connection test
  testConnection();

  // Save settings
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const newSettings = {
      collectorUrl: urlInput.value.replace(/\/$/, ''), // Remove trailing slash
      authToken: authTokenInput.value.trim(),
      minDuration: parseFloat(minDurationInput.value),
      trackInternal: trackInternalInput.checked,
      stripParams: stripParamsInput.checked
    };

    await chrome.storage.local.set({ settings: newSettings });
    
    saveMessage.classList.remove('hidden');
    setTimeout(() => {
      saveMessage.classList.add('hidden');
    }, 3000);

    testConnection();
  });

  // Test connection button
  testBtn.addEventListener('click', testConnection);

  async function testConnection() {
    statusIndicator.className = 'status-indicator loading';
    statusText.textContent = 'Testing connection...';
    
    const url = urlInput.value.replace(/\/$/, '');
    const token = authTokenInput.value.trim();
    
    try {
      const headers = {};
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }
      const response = await fetch(`${url}/config`, { 
        method: 'GET',
        headers: headers
      });
      
      if (response.ok) {
        statusIndicator.className = 'status-indicator success';
        statusText.textContent = 'Connected and authenticated';
      } else if (response.status === 401) {
        statusIndicator.className = 'status-indicator error';
        statusText.textContent = 'Authentication failed: invalid token';
      } else {
        statusIndicator.className = 'status-indicator error';
        statusText.textContent = `Server responded with status ${response.status}`;
      }
    } catch (err) {
      statusIndicator.className = 'status-indicator error';
      statusText.textContent = 'Connection failed. Is the collector running?';
    }
  }
});

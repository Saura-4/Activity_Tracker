document.addEventListener('DOMContentLoaded', async () => {
  const form = document.getElementById('settingsForm');
  const urlInput = document.getElementById('collectorUrl');
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
    minDuration: 40,
    trackInternal: false,
    stripParams: true
  };

  urlInput.value = settings.collectorUrl;
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
    
    try {
      // Assuming collector has a /health or similar, if not just hit the root
      // We will just do a fetch and see if we get a response
      const response = await fetch(`${url}/`, { 
        method: 'GET',
        mode: 'no-cors' // Use no-cors in case CORS isn't set up on root
      });
      
      statusIndicator.className = 'status-indicator success';
      statusText.textContent = 'Connected to Collector';
    } catch (err) {
      statusIndicator.className = 'status-indicator error';
      statusText.textContent = 'Connection failed. Is the collector running?';
    }
  }
});

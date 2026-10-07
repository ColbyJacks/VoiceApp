// The only bridge between the page and the main process.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('voiceapp', {
  call: (method, params = {}) => ipcRenderer.invoke('engine:call', method, params),
  engineStatus: () => ipcRenderer.invoke('engine:status'),
  restartEngine: () => ipcRenderer.invoke('engine:restart'),
  onEvent: (cb) => ipcRenderer.on('engine:event', (_e, msg) => cb(msg)),
  onEngineStatus: (cb) => ipcRenderer.on('engine:status', (_e, status) => cb(status)),

  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (patch) => ipcRenderer.invoke('settings:set', patch),

  info: () => ipcRenderer.invoke('app:info'),
  openVoicesFolder: () => ipcRenderer.invoke('app:open-voices'),
  openLogs: () => ipcRenderer.invoke('app:open-logs'),
  pickVoiceFiles: () => ipcRenderer.invoke('app:pick-voices'),
  pathForFile: (file) => webUtils.getPathForFile(file),
  ready: () => ipcRenderer.send('renderer:ready'),
});

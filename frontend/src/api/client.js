const BASE = '/api'

async function _json(res) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  getBatches() {
    return fetch(`${BASE}/batches`).then(_json)
  },

  getScanStatus() {
    return fetch(`${BASE}/scan/status`).then(_json)
  },

  getConfig() {
    return fetch(`${BASE}/config`).then(_json)
  },

  getStatus() {
    return fetch(`${BASE}/status`).then(_json)
  },

  startScan(settings) {
    return fetch(`${BASE}/scan/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }).then(_json)
  },

  stopScan() {
    return fetch(`${BASE}/scan/stop`, { method: 'POST' }).then(_json)
  },

  renameBatch(id, name) {
    return fetch(`${BASE}/batches/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }).then(_json)
  },

  renameFile(id, filename) {
    return fetch(`${BASE}/batches/${id}/rename-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
    }).then(_json)
  },

  deleteBatch(id) {
    return fetch(`${BASE}/batches/${id}`, { method: 'DELETE' }).then(_json)
  },

  fileUrl(batchId, filename) {
    return `${BASE}/batches/${batchId}/files/${filename}`
  },

  previewUrl(batchId, fileIndex = 0) {
    return `${BASE}/batches/${batchId}/preview/${fileIndex}`
  },

  downloadUrl(batchId, fileIndex = 0) {
    return `${BASE}/batches/${batchId}/preview/${fileIndex}?download=true`
  },

  getAutoscanStatus() {
    return fetch(`${BASE}/autoscan/status`).then(_json)
  },

  enableAutoscan(settings) {
    return fetch(`${BASE}/autoscan/enable`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings),
    }).then(_json)
  },

  disableAutoscan() {
    return fetch(`${BASE}/autoscan/disable`, { method: 'POST' }).then(_json)
  },
}

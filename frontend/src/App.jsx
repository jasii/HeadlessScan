import { useState, useEffect, useRef, useCallback } from 'react'
import ScanControls from './components/ScanControls'
import BatchTable from './components/BatchTable'
import PreviewModal from './components/PreviewModal'
import Console from './components/Console'
import { api } from './api/client'

const MAX_LOGS = 500

export default function App() {
  const [batches, setBatches] = useState([])
  const [scanning, setScanning] = useState(false)
  const [autoScan, setAutoScan] = useState(false)
  const [logs, setLogs] = useState([])
  const [previewBatch, setPreviewBatch] = useState(null)
  const [defaultSettings, setDefaultSettings] = useState(null)
  const wsRef = useRef(null)

  const addLog = useCallback((entry) => {
    setLogs((prev) => {
      const next = [...prev, entry]
      return next.length > MAX_LOGS ? next.slice(-MAX_LOGS) : next
    })
  }, [])

  // Initial data load
  useEffect(() => {
    api.getBatches().then(setBatches).catch(console.error)
    api.getScanStatus().then(({ scanning, autoscan }) => {
      setScanning(scanning)
      setAutoScan(autoscan)
    }).catch(console.error)
    api.getConfig().then((cfg) => {
      setDefaultSettings({
        timeout: cfg.timeout ?? 10,
        format: cfg.format ?? 'pdf',
        dpi: cfg.dpi != null ? String(cfg.dpi) : '',
        duplex: cfg.duplex ?? false,
        blank_page_skip: cfg.blank_page_skip ?? false,
        output_dir: cfg.output_dir ?? '',
        webhook_url: cfg.webhook_url ?? '',
      })
    }).catch(console.error)
  }, [])

  // WebSocket with auto-reconnect
  useEffect(() => {
    let closed = false

    const connect = () => {
      if (closed) return
      const ws = new WebSocket(`ws://${location.host}/ws/logs`)
      wsRef.current = ws

      ws.onopen = () => {
        // Refresh batch list on (re)connect to sync any missed updates
        api.getBatches().then(setBatches).catch(console.error)
      }

      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data)
        switch (msg.type) {
          case 'status':
            setScanning(msg.scanning)
            setAutoScan(msg.autoscan ?? false)
            break
          case 'autoscan_status':
            setAutoScan(msg.enabled)
            if (!msg.enabled) setScanning(false)
            break
          case 'log':
            addLog(msg)
            break
          case 'batch_created':
            // Fetch fresh list so the new scanning row appears immediately
            api.getBatches().then(setBatches).catch(console.error)
            break
          case 'scan_complete':
            setScanning(false)
            setBatches((prev) =>
              prev.map((b) =>
                b.id === msg.batch_id
                  ? { ...b, status: msg.status, pages: msg.pages, files: msg.files }
                  : b,
              ),
            )
            break
          case 'batch_renamed':
            setBatches((prev) =>
              prev.map((b) =>
                b.id === msg.batch_id
                  ? { ...b, name: msg.name, files: msg.files ?? b.files }
                  : b,
              ),
            )
            break
          case 'batch_file_renamed':
            setBatches((prev) =>
              prev.map((b) => (b.id === msg.batch_id ? { ...b, files: msg.files } : b)),
            )
            break
          case 'batch_deleted':
            setBatches((prev) => prev.filter((b) => b.id !== msg.batch_id))
            // Close preview if the deleted batch was open
            setPreviewBatch((prev) => (prev?.id === msg.batch_id ? null : prev))
            break
        }
      }

      ws.onclose = () => {
        if (!closed) setTimeout(connect, 2000)
      }
    }

    connect()
    return () => {
      closed = true
      wsRef.current?.close()
    }
  }, [addLog])

  const handleStartScan = async (settings) => {
    try {
      await api.startScan(settings)
      setScanning(true)
    } catch (err) {
      addLog({ level: 'error', message: err.message, timestamp: new Date().toISOString() })
    }
  }

  const handleStopScan = async () => {
    try {
      await api.stopScan()
    } catch (err) {
      addLog({ level: 'error', message: err.message, timestamp: new Date().toISOString() })
    }
  }

  const handleAutoScanToggle = async (enable, settings) => {
    try {
      if (enable) {
        await api.enableAutoscan(settings)
        setAutoScan(true)
      } else {
        await api.disableAutoscan()
        setAutoScan(false)
      }
    } catch (err) {
      addLog({ level: 'error', message: err.message, timestamp: new Date().toISOString() })
    }
  }

  const handleRename = async (id, name) => {
    try {
      await api.renameBatch(id, name)
    } catch (err) {
      addLog({ level: 'error', message: err.message, timestamp: new Date().toISOString() })
    }
  }

  const handleDelete = async (id) => {
    try {
      await api.deleteBatch(id)
    } catch (err) {
      addLog({ level: 'error', message: err.message, timestamp: new Date().toISOString() })
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <span className="app-header-icon">🖨</span>
        <div>
          <h1>HeadlessScan</h1>
          <p>Epson ADF scanner · headless interface for paperless-ng</p>
        </div>
        <div className={`status-badge ${scanning ? 'scanning' : autoScan ? 'autoscan' : 'idle'}`}>
          {scanning ? '● Scanning' : autoScan ? '● Auto-scan' : '● Idle'}
        </div>
      </header>

      <div className="main-layout">
        <aside className="sidebar">
          <ScanControls
            scanning={scanning}
            autoScan={autoScan}
            onStart={handleStartScan}
            onStop={handleStopScan}
            onAutoScanToggle={handleAutoScanToggle}
            initialSettings={defaultSettings}
          />
        </aside>
        <main className="content">
          <BatchTable
            batches={batches}
            onPreview={setPreviewBatch}
            onRename={handleRename}
            onDelete={handleDelete}
          />
        </main>
      </div>

      <Console logs={logs} />

      {previewBatch && (
        <PreviewModal batch={previewBatch} onClose={() => setPreviewBatch(null)} />
      )}
    </div>
  )
}

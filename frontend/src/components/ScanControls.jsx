import { useState, useEffect } from 'react'

const FORMATS = [
  { value: 'pdf', label: 'PDF' },
  { value: 'png', label: 'PNG' },
  { value: 'jpg', label: 'JPG' },
]

export default function ScanControls({ scanning, autoScan, onStart, onStop, onAutoScanToggle, initialSettings }) {
  const [settings, setSettings] = useState({
    timeout: 10,
    format: 'pdf',
    dpi: '',
    duplex: false,
    blank_page_skip: false,
    output_dir: '',
    webhook_url: '',
  })
  const [settingsLoaded, setSettingsLoaded] = useState(false)

  // Apply config.json defaults once when they arrive from the server
  useEffect(() => {
    if (!settingsLoaded && initialSettings) {
      setSettings(initialSettings)
      setSettingsLoaded(true)
    }
  }, [initialSettings, settingsLoaded])

  const set = (key, value) => setSettings((prev) => ({ ...prev, [key]: value }))

  const buildSettings = () => ({
    timeout: Number(settings.timeout) || 10,
    format: settings.format,
    dpi: settings.dpi !== '' ? Number(settings.dpi) : null,
    duplex: settings.duplex,
    blank_page_skip: settings.blank_page_skip,
    output_dir: settings.output_dir.trim(),
    webhook_url: settings.webhook_url.trim(),
  })

  const handleStart = () => onStart(buildSettings())

  const disabled = scanning || autoScan

  return (
    <section className="card">
      <h2 className="card-title">Scan Settings</h2>

      <div className="field">
        <label>Output Format</label>
        <div className="format-buttons">
          {FORMATS.map((f) => (
            <button
              key={f.value}
              className={`format-btn ${settings.format === f.value ? 'active' : ''}`}
              onClick={() => set('format', f.value)}
              disabled={disabled}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      <div className="field">
        <label>No-document Timeout (seconds)</label>
        <input
          type="number"
          min="1"
          max="300"
          value={settings.timeout}
          onChange={(e) => set('timeout', e.target.value)}
          disabled={disabled}
        />
        <span className="field-hint">
          After the last page, wait this long before finishing the batch
        </span>
      </div>

      <div className="field">
        <label>
          DPI <span className="field-optional">(optional — default 300)</span>
        </label>
        <input
          type="number"
          min="75"
          max="1200"
          step="75"
          placeholder="300"
          value={settings.dpi}
          onChange={(e) => set('dpi', e.target.value)}
          disabled={disabled}
        />
      </div>

      <div className="toggles">
        <label className="toggle">
          <input
            type="checkbox"
            checked={settings.duplex}
            onChange={(e) => set('duplex', e.target.checked)}
            disabled={disabled}
          />
          <span>Duplex (double-sided)</span>
        </label>
        <label className="toggle">
          <input
            type="checkbox"
            checked={settings.blank_page_skip}
            onChange={(e) => set('blank_page_skip', e.target.checked)}
            disabled={disabled}
          />
          <span>Skip blank pages</span>
        </label>
      </div>

      <div className="field">
        <label>
          Save Directory <span className="field-optional">(optional)</span>
        </label>
        <input
          type="text"
          placeholder="/opt/paperless/consume"
          value={settings.output_dir}
          onChange={(e) => set('output_dir', e.target.value)}
          disabled={disabled}
          style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '0.5rem 0.75rem', fontSize: '0.9rem', width: '100%', fontFamily: 'monospace', transition: 'border-color .15s' }}
          onFocus={(e) => e.target.style.borderColor = 'var(--accent)'}
          onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
        />
        <span className="field-hint">
          Finished files are copied here after scanning (e.g. paperless-ng consume folder)
        </span>
      </div>

      <div className="field">
        <label>
          Webhook URL <span className="field-optional">(optional)</span>
        </label>
        <input
          type="url"
          placeholder="https://example.com/webhook"
          value={settings.webhook_url}
          onChange={(e) => set('webhook_url', e.target.value)}
          disabled={disabled}
          style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', color: 'var(--text)', padding: '0.5rem 0.75rem', fontSize: '0.9rem', width: '100%', fontFamily: 'monospace', transition: 'border-color .15s' }}
          onFocus={(e) => e.target.style.borderColor = 'var(--accent)'}
          onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
        />
        <span className="field-hint">
          POST JSON fired after each completed batch (includes batch_id, pages, files)
        </span>
      </div>

      <div className="scan-actions">
        {autoScan ? (
          <>
            <div className={`autoscan-indicator ${scanning ? 'scanning' : 'waiting'}`}>
              {scanning ? '● Scanning document…' : '● Waiting for document…'}
            </div>
            <button className="btn btn-danger" onClick={() => onAutoScanToggle(false, null)}>
              ■ Disable Auto-scan
            </button>
          </>
        ) : scanning ? (
          <button className="btn btn-danger" onClick={onStop}>
            ■ Stop Scan
          </button>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <button className="btn btn-primary" onClick={handleStart}>
              ▶ Start Scan
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => onAutoScanToggle(true, buildSettings())}
            >
              ↻ Enable Auto-scan
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

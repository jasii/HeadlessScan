import { useState } from 'react'
import { api } from '../api/client'

function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{status}</span>
}

function BatchRow({ batch, onPreview, onRename, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(batch.name)

  const SAFE_RE = /[^A-Za-z0-9 _\-.]/g

  const commit = () => {
    const trimmed = name.trim()
    if (trimmed && trimmed !== batch.name) {
      onRename(batch.id, trimmed)
    } else {
      setName(batch.name)
    }
    setEditing(false)
  }

  // Keep local name in sync if a WS rename event updates batch.name externally
  if (!editing && name !== batch.name) {
    setName(batch.name)
  }

  const created = new Date(batch.created_at).toLocaleString()
  // A file is "external" if it starts with / (absolute path outside batches dir).
  const isExternal = batch.files?.length > 0 && batch.files[0].startsWith('/')
  const canPreview = batch.status === 'done' && batch.files?.length > 0

  // Show just the directory of the first external file as the save location.
  const savedTo = isExternal
    ? batch.files[0].replace(/\/[^\/]+$/, '')
    : null

  // Derive current filename from full path for display only.
  const currentFileName = batch.files?.length > 0
    ? batch.files[0].replace(/.*\//, '')
    : null

  return (
    <tr className={batch.status === 'scanning' ? 'row-scanning' : ''}>
      <td>
        {editing ? (
          <div className="inline-edit">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value.replace(SAFE_RE, ''))}
              onBlur={commit}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                if (e.key === 'Escape') { setName(batch.name); setEditing(false) }
              }}
            />
          </div>
        ) : (
          <div className="batch-name">
            <span>{batch.name}</span>
            <button
              className="icon-btn"
              onClick={() => setEditing(true)}
              title="Rename"
            >
              ✎
            </button>
            {savedTo && (
              <span className="saved-path" title={savedTo}>
                Saved to: {savedTo}
              </span>
            )}
            {currentFileName && batch.status === 'done' && (
              <span className="file-name-display" title={currentFileName}>
                {currentFileName}
              </span>
            )}
          </div>
        )}
      </td>
      <td>{created}</td>
      <td>{batch.pages}</td>
      <td><span className="format-tag">{batch.format.toUpperCase()}</span></td>
      <td><StatusBadge status={batch.status} /></td>
      <td>
        <div className="row-actions">
          <button
            className="action-icon"
            onClick={() => onPreview(batch)}
            disabled={!canPreview}
            title={canPreview ? 'Preview' : 'Not available yet'}
          >
            &#128065;
          </button>
          {canPreview ? (
            <a
              className="action-icon"
              href={api.downloadUrl(batch.id, 0)}
              title="Download"
            >
              &#8659;
            </a>
          ) : (
            <button className="action-icon" disabled title="Not available yet">&#8659;</button>
          )}
          <button
            className="action-icon action-icon-danger"
            disabled={batch.status === 'scanning'}
            title="Delete"
            onClick={() => {
              if (window.confirm(`Delete "${batch.name}"? This cannot be undone.`)) {
                onDelete(batch.id)
              }
            }}
          >
            &#128465;
          </button>
        </div>
      </td>
    </tr>
  )
}

export default function BatchTable({ batches, onPreview, onRename, onDelete }) {
  return (
    <section className="card">
      <h2 className="card-title">Scan Batches</h2>
      {batches.length === 0 ? (
        <p className="empty-state">No batches yet. Start a scan to create one.</p>
      ) : (
        <div className="table-wrap">
          <table className="batch-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Created</th>
                <th>Pages</th>
                <th>Format</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <BatchRow
                  key={b.id}
                  batch={b}
                  onPreview={onPreview}
                  onRename={onRename}
                  onDelete={onDelete}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

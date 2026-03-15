import { useEffect } from 'react'
import { api } from '../api/client'

export default function PreviewModal({ batch, onClose }) {
  // Close on Escape key
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const isPdf   = batch.format === 'pdf'
  const isImage = batch.format === 'png' || batch.format === 'jpg'

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal" onClick={(e) => e.stopPropagation()}>

        <div className="modal-header">
          <h2>{batch.name}</h2>
          <button className="modal-close" onClick={onClose} aria-label="Close preview">✕</button>
        </div>

        <div className="modal-body">
          {isPdf && batch.files?.[0] && (
            <iframe
              className="pdf-preview"
              src={api.previewUrl(batch.id, 0)}
              title="PDF Preview"
            />
          )}

          {isImage && (
            <div className="image-grid">
              {batch.files?.map((_, i) => (
                <div key={i} className="image-card">
                  <img
                    src={api.previewUrl(batch.id, i)}
                    alt={`Page ${i + 1}`}
                    loading="lazy"
                  />
                  <span className="image-caption">Page {i + 1}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <span className="modal-info">
            {batch.pages} page(s) · {batch.format.toUpperCase()}
          </span>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {isPdf && batch.files?.[0] && (
              <>
                <a
                  className="btn btn-secondary btn-sm"
                  href={api.previewUrl(batch.id, 0)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in new tab ↗
                </a>
                <a
                  className="btn btn-primary btn-sm"
                  href={api.downloadUrl(batch.id, 0)}
                >
                  ↓ Download PDF
                </a>
              </>
            )}
            {isImage && batch.files?.map((_, i) => (
              <a
                key={i}
                className="btn btn-primary btn-sm"
                href={api.downloadUrl(batch.id, i)}
              >
                ↓ Page {i + 1}
              </a>
            ))}
            <button className="btn btn-secondary btn-sm" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

      </div>
    </div>
  )
}

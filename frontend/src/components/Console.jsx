import { useEffect, useRef } from 'react'

const LEVEL_COLOR = {
  info:     '#94a3b8',
  warning:  '#f59e0b',
  error:    '#ef4444',
  critical: '#f43f5e',
}

export default function Console({ logs }) {
  const bottomRef = useRef(null)

  // Auto-scroll to the latest log entry
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [logs])

  return (
    <section className="console-section">
      <h2 className="card-title">Console</h2>
      <div className="console">
        {logs.length === 0 && (
          <span className="console-empty">Waiting for events…</span>
        )}
        {logs.map((log, i) => {
          const time = new Date(log.timestamp).toLocaleTimeString()
          return (
            <div key={i} className="console-line">
              <span className="console-time">{time}</span>
              <span
                className="console-level"
                style={{ color: LEVEL_COLOR[log.level] ?? LEVEL_COLOR.info }}
              >
                [{log.level.toUpperCase()}]
              </span>
              <span className="console-msg">{log.message}</span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </section>
  )
}

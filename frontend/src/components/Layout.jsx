import { useState, useEffect } from 'react'
import { useProject } from '../context/ProjectContext'
import { Link, useLocation } from 'react-router-dom'

export default function Layout({ children }) {
    const [sidebarOpen, setSidebarOpen] = useState(false)

    return (
        <div className="flex min-h-screen">
            {/* Sidebar */}
            <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

            {/* Main content */}
            <div className="flex-1 flex flex-col min-h-screen">
                <header className="flex items-center justify-between px-6 py-4 border-b border-[var(--color-border)]">
                    <div className="flex items-center gap-4">
                        <Link to="/" className="text-xl font-bold tracking-tight bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] bg-clip-text text-transparent">
                            CLIPR
                        </Link>
                    </div>
                    <button
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        className="px-4 py-2 text-sm rounded-lg border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] transition-colors"
                    >
                        Project History ›
                    </button>
                </header>

                <main className="flex-1 p-6 max-w-5xl mx-auto w-full">
                    {children}
                </main>
            </div>
        </div>
    )
}

function Sidebar({ open, onClose }) {
    const { state } = useProject()
    const [history, setHistory] = useState([])

    useEffect(() => {
        fetch('/api/history')
            .then(r => r.json())
            .then(d => setHistory(d.projects || []))
            .catch(() => { })
    }, [open])

    return (
        <>
            {/* Overlay */}
            {open && (
                <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
            )}

            {/* Panel */}
            <div className={`fixed right-0 top-0 h-full w-80 bg-[var(--color-bg-secondary)] border-l border-[var(--color-border)] z-50 transform transition-transform duration-300 ${open ? 'translate-x-0' : 'translate-x-full'}`}>
                <div className="p-6">
                    <div className="flex items-center justify-between mb-6">
                        <h2 className="text-lg font-semibold">Project History</h2>
                        <button onClick={onClose} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">✕</button>
                    </div>

                    {history.length === 0 ? (
                        <p className="text-[var(--color-text-muted)] text-sm">No projects yet</p>
                    ) : (
                        <div className="space-y-3">
                            {history.map((p, i) => (
                                <Link
                                    key={i}
                                    to={`/project/${p.project_id}/export`}
                                    onClick={onClose}
                                    className="block p-3 rounded-lg bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] transition-colors"
                                >
                                    <div className="text-sm font-medium truncate">{p.source || `Project ${p.project_id}`}</div>
                                    <div className="flex items-center gap-2 mt-1 text-xs text-[var(--color-text-muted)]">
                                        <span className={`inline-block w-2 h-2 rounded-full ${p.status === 'export_ready' ? 'bg-[var(--color-success)]' : p.status === 'error' ? 'bg-[var(--color-danger)]' : 'bg-[var(--color-warning)]'}`} />
                                        <span>{p.genre}</span>
                                        <span>·</span>
                                        <span>{new Date(p.created_at).toLocaleDateString()}</span>
                                    </div>
                                </Link>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </>
    )
}

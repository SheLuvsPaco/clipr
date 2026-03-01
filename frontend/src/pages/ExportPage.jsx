import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

export default function ExportPage() {
    const { projectId } = useParams()
    const navigate = useNavigate()
    const [exports, setExports] = useState([])
    const [clipMeta, setClipMeta] = useState([])
    const [loading, setLoading] = useState(true)
    const [editingAss, setEditingAss] = useState(null) // { clipId, content }
    const [rerendering, setRerendering] = useState(false)

    useEffect(() => {
        fetchExports()
    }, [projectId])

    const fetchExports = async () => {
        try {
            const res = await fetch(`http://localhost:8000/api/projects/${projectId}/exports`)
            if (res.ok) {
                const data = await res.json()
                setExports(data.exports || [])
                setClipMeta(data.clip_metadata || [])
            }
        } catch { }
        setLoading(false)
    }

    const downloadClip = (clipId) => {
        window.open(`http://localhost:8000/api/projects/${projectId}/exports/${clipId}`, '_blank')
    }

    const downloadAll = () => {
        window.open(`http://localhost:8000/api/projects/${projectId}/exports/all.zip`, '_blank')
    }

    const openAssEditor = async (clipId) => {
        try {
            const res = await fetch(`http://localhost:8000/api/projects/${projectId}/clips/${clipId}/ass`)
            if (res.ok) {
                const data = await res.json()
                setEditingAss({ clipId, content: data.ass_content })
            }
        } catch { }
    }

    const saveAss = async () => {
        if (!editingAss) return
        setRerendering(true)
        try {
            const res = await fetch(`http://localhost:8000/api/projects/${projectId}/clips/${editingAss.clipId}/rerender`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ass_content: editingAss.content }),
            })
            if (res.ok) {
                setEditingAss(null)
                fetchExports() // refresh
            }
        } catch { }
        setRerendering(false)
    }

    const getClipMeta = (filename) => {
        const match = filename.match(/clip_(\d+)_final/)
        if (!match) return null
        const id = parseInt(match[1])
        return clipMeta.find(c => c.rank === id)
    }

    const formatDuration = (seconds) => {
        const m = Math.floor(seconds / 60)
        const s = Math.round(seconds % 60)
        return `${m}:${s.toString().padStart(2, '0')}`
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="text-[var(--color-text-muted)] animate-pulse">Loading exports...</div>
            </div>
        )
    }

    return (
        <div className="space-y-8 animate-in fade-in">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold">Done! {exports.length} clips ready 🎉</h1>
                    <p className="text-sm text-[var(--color-text-muted)] mt-1">Download your viral-ready clips</p>
                </div>
                {exports.length > 1 && (
                    <button
                        onClick={downloadAll}
                        className="px-6 py-3 rounded-xl font-semibold text-sm bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] text-white hover:shadow-lg hover:shadow-[var(--color-accent)]/25 transition-all"
                    >
                        ↓ Download All
                    </button>
                )}
            </div>

            {/* ASS Editor Modal */}
            {editingAss && (
                <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-8">
                    <div className="bg-[var(--color-bg-secondary)] rounded-2xl p-6 w-full max-w-3xl max-h-[80vh] flex flex-col border border-[var(--color-border)]">
                        <div className="flex items-center justify-between mb-4">
                            <h3 className="font-semibold">Edit Captions — Clip {editingAss.clipId}</h3>
                            <button onClick={() => setEditingAss(null)} className="text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)]">✕</button>
                        </div>
                        <textarea
                            value={editingAss.content}
                            onChange={(e) => setEditingAss({ ...editingAss, content: e.target.value })}
                            className="flex-1 w-full p-4 rounded-xl bg-[var(--color-bg-primary)] border border-[var(--color-border)] text-sm font-mono text-[var(--color-text-primary)] resize-none focus:outline-none focus:border-[var(--color-accent)]"
                            spellCheck={false}
                        />
                        <div className="flex justify-end gap-3 mt-4">
                            <button onClick={() => setEditingAss(null)} className="px-4 py-2 rounded-lg text-sm border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors">
                                Cancel
                            </button>
                            <button
                                onClick={saveAss}
                                disabled={rerendering}
                                className="px-6 py-2 rounded-lg text-sm font-medium bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-light)] transition-colors disabled:opacity-50"
                            >
                                {rerendering ? 'Re-rendering...' : 'Save & Re-render'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Clip Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {exports.map((exp, i) => {
                    const meta = getClipMeta(exp.filename)
                    const clipId = exp.filename.match(/clip_(\d+)/)?.[1] || i + 1
                    const duration = meta ? (meta.end || 0) - (meta.start || 0) : 0

                    return (
                        <div key={i} className="rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] overflow-hidden hover:border-[var(--color-border-light)] transition-all">
                            {/* Video preview area */}
                            <div className="aspect-[9/16] bg-[var(--color-bg-primary)] flex items-center justify-center relative max-h-64">
                                <video
                                    src={`http://localhost:8000/api/projects/${projectId}/exports/${clipId}`}
                                    className="w-full h-full object-contain"
                                    preload="metadata"
                                />
                                {duration > 0 && (
                                    <span className="absolute bottom-2 right-2 px-2 py-0.5 rounded text-xs bg-black/70 text-white">
                                        {formatDuration(duration)}
                                    </span>
                                )}
                            </div>

                            {/* Info */}
                            <div className="p-4 space-y-3">
                                <div>
                                    {meta?.suggested_title && (
                                        <p className="text-sm font-medium truncate">{meta.suggested_title}</p>
                                    )}
                                    <div className="flex items-center gap-2 mt-1 text-xs text-[var(--color-text-muted)]">
                                        {meta?.overall_score && <span>Score: {meta.overall_score}</span>}
                                        {meta?.caption_style && (
                                            <span className="px-1.5 py-0.5 rounded bg-[var(--color-accent)]/10 text-[var(--color-accent-light)]">
                                                {meta.caption_style}
                                            </span>
                                        )}
                                        <span>{exp.size_mb} MB</span>
                                    </div>
                                </div>

                                {/* Actions */}
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => downloadClip(clipId)}
                                        className="flex-1 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] text-white hover:shadow-md transition-all"
                                    >
                                        ↓ Download
                                    </button>
                                    <button
                                        onClick={() => openAssEditor(parseInt(clipId))}
                                        className="px-3 py-2 rounded-lg text-xs border border-[var(--color-border)] text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] transition-colors"
                                        title="Edit captions"
                                    >
                                        ✏
                                    </button>
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>

            {/* Run Summary */}
            <div className="p-6 rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] space-y-2">
                <h3 className="font-semibold text-sm text-[var(--color-text-muted)]">Run Summary</h3>
                <div className="grid grid-cols-2 gap-2 text-sm">
                    <span className="text-[var(--color-text-muted)]">Clips exported:</span>
                    <span>{exports.length}</span>
                    <span className="text-[var(--color-text-muted)]">Total size:</span>
                    <span>{exports.reduce((a, e) => a + e.size_mb, 0).toFixed(1)} MB</span>
                </div>
            </div>

            {/* New Project */}
            <div className="text-center pb-8">
                <button
                    onClick={() => navigate('/')}
                    className="px-6 py-3 rounded-xl text-sm font-medium border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors"
                >
                    Start a new project
                </button>
            </div>
        </div>
    )
}

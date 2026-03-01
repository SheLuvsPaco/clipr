import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useProject } from '../context/ProjectContext'
import CaptionStylePicker from '../components/CaptionStylePicker'
import ErrorBanner from '../components/ErrorBanner'

const FILTERS = [
    { id: 'all', label: 'All' },
    { id: 'strong', label: '★ Strong' },
    { id: 'approved', label: '✓ Approved' },
    { id: 'rejected', label: '✗ Rejected' },
]

function getStrength(score) {
    if (score >= 80) return { label: 'STRONG', color: 'var(--color-strong)' }
    if (score >= 60) return { label: 'DECENT', color: 'var(--color-decent)' }
    return { label: 'WEAK', color: 'var(--color-weak)' }
}

function formatDuration(seconds) {
    const m = Math.floor(seconds / 60)
    const s = Math.round(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
}

function ScoreBar({ label, score }) {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-20 text-[var(--color-text-muted)]">{label}</span>
            <div className="flex-1 h-1.5 bg-[var(--color-bg-primary)] rounded-full overflow-hidden">
                <div
                    className="h-full rounded-full bg-[var(--color-accent-light)] transition-all"
                    style={{ width: `${score * 10}%` }}
                />
            </div>
            <span className="w-8 text-right text-[var(--color-text-muted)]">{score}/10</span>
        </div>
    )
}

export default function ClipReviewPage() {
    const { projectId } = useParams()
    const navigate = useNavigate()
    const { state, dispatch } = useProject()
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sending, setSending] = useState(false)

    useEffect(() => {
        fetchClips()
    }, [projectId])

    const fetchClips = async () => {
        try {
            // Try the job-based endpoint first
            const res = await fetch(`http://localhost:8000/api/clips/${projectId}`)
            if (res.ok) {
                const data = await res.json()
                dispatch({ type: 'LOAD_CLIPS', clips: data.clips || [] })
                setLoading(false)
                return
            }
        } catch { }

        // Fallback: try project-based
        try {
            const res = await fetch(`http://localhost:8000/api/projects/${projectId}/clips`)
            if (res.ok) {
                const data = await res.json()
                dispatch({ type: 'LOAD_CLIPS', clips: data.clips || [] })
            }
        } catch (e) {
            setError({ message: 'Failed to load clips' })
        }
        setLoading(false)
    }

    const approvedCount = Object.values(state.decisions).filter(d => d === 'approved').length
    const rejectedCount = Object.values(state.decisions).filter(d => d === 'rejected').length

    const filteredClips = state.clips.filter(clip => {
        const decision = state.decisions[clip.rank]
        switch (state.filter) {
            case 'strong': return (clip.overall_score || 0) >= 80
            case 'approved': return decision === 'approved'
            case 'rejected': return decision === 'rejected'
            default: return true
        }
    })

    const strongCount = state.clips.filter(c => (c.overall_score || 0) >= 80).length

    const handleSendToProcessing = async () => {
        setSending(true)
        const approved = Object.entries(state.decisions)
            .filter(([_, status]) => status === 'approved')
            .map(([clipId]) => ({
                clip_id: parseInt(clipId),
                style: state.styles[clipId] || 'hormozi',
                trim_start: state.trims[clipId]?.start ?? 0,
                trim_end: state.trims[clipId]?.end ?? 0,
            }))

        try {
            const res = await fetch(`http://localhost:8000/api/projects/${projectId}/process`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ clips: approved }),
            })

            if (!res.ok) throw new Error('Failed to start processing')
            navigate(`/project/${projectId}/processing`)
        } catch (e) {
            setError({ message: e.message })
            setSending(false)
        }
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center h-64">
                <div className="text-[var(--color-text-muted)] animate-pulse">Loading clips...</div>
            </div>
        )
    }

    return (
        <div className="space-y-6 animate-in fade-in">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold">Clip Review</h1>
                    <p className="text-sm text-[var(--color-text-muted)] mt-1">
                        {state.clips.length} candidates found · {approvedCount} approved
                    </p>
                </div>
                <button
                    onClick={handleSendToProcessing}
                    disabled={approvedCount === 0 || sending}
                    className="px-6 py-3 rounded-xl font-semibold text-sm transition-all duration-200 bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] text-white hover:shadow-lg hover:shadow-[var(--color-accent)]/25 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {sending ? 'Starting...' : `Send ${approvedCount} to Processing ›`}
                </button>
            </div>

            <ErrorBanner error={error} onRetry={() => setError(null)} />

            {/* Filter Tabs */}
            <div className="flex gap-2">
                {FILTERS.map(f => (
                    <button
                        key={f.id}
                        onClick={() => dispatch({ type: 'SET_FILTER', filter: f.id })}
                        className={`px-4 py-2 rounded-lg text-sm transition-all ${state.filter === f.id
                                ? 'bg-[var(--color-accent)]/15 text-[var(--color-accent-light)] border border-[var(--color-accent)]/30'
                                : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                            }`}
                    >
                        {f.label} {f.id === 'all' ? state.clips.length : f.id === 'strong' ? strongCount : f.id === 'approved' ? approvedCount : rejectedCount}
                    </button>
                ))}
            </div>

            {/* Clip Cards */}
            <div className="space-y-4">
                {filteredClips.map(clip => {
                    const decision = state.decisions[clip.rank]
                    const strength = getStrength(clip.overall_score || 0)
                    const duration = (clip.end || 0) - (clip.start || 0)

                    return (
                        <div
                            key={clip.rank}
                            className={`rounded-xl border transition-all duration-300 ${decision === 'approved'
                                    ? 'border-[var(--color-success)]/30 bg-[var(--color-bg-card)]'
                                    : decision === 'rejected'
                                        ? 'border-[var(--color-border)] bg-[var(--color-bg-card)] opacity-50'
                                        : 'border-[var(--color-border)] bg-[var(--color-bg-card)] hover:border-[var(--color-border-light)]'
                                }`}
                        >
                            <div className="p-5 space-y-4">
                                {/* Card Header */}
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-3">
                                        <span className="text-sm font-bold text-[var(--color-text-muted)]">Clip {clip.rank}</span>
                                        <span className="text-sm">Score: {clip.overall_score || 0}</span>
                                        <span
                                            className="px-2 py-0.5 rounded text-xs font-bold"
                                            style={{ color: strength.color, backgroundColor: `${strength.color}15` }}
                                        >
                                            {strength.label}
                                        </span>
                                        <span className="text-sm text-[var(--color-text-muted)]">{formatDuration(duration)}</span>
                                    </div>
                                    {decision === 'approved' && (
                                        <span className="text-xs text-[var(--color-success)] font-medium">✓ Approved</span>
                                    )}
                                </div>

                                {/* Hook & Title */}
                                <div className="space-y-1">
                                    {clip.hook_text && (
                                        <p className="text-sm italic text-[var(--color-text-secondary)]">
                                            "{clip.hook_text}"
                                        </p>
                                    )}
                                    {clip.suggested_title && (
                                        <p className="text-sm font-medium">{clip.suggested_title}</p>
                                    )}
                                </div>

                                {/* Scores */}
                                <div className="grid grid-cols-3 gap-3">
                                    <ScoreBar label="Hook" score={clip.hook_score || 0} />
                                    <ScoreBar label="Narrative" score={clip.narrative_score || 0} />
                                    <ScoreBar label="Standalone" score={clip.standalone_score || 0} />
                                </div>

                                {/* Caption Style */}
                                <div className="space-y-2">
                                    <span className="text-xs text-[var(--color-text-muted)]">Caption Style</span>
                                    <CaptionStylePicker
                                        selected={state.styles[clip.rank] || 'hormozi'}
                                        onChange={(style) => dispatch({ type: 'SET_STYLE', clipId: clip.rank, style })}
                                    />
                                </div>

                                {/* Actions */}
                                <div className="flex justify-end gap-3 pt-2 border-t border-[var(--color-border)]">
                                    <button
                                        onClick={() => dispatch({ type: 'REJECT_CLIP', clipId: clip.rank })}
                                        className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${decision === 'rejected'
                                                ? 'bg-[var(--color-danger)]/15 text-[var(--color-danger)] border border-[var(--color-danger)]/30'
                                                : 'text-[var(--color-text-muted)] hover:text-[var(--color-danger)] hover:bg-[var(--color-danger)]/5 border border-[var(--color-border)]'
                                            }`}
                                    >
                                        ✗ Reject
                                    </button>
                                    <button
                                        onClick={() => dispatch({ type: 'APPROVE_CLIP', clipId: clip.rank })}
                                        className={`px-5 py-2 rounded-lg text-sm font-medium transition-all ${decision === 'approved'
                                                ? 'bg-[var(--color-success)]/15 text-[var(--color-success)] border border-[var(--color-success)]/30'
                                                : 'text-[var(--color-text-secondary)] hover:text-[var(--color-success)] hover:bg-[var(--color-success)]/5 border border-[var(--color-border)]'
                                            }`}
                                    >
                                        ✓ Approve
                                    </button>
                                </div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

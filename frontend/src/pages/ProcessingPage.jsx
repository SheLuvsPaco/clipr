import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWebSocket } from '../hooks/useWebSocket'
import ProgressBar from '../components/ProgressBar'

const STEP_LABELS = {
    cutting: 'Cutting',
    jump_cutting: 'Jump cuts',
    analysing: 'Layout detection',
    tracking: 'Face tracking',
    cropping: 'Cropping & reframing',
    normalising: 'Audio normalisation',
    encoding: 'Encoding',
    filtering: 'Filtering words',
    rendering: 'Burning captions',
    saving: 'Saving',
}

export default function ProcessingPage() {
    const { projectId } = useParams()
    const navigate = useNavigate()
    const [clips, setClips] = useState([])
    const [currentClip, setCurrentClip] = useState(null)
    const [overallPercent, setOverallPercent] = useState(0)
    const [done, setDone] = useState(false)
    const [error, setError] = useState(null)

    useWebSocket(
        `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/ws/project/${projectId}/processing`,
        {
            onMessage: (data) => {
                if (data.stage === 'complete') {
                    setDone(true)
                    setOverallPercent(100)
                    return
                }
                if (data.stage === 'error') {
                    setError(data.message)
                    return
                }
                if (data.percent) setOverallPercent(data.percent)
                if (data.clip_id) setCurrentClip(data.clip_id)
            },
            enabled: !done,
        }
    )

    // Fallback polling
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`/api/projects/${projectId}`)
                if (res.ok) {
                    const data = await res.json()
                    if (data.status === 'export_ready') setDone(true)
                }
            } catch { }
        }, 5000)
        return () => clearInterval(interval)
    }, [projectId])

    return (
        <div className="max-w-2xl mx-auto mt-12 space-y-8 animate-in fade-in">
            <div className="text-center space-y-2">
                <h1 className="text-2xl font-bold">
                    {done ? 'All clips ready! 🎉' : error ? 'Processing Error' : 'Processing clips...'}
                </h1>
                {!done && !error && (
                    <p className="text-[var(--color-text-secondary)]">
                        Cutting, reframing, and burning captions
                    </p>
                )}
            </div>

            {error ? (
                <div className="p-6 rounded-xl border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 text-center space-y-4">
                    <p className="text-[var(--color-danger)]">{error}</p>
                    <button onClick={() => navigate('/')} className="px-6 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] text-sm">
                        Start over
                    </button>
                </div>
            ) : (
                <>
                    {/* Overall progress */}
                    <div className="space-y-2">
                        <ProgressBar percent={overallPercent} />
                        <div className="text-right text-sm text-[var(--color-text-muted)]">
                            {Math.round(overallPercent)}%
                        </div>
                    </div>

                    {/* Processing indicator */}
                    {!done && (
                        <div className="p-6 rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] space-y-4">
                            <div className="flex items-center gap-3">
                                <span className="animate-spin text-[var(--color-accent-light)]">↻</span>
                                <span className="font-medium">Processing in progress...</span>
                            </div>
                            <div className="text-sm text-[var(--color-text-muted)]">
                                Clips are processed one at a time to avoid saturating the CPU.
                                Each clip goes through cutting, face tracking, cropping, encoding, and caption burning.
                            </div>
                        </div>
                    )}

                    {/* Done → Export */}
                    {done && (
                        <div className="text-center">
                            <button
                                onClick={() => navigate(`/project/${projectId}/export`)}
                                className="px-8 py-4 rounded-xl font-semibold bg-gradient-to-r from-[var(--color-success)] to-[var(--color-accent)] text-white hover:shadow-lg transition-all"
                            >
                                Go to Export →
                            </button>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

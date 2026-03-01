import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useWebSocket } from '../hooks/useWebSocket'
import ProgressBar from '../components/ProgressBar'

const STATUS_ICONS = {
    done: '✓',
    running: '↻',
    waiting: '·',
}

const STAGE_ORDER = ['download', 'extract', 'preprocess', 'transcribe', 'postprocess']
const STAGE_LABELS = {
    download: 'Downloading video',
    extract: 'Extracting audio',
    preprocess: 'Preprocessing audio',
    transcribe: 'Transcribing with Whisper',
    postprocess: 'Post-processing transcript',
}

export default function TranscribingPage() {
    const { projectId } = useParams()
    const navigate = useNavigate()
    const [progress, setProgress] = useState({
        stage: 'initialising',
        percent: 0,
        steps: [],
        message: '',
        eta_seconds: null,
    })
    const [error, setError] = useState(null)
    const [logs, setLogs] = useState([])
    const [logsOpen, setLogsOpen] = useState(true)
    const logEndRef = useRef(null)

    useWebSocket(
        `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/ws/project/${projectId}`,
        {
            onMessage: (data) => {
                // Accumulate log entries
                if (data.type === 'log') {
                    setLogs(prev => [...prev, data])
                    return
                }

                if (data.stage === 'complete') {
                    setLogs(prev => [...prev, { ts: new Date().toLocaleTimeString('en-GB', { hour12: false }), level: 'success', log: 'Pipeline complete — navigating to review...' }])
                    setTimeout(() => navigate(`/project/${projectId}/review`), 1200)
                    return
                }
                if (data.stage === 'error') {
                    setLogs(prev => [...prev, { ts: new Date().toLocaleTimeString('en-GB', { hour12: false }), level: 'error', log: data.message || 'Processing failed' }])
                    setError({ message: data.message || 'Processing failed' })
                    return
                }
                setProgress(prev => ({ ...prev, ...data }))
            },
            enabled: true,
        }
    )

    // Auto-scroll logs
    useEffect(() => {
        logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [logs])

    // Fallback polling if WebSocket isn't available
    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`/api/projects/${projectId}`)
                if (res.ok) {
                    const data = await res.json()
                    if (data.status === 'completed' || data.stage === 'done') {
                        navigate(`/project/${projectId}/review`)
                    }
                }
            } catch { }
        }, 5000)
        return () => clearInterval(interval)
    }, [projectId])

    // Derive step statuses from current stage
    const currentStage = progress.stage
    const steps = STAGE_ORDER.map(id => {
        const idx = STAGE_ORDER.indexOf(id)
        const currentIdx = STAGE_ORDER.indexOf(currentStage)
        let status = 'waiting'
        if (currentIdx > idx) status = 'done'
        else if (currentIdx === idx) status = 'running'
        return { name: STAGE_LABELS[id], status }
    })

    const logLevelColor = (level) => {
        switch (level) {
            case 'error': return 'text-red-400'
            case 'success': return 'text-emerald-400'
            case 'warn': return 'text-amber-400'
            default: return 'text-[var(--color-text-secondary)]'
        }
    }

    const logLevelBadge = (level) => {
        switch (level) {
            case 'error': return 'ERR'
            case 'success': return ' OK'
            case 'warn': return 'WRN'
            default: return 'INF'
        }
    }

    return (
        <div className="max-w-2xl mx-auto mt-12 space-y-6 animate-in fade-in">
            <div className="text-center space-y-2">
                <h1 className="text-2xl font-bold">
                    {error ? 'Processing Failed' : 'Transcribing...'}
                </h1>
                {progress.message && !error && (
                    <p className="text-[var(--color-text-secondary)]">{progress.message}</p>
                )}
            </div>

            {error ? (
                <div className="p-6 rounded-xl border border-[var(--color-danger)]/30 bg-[var(--color-danger)]/5 text-center space-y-4">
                    <p className="text-[var(--color-danger)]">{error.message}</p>
                    <button
                        onClick={() => navigate('/')}
                        className="px-6 py-2 rounded-lg bg-[var(--color-bg-card)] border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors text-sm"
                    >
                        Start over
                    </button>
                </div>
            ) : (
                <>
                    {/* Progress bar */}
                    <div className="space-y-2">
                        <ProgressBar percent={progress.percent || 0} />
                        <div className="flex justify-between text-sm text-[var(--color-text-muted)]">
                            <span>{Math.round(progress.percent || 0)}%</span>
                            {progress.eta_seconds && <span>ETA: {formatEta(progress.eta_seconds)}</span>}
                        </div>
                    </div>

                    {/* Step list */}
                    <div className="space-y-2">
                        {steps.map((step, i) => (
                            <div
                                key={i}
                                className={`flex items-center justify-between p-3 rounded-lg transition-all duration-300 ${step.status === 'running'
                                        ? 'bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/20'
                                        : step.status === 'done'
                                            ? 'opacity-60'
                                            : 'opacity-40'
                                    }`}
                            >
                                <div className="flex items-center gap-3">
                                    <span className={`text-sm ${step.status === 'done' ? 'text-[var(--color-success)]'
                                            : step.status === 'running' ? 'text-[var(--color-accent-light)] animate-spin'
                                                : 'text-[var(--color-text-muted)]'
                                        }`}>
                                        {STATUS_ICONS[step.status] || '·'}
                                    </span>
                                    <span className="text-sm">{step.name}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {/* Live Log Panel */}
            <div className="rounded-xl border border-[var(--color-border)] overflow-hidden">
                <button
                    onClick={() => setLogsOpen(prev => !prev)}
                    className="w-full flex items-center justify-between px-4 py-3 bg-[var(--color-bg-card)] hover:bg-[var(--color-bg-hover)] transition-colors text-sm font-medium"
                >
                    <div className="flex items-center gap-2">
                        <span className="font-mono text-xs px-1.5 py-0.5 rounded bg-[var(--color-accent)]/15 text-[var(--color-accent-light)]">LIVE</span>
                        <span>Pipeline Logs</span>
                        <span className="text-[var(--color-text-muted)]">({logs.length})</span>
                    </div>
                    <span className="text-[var(--color-text-muted)] text-xs">{logsOpen ? '▲ collapse' : '▼ expand'}</span>
                </button>

                {logsOpen && (
                    <div className="bg-[#0d1117] max-h-80 overflow-y-auto font-mono text-xs leading-relaxed p-3 space-y-px scroll-smooth">
                        {logs.length === 0 && (
                            <div className="text-gray-600 py-4 text-center">Waiting for pipeline to start...</div>
                        )}
                        {logs.map((entry, i) => (
                            <div key={i} className={`flex gap-2 ${logLevelColor(entry.level)} hover:bg-white/5 px-1 rounded`}>
                                <span className="text-gray-600 shrink-0 select-none">{entry.ts}</span>
                                <span className={`shrink-0 select-none ${entry.level === 'error' ? 'text-red-500' : entry.level === 'success' ? 'text-emerald-500' : 'text-gray-600'}`}>
                                    {logLevelBadge(entry.level)}
                                </span>
                                <span className="break-all">{entry.log}</span>
                            </div>
                        ))}
                        <div ref={logEndRef} />
                    </div>
                )}
            </div>
        </div>
    )
}

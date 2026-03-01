import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ErrorBanner from '../components/ErrorBanner'

const GENRES = [
    { id: 'business', label: 'Business & Entrepreneurship', icon: '💼' },
    { id: 'self_improvement', label: 'Self-Improvement & Mindset', icon: '🧠' },
    { id: 'finance', label: 'Finance & Investing', icon: '📈' },
    { id: 'health', label: 'Health & Fitness', icon: '💪' },
    { id: 'relationships', label: 'Relationships & Dating', icon: '❤️' },
    { id: 'true_crime', label: 'True Crime & Storytelling', icon: '🎭' },
]

export default function InputPage() {
    const navigate = useNavigate()
    const fileRef = useRef(null)
    const [url, setUrl] = useState('')
    const [file, setFile] = useState(null)
    const [genre, setGenre] = useState('business')
    const [dragging, setDragging] = useState(false)
    const [error, setError] = useState(null)
    const [loading, setLoading] = useState(false)

    const hasInput = url.trim() || file
    const canSubmit = hasInput && genre && !loading

    const handleDrop = (e) => {
        e.preventDefault()
        setDragging(false)
        const dropped = e.dataTransfer.files[0]
        if (dropped) {
            const valid = ['.mp4', '.mov', '.mkv', '.avi', '.webm']
            if (valid.some(ext => dropped.name.toLowerCase().endsWith(ext))) {
                setFile(dropped)
                setUrl('')
            } else {
                setError({ message: `Unsupported format. Use: ${valid.join(', ')}` })
            }
        }
    }

    const handleSubmit = async () => {
        setLoading(true)
        setError(null)

        try {
            const formData = new FormData()
            if (file) {
                formData.append('file', file)
            } else {
                formData.append('url', url)
            }
            formData.append('genre', genre)

            const res = await fetch('/api/projects', { method: 'POST', body: formData })
            if (!res.ok) {
                const data = await res.json()
                throw new Error(data.detail || 'Failed to create project')
            }

            const { project_id } = await res.json()
            navigate(`/project/${project_id}/transcribing`)
        } catch (e) {
            setError({ message: e.message })
            setLoading(false)
        }
    }

    return (
        <div className="max-w-2xl mx-auto mt-12 space-y-8 animate-in fade-in">
            <div className="text-center space-y-2">
                <h1 className="text-3xl font-bold">Drop a video or paste a URL</h1>
                <p className="text-[var(--color-text-secondary)]">We'll find the best clips and make them viral-ready</p>
            </div>

            <ErrorBanner error={error} onRetry={() => setError(null)} />

            {/* File Drop Zone */}
            <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
                className={`relative border-2 border-dashed rounded-2xl p-12 text-center cursor-pointer transition-all duration-200 ${dragging
                        ? 'border-[var(--color-accent)] bg-[var(--color-accent)]/5'
                        : file
                            ? 'border-[var(--color-success)] bg-[var(--color-success)]/5'
                            : 'border-[var(--color-border)] hover:border-[var(--color-border-light)] hover:bg-[var(--color-bg-hover)]'
                    }`}
            >
                <input
                    ref={fileRef}
                    type="file"
                    accept=".mp4,.mov,.mkv,.avi,.webm"
                    className="hidden"
                    onChange={(e) => { setFile(e.target.files[0]); setUrl('') }}
                />
                {file ? (
                    <div className="space-y-2">
                        <div className="text-3xl">✓</div>
                        <div className="font-medium">{file.name}</div>
                        <div className="text-sm text-[var(--color-text-muted)]">{(file.size / 1024 / 1024).toFixed(0)} MB</div>
                    </div>
                ) : (
                    <div className="space-y-2">
                        <div className="text-3xl opacity-40">↑</div>
                        <div className="font-medium text-[var(--color-text-secondary)]">Drop MP4, MOV, MKV here</div>
                        <div className="text-sm text-[var(--color-text-muted)]">or click to browse</div>
                    </div>
                )}
            </div>

            {/* Divider */}
            <div className="flex items-center gap-4">
                <div className="flex-1 h-px bg-[var(--color-border)]" />
                <span className="text-sm text-[var(--color-text-muted)]">or</span>
                <div className="flex-1 h-px bg-[var(--color-border)]" />
            </div>

            {/* URL Input */}
            <input
                type="url"
                placeholder="https://youtube.com/watch?v=..."
                value={url}
                onChange={(e) => { setUrl(e.target.value); setFile(null) }}
                className="w-full px-4 py-3 rounded-xl bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:border-[var(--color-accent)] focus:outline-none transition-colors"
            />

            {/* Genre Selector */}
            <div className="space-y-3">
                <label className="text-sm font-medium text-[var(--color-text-secondary)]">Genre</label>
                <div className="grid grid-cols-2 gap-2">
                    {GENRES.map(g => (
                        <button
                            key={g.id}
                            onClick={() => setGenre(g.id)}
                            className={`flex items-center gap-2 px-4 py-3 rounded-xl text-left text-sm transition-all duration-200 ${genre === g.id
                                    ? 'bg-[var(--color-accent)]/15 border border-[var(--color-accent)]/40 text-[var(--color-text-primary)]'
                                    : 'bg-[var(--color-bg-card)] border border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
                                }`}
                        >
                            <span>{g.icon}</span>
                            <span>{g.label}</span>
                        </button>
                    ))}
                </div>
            </div>

            {/* Submit Button */}
            <button
                onClick={handleSubmit}
                disabled={!canSubmit}
                className="w-full py-4 rounded-xl font-semibold text-base transition-all duration-200 bg-gradient-to-r from-[var(--color-accent)] to-[var(--color-accent-light)] text-white hover:shadow-lg hover:shadow-[var(--color-accent)]/25 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:shadow-none"
            >
                {loading ? (
                    <span className="flex items-center justify-center gap-2">
                        <span className="animate-spin">↻</span> Creating project...
                    </span>
                ) : (
                    'Start Processing'
                )}
            </button>
        </div>
    )
}

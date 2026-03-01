import { createContext, useContext, useReducer } from 'react'

const ProjectContext = createContext(null)

const initialState = {
    currentProject: null,
    clips: [],
    decisions: {},
    styles: {},
    trims: {},
    filter: 'all',
    history: [],
}

function projectReducer(state, action) {
    switch (action.type) {
        case 'SET_PROJECT':
            return { ...state, currentProject: action.project }

        case 'LOAD_CLIPS':
            return {
                ...state,
                clips: action.clips,
                decisions: Object.fromEntries(action.clips.map(c => [c.rank, null])),
                styles: Object.fromEntries(action.clips.map(c => [c.rank, 'hormozi'])),
                trims: Object.fromEntries(action.clips.map(c => [c.rank, { start: 0, end: 0 }])),
            }

        case 'APPROVE_CLIP':
            return { ...state, decisions: { ...state.decisions, [action.clipId]: 'approved' } }

        case 'REJECT_CLIP':
            return { ...state, decisions: { ...state.decisions, [action.clipId]: 'rejected' } }

        case 'SET_STYLE':
            return { ...state, styles: { ...state.styles, [action.clipId]: action.style } }

        case 'SET_TRIM':
            return { ...state, trims: { ...state.trims, [action.clipId]: action.trim } }

        case 'SET_FILTER':
            return { ...state, filter: action.filter }

        case 'SET_HISTORY':
            return { ...state, history: action.history }

        case 'RESET':
            return { ...initialState, history: state.history }

        default:
            return state
    }
}

export function ProjectProvider({ children }) {
    const [state, dispatch] = useReducer(projectReducer, initialState)
    return (
        <ProjectContext.Provider value={{ state, dispatch }}>
            {children}
        </ProjectContext.Provider>
    )
}

export function useProject() {
    const ctx = useContext(ProjectContext)
    if (!ctx) throw new Error('useProject must be used within ProjectProvider')
    return ctx
}

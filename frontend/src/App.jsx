import { Routes, Route, Navigate } from 'react-router-dom'
import { ProjectProvider } from './context/ProjectContext'
import Layout from './components/Layout'
import InputPage from './pages/InputPage'
import TranscribingPage from './pages/TranscribingPage'
import ClipReviewPage from './pages/ClipReviewPage'
import ProcessingPage from './pages/ProcessingPage'
import ExportPage from './pages/ExportPage'

export default function App() {
  return (
    <ProjectProvider>
      <Layout>
        <Routes>
          <Route path="/" element={<InputPage />} />
          <Route path="/project/:projectId/transcribing" element={<TranscribingPage />} />
          <Route path="/project/:projectId/review" element={<ClipReviewPage />} />
          <Route path="/project/:projectId/processing" element={<ProcessingPage />} />
          <Route path="/project/:projectId/export" element={<ExportPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </ProjectProvider>
  )
}

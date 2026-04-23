import type { Metadata } from 'next'
import './globals.css'
import Sidebar from '@/components/Sidebar/Sidebar'
import { ErrorBoundary } from '@/components/ErrorBoundary'

export const metadata: Metadata = {
  title: 'RAG Dev Assistant',
  description: 'Семантический поиск по IT-проектам',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <div className="app-shell">
          <Sidebar />
          <main className="main-content">
            <ErrorBoundary>
              {children}
            </ErrorBoundary>
          </main>
        </div>
      </body>
    </html>
  )
}

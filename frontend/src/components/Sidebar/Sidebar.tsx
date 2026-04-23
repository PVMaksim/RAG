'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { fetchHealth } from '@/lib/api'

const NAV = [
  { href: '/search',   icon: '🔍', label: 'Поиск'    },
  { href: '/projects', icon: '📁', label: 'Проекты'  },
  { href: '/graph',    icon: '🕸',  label: 'Граф'     },
  { href: '/settings', icon: '⚙',  label: 'Настройки'},
]

export default function Sidebar() {
  const pathname = usePathname()
  const [backendOk, setBackendOk] = useState<boolean | null>(null)

  useEffect(() => {
    fetchHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false))
  }, [])

  return (
    <aside style={{
      width: 'var(--sidebar-width)',
      borderRight: '1px solid var(--color-border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '16px 0',
      flexShrink: 0,
      background: 'var(--color-surface)',
    }}>
      {/* Логотип */}
      <div style={{ padding: '0 16px 20px', fontWeight: 500, fontSize: 13 }}>
        RAG Assistant
      </div>

      {/* Навигация */}
      <nav style={{ flex: 1 }}>
        {NAV.map(({ href, icon, label }) => {
          const active = pathname.startsWith(href)
          return (
            <Link key={href} href={href} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '9px 16px',
              fontSize: 13,
              color: active ? 'var(--color-accent)' : 'var(--color-text)',
              background: active ? 'var(--color-accent-light)' : 'transparent',
              borderRight: active ? '2px solid var(--color-accent)' : '2px solid transparent',
              textDecoration: 'none',
              transition: 'background 0.15s',
            }}>
              <span style={{ fontSize: 16, lineHeight: 1 }}>{icon}</span>
              {label}
            </Link>
          )
        })}
      </nav>

      {/* MCP статус */}
      <div style={{ padding: '12px 16px', borderTop: '1px solid var(--color-border)' }}>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
          Бэкенд
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
            background: backendOk === null ? '#888' : backendOk ? '#1d9e75' : '#d85a30',
          }} />
          <span style={{ color: 'var(--color-text-muted)' }}>
            {backendOk === null ? 'проверка...' : backendOk ? 'онлайн' : 'недоступен'}
          </span>
        </div>
      </div>
    </aside>
  )
}

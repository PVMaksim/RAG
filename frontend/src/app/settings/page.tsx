'use client'

import { useEffect, useState } from 'react'

export default function SettingsPage() {
  const [backendUrl, setBackendUrl] = useState('http://localhost:8080')
  const [saved, setSaved]           = useState(false)

  useEffect(() => {
    const stored = localStorage.getItem('backendUrl')
    if (stored) setBackendUrl(stored)
  }, [])

  const save = () => {
    localStorage.setItem('backendUrl', backendUrl)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div style={{ maxWidth: 600, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 24 }}>
      <h1 style={{ fontSize: 18, fontWeight: 500 }}>Настройки</h1>

      {/* Бэкенд URL */}
      <Section title="Бэкенд">
        <label style={labelStyle}>URL бэкенда</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            value={backendUrl}
            onChange={e => setBackendUrl(e.target.value)}
            style={inputStyle}
            placeholder="http://localhost:8080"
          />
          <button onClick={save} style={btnStyle}>
            {saved ? '✅ Сохранено' : 'Сохранить'}
          </button>
        </div>
        <p style={hintStyle}>
          Локально: http://localhost:8080 · VPS: https://rag.yourdomain.com
        </p>
      </Section>

      {/* API ключ — только через .env */}
      <Section title="Anthropic API Key">
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          API ключ задаётся через переменную окружения <code style={codeStyle}>ANTHROPIC_API_KEY</code> в файле <code style={codeStyle}>.env</code>.
          Это сделано намеренно — ключ никогда не попадает в браузер.
        </p>
        <div style={{
          marginTop: 10,
          padding: '10px 14px',
          background: 'var(--color-surface)',
          borderRadius: 7,
          border: '1px solid var(--color-border)',
          fontSize: 12,
          fontFamily: 'monospace',
          color: 'var(--color-text)',
        }}>
          # .env<br />
          ANTHROPIC_API_KEY=sk-ant-...
        </div>
      </Section>

      {/* MCP аутентификация */}
      <Section title="MCP API ключ (для VPS)">
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
          При деплое на VPS задай случайный токен чтобы закрыть MCP сервер от публичного доступа.
          Локально можно оставить пустым.
        </p>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <code style={{ ...codeStyle, flex: 1, padding: '7px 10px', display: 'block' }}>
            openssl rand -hex 32
          </code>
        </div>
        <p style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          Добавь результат в <code style={codeStyle}>.env</code> как{' '}
          <code style={codeStyle}>MCP_API_KEY=&lt;токен&gt;</code>,
          затем укажи токен в конфиге MCP-клиента.
        </p>
      </Section>

      {/* MCP подключение */}
      <Section title="MCP — подключение AI-ассистентов">
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
          MCP сервер позволяет Claude Desktop, Cursor и Windsurf искать по твоим проектам
          без загрузки кода в контекст. Экономия до 95% токенов.
        </p>

        <label style={labelStyle}>Claude Desktop</label>
        <pre style={codeBlockStyle}>{`# ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "rag-dev-assistant": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:27183/mcp/sse"]
    }
  }
}`}</pre>

        <label style={{ ...labelStyle, marginTop: 14 }}>Cursor / Windsurf (с токеном)</label>
        <pre style={codeBlockStyle}>{`# .cursor/mcp.json (в папке проекта)
{
  "mcpServers": {
    "rag": {
      "url": "http://localhost:27183/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_API_KEY"
      }
    }
  }
}`}</pre>

        <p style={{ ...hintStyle, marginTop: 10 }}>
          На VPS замени localhost:27183 на https://rag.yourdomain.com
        </p>
      </Section>

      {/* GitHub Webhook */}
      <Section title="GitHub Webhook (автообновление)">
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12, lineHeight: 1.6 }}>
          При каждом push в GitHub проект автоматически обновляется и переиндексируется.
        </p>

        <label style={labelStyle}>Webhook URL</label>
        <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
          <code style={{ ...codeStyle, flex: 1, padding: '7px 10px', display: 'block', fontSize: 12 }}>
            {backendUrl.replace('http://localhost:8080', 'https://rag.yourdomain.com')}/api/webhook/github
          </code>
          <button
            onClick={() => {
              navigator.clipboard.writeText(
                `${backendUrl.replace('http://localhost:8080', 'https://rag.yourdomain.com')}/api/webhook/github`
              )
            }}
            style={{ ...inputStyle, flex: '0 0 auto', cursor: 'pointer', padding: '7px 12px' }}
          >
            📋
          </button>
        </div>

        <label style={labelStyle}>Настройка секрета</label>
        <pre style={codeBlockStyle}>{`# 1. Сгенерируй секрет:
openssl rand -hex 32

# 2. Добавь в .env:
WEBHOOK_SECRET=<твой_секрет>

# 3. GitHub → repo → Settings → Webhooks → Add webhook:
#    Payload URL: https://rag.yourdomain.com/api/webhook/github
#    Content type: application/json
#    Secret: <тот_же_секрет>
#    Events: Just the push event`}</pre>
      </Section>

      {/* Советы */}
      <Section title="Быстрый старт">
        <ol style={{ fontSize: 13, lineHeight: 2, color: 'var(--color-text)', paddingLeft: 18 }}>
          <li>Скопируй <code style={codeStyle}>.env.example</code> в <code style={codeStyle}>.env</code> и добавь ANTHROPIC_API_KEY</li>
          <li>Запусти: <code style={codeStyle}>docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --build</code></li>
          <li>Перейди в <strong>Проекты</strong> → добавь папку с проектом</li>
          <li>Дождись сканирования → нажми «Построить граф знаний» (опционально)</li>
          <li>Перейди в <strong>Поиск</strong> и задай вопрос</li>
        </ol>
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      border: '1px solid var(--color-border)',
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '10px 16px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
        fontWeight: 500,
        fontSize: 13,
      }}>
        {title}
      </div>
      <div style={{ padding: 16 }}>{children}</div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 12,
  color: 'var(--color-text-muted)',
  marginBottom: 6,
  fontWeight: 500,
}
const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: '7px 10px',
  borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-text)',
  fontSize: 13,
}
const btnStyle: React.CSSProperties = {
  padding: '7px 14px',
  borderRadius: 6,
  border: 'none',
  background: 'var(--color-accent)',
  color: '#fff',
  fontSize: 13,
  cursor: 'pointer',
  flexShrink: 0,
}
const hintStyle: React.CSSProperties = {
  fontSize: 11,
  color: 'var(--color-text-muted)',
  marginTop: 6,
}
const codeStyle: React.CSSProperties = {
  fontFamily: 'monospace',
  background: 'var(--color-surface)',
  padding: '1px 5px',
  borderRadius: 3,
  fontSize: 12,
}
const codeBlockStyle: React.CSSProperties = {
  padding: '12px 14px',
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 7,
  fontSize: 12,
  fontFamily: 'monospace',
  lineHeight: 1.6,
  whiteSpace: 'pre-wrap',
  color: 'var(--color-text)',
}

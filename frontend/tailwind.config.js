/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  // Отключаем preflight — используем собственные CSS переменные
  // чтобы не конфликтовали с var(--color-*) из globals.css
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        accent: 'var(--color-accent)',
        'accent-light': 'var(--color-accent-light)',
        surface: 'var(--color-surface)',
        border: 'var(--color-border)',
        muted: 'var(--color-text-muted)',
      },
    },
  },
  plugins: [],
}

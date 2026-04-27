// src/lib/styles.ts
export type CssVar = `var(--${string})`

export function css<T extends React.CSSProperties>(styles: T): T {
  return styles
}
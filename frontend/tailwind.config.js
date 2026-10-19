/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Outfit', 'Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      colors: {
        space: { 900: '#05060f', 800: '#0a0e1f', 700: '#111634', 600: '#1b2350' },
        muted: '#8a97c2',
        glow: { cyan: '#38e1ff', violet: '#8b5cf6', lime: '#a3e635' },
      },
      boxShadow: { glow: '0 0 20px rgba(56,225,255,0.35)' },
    },
  },
  plugins: [],
}

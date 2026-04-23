/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ed: {
          bg: 'var(--bg)',
          'bg-soft': 'var(--bg-soft)',
          text: 'var(--text)',
          muted: 'var(--muted)',
          accent: 'var(--accent)',
          'accent-soft': 'var(--accent-soft)',
          line: 'var(--line)',
          'line-strong': 'var(--line-strong)',
          panel: 'var(--panel)',
          'panel-strong': 'var(--panel-strong)',
          success: 'var(--success)',
          'success-soft': 'var(--success-soft)',
          danger: 'var(--danger)',
          'danger-soft': 'var(--danger-soft)',
          warning: 'var(--warning)',
          'warning-soft': 'var(--warning-soft)',
          info: 'var(--info)',
          'info-soft': 'var(--info-soft)',
          purple: 'var(--purple)',
          'purple-soft': 'var(--purple-soft)',
          surface: 'var(--surface)',
          'surface-hover': 'var(--surface-hover)',
          overlay: 'var(--overlay)',
        },
      },
      borderRadius: {
        'ed-sm': 'var(--radius-sm)',
        'ed-md': 'var(--radius-md)',
        'ed-lg': 'var(--radius-lg)',
        'ed-xl': 'var(--radius-xl)',
      },
      maxWidth: {
        'main': '1920px',
      },
      zIndex: {
        'header': '40',
        'filter': '30',
        'overlay': '50',
      },
    },
  },
  plugins: [],
}

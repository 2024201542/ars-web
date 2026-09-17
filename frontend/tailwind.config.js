/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'ruc': {
          // ── 人大红主色系 ──
          'red':        '#be282d',   // 主色
          'red-light':  '#d94045',   // hover
          'red-dark':   '#9a1f24',   // pressed / active
          'red-pale':   '#fef5f5',   // 极浅红底 (5%)
          'red-soft':   '#fbe8e8',   // 浅红底 (10%)

          // ── 暖白/灰中性基底 ──
          'bg':         '#f7f5f2',   // 页面底色 暖米白
          'card':       '#ffffff',   // 卡片 / 输入框
          'card-hover': '#faf8f5',   // 卡片 hover

          // ── 文字层级 ──
          'text':       '#1c1917',   // 主文字 深灰棕
          'text-dim':   '#6b6560',   // 次要文字
          'text-light': '#a39d98',   // 提示/占位

          // ── 边框 / 分割 ──
          'border':     '#e1dcd6',   // 可见边框
          'border-light':'#ede8e2',  // 微边框
          'divider':    '#f0ece6',   // 分割线

          // ── 强调 / 装饰 ──
          'gold':       '#c8a96e',   // 学术金色点缀
          'gold-light': '#e0cfa0',   // gold hover
          'warm':       '#f5efe5',   // 暖色强调底

          // ── 功能色 ──
          'error':      '#dc2626',
          'error-soft': '#fef2f2',
          'success':    '#059669',
          'success-soft':'#ecfdf5',
        },
      },
      fontFamily: {
        'display': ['"Crimson Text"', 'Georgia', 'serif'],
        'body':    ['"Source Serif 4"', 'Georgia', 'serif'],
        'ui':      ['Inter', '-apple-system', 'sans-serif'],
        'mono':    ['"JetBrains Mono"', '"Fira Code"', 'monospace'],
      },
      borderRadius: {
        'xs':  '4px',
        'sm':  '6px',
        'md':  '8px',
        'lg':  '12px',
        'xl':  '16px',
        '2xl': '20px',
      },
      boxShadow: {
        'card':     '0 1px 3px 0 rgba(0,0,0,0.04), 0 1px 2px -1px rgba(0,0,0,0.03)',
        'elevated': '0 4px 12px -2px rgba(0,0,0,0.08), 0 2px 4px -2px rgba(0,0,0,0.04)',
        'modal':    '0 20px 60px -12px rgba(0,0,0,0.15), 0 8px 16px -8px rgba(0,0,0,0.08)',
        'glow':     '0 0 0 3px rgba(190,40,45,0.15)',
        'glow-sm':  '0 0 0 2px rgba(190,40,45,0.10)',
      },
      ringWidth: {
        DEFAULT: '2px',
      },
      animation: {
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
        'fade-in':    'fadeIn 0.2s ease-out',
        'slide-up':   'slideUp 0.25s ease-out',
      },
      keyframes: {
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
        'fadeIn': {
          '0%':   { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'slideUp': {
          '0%':   { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Freebuff-style near-black canvas, violet -> cyan brand ramp.
        ink: {
          950: '#07070d',
          900: '#0b0b14',
          850: '#101019',
          800: '#15151f',
          700: '#1d1d2b',
        },
        brand: {
          50: '#f2f0ff',
          100: '#e6e1ff',
          200: '#cfc5ff',
          300: '#b3a2ff',
          400: '#a78bfa',
          500: '#7c5cff',
          600: '#6d46f5',
          700: '#5b34d8',
          800: '#4a2bb0',
          900: '#3d268c',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 12px 40px -12px rgba(124,92,255,0.65)',
        panel: '0 24px 70px -30px rgba(0,0,0,0.85)',
      },
      transitionTimingFunction: {
        swift: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
    },
  },
  plugins: [],
};

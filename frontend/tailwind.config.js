/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // Walmart brand palette (public)
        walmart: {
          navy: '#041E42',
          blue: '#0071DC',
          spark: '#FFC220',
          sky: '#4DBDF5',
          'navy-light': '#0A2A57',
          'blue-light': '#3A93E8',
          'spark-dark': '#E0A800',
        },
        surface: '#FFFFFF',
        'bg-base': '#F2F8FD',
        sentiment: {
          positive: '#00865A',
          negative: '#DE1C24',
          neutral: '#74767C',
        },
        // Back-compat alias so unmigrated `brand-*` classes still resolve
        brand: {
          50: '#EAF3FB',
          100: '#D5E7F7',
          500: '#0071DC',
          600: '#005FB8',
          700: '#041E42',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
      },
      borderRadius: {
        pill: '9999px',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgba(4, 30, 66, 0.04), 0 4px 12px -2px rgba(4, 30, 66, 0.06)',
        'card-hover': '0 4px 8px 0 rgba(4, 30, 66, 0.06), 0 12px 24px -4px rgba(4, 30, 66, 0.10)',
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        card: 'hsl(var(--card))',
        border: 'hsl(var(--border))',
        primary: 'hsl(var(--primary))',
        'primary-foreground': 'hsl(var(--primary-foreground))',
        secondary: 'hsl(var(--secondary))',
        'secondary-foreground': 'hsl(var(--secondary-foreground))',
        muted: 'hsl(var(--muted))',
        'muted-foreground': 'hsl(var(--muted-foreground))',
        accent: 'hsl(var(--accent))',
        destructive: 'hsl(var(--destructive))',
        ring: 'hsl(var(--ring))',
        'stage-new': 'hsl(var(--stage-new))',
        'stage-qualified': 'hsl(var(--stage-qualified))',
        'stage-hesitant': 'hsl(var(--stage-hesitant))',
        'stage-link-sent': 'hsl(var(--stage-link-sent))',
        'stage-deposited': 'hsl(var(--stage-deposited))'
      }
    }
  },
  plugins: []
}

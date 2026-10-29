module.exports = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            obsidian: {
              950: '#07090e',
              900: '#0c1017',
              850: '#111722',
              800: '#171f2e',
              700: '#222d42',
              600: '#33415c'
            },
            cyan: {
              accent: '#00f0ff',
              muted: 'rgba(0, 240, 255, 0.15)',
              glow: 'rgba(0, 240, 255, 0.4)'
            },
            violet: {
              accent: '#8b5cf6',
              muted: 'rgba(139, 92, 246, 0.15)',
              glow: 'rgba(139, 92, 246, 0.4)'
            }
          },
          fontFamily: {
            sans: ['Inter', 'sans-serif'],
            mono: ['JetBrains Mono', 'monospace'],
            tech: ['Space Grotesk', 'sans-serif']
          },
          boxShadow: {
            'cyan-glow': '0 0 25px -5px rgba(0, 240, 255, 0.3)',
            'violet-glow': '0 0 25px -5px rgba(139, 92, 246, 0.3)',
            'dual-glow': '0 0 35px -5px rgba(0, 240, 255, 0.25), 0 0 35px -5px rgba(139, 92, 246, 0.25)'
          },
          animation: {
            'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            'scanline': 'scanline 8s linear infinite'
          },
          keyframes: {
            scanline: {
              '0%': { transform: 'translateY(-100%)' },
              '100%': { transform: 'translateY(1000%)' }
            }
          }
        }
      }
    };
module.exports.content = ['./index.html'];

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        wa: {
          bg: "#0b141a",
          panel: "#111b21",
          panel2: "#202c33",
          text: "#e9edef",
          muted: "#8696a0",
          green: "#00a884",
          bubbleMe: "#005c4b",
          bubbleThem: "#202c33"
        }
      }
    }
  },
  plugins: []
};

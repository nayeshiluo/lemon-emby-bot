module.exports = {
  content: ["./web/static/**/*.html", "./web/static/**/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309"
        },
        dark: {
          900: "#0f172a",
          800: "#1e293b",
          700: "#334155"
        }
      }
    }
  },
  plugins: []
};

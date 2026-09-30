const fs = require("node:fs");
const path = require("node:path");

function copy(source, target) {
  if (!fs.existsSync(source)) {
    throw new Error("Missing vendor file: " + source);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}

function copyFirst(sources, target) {
  const source = sources.find((candidate) => fs.existsSync(candidate));
  if (!source) {
    throw new Error("Missing vendor license: " + sources.join(", "));
  }
  copy(source, target);
}

copy("node_modules/vue/dist/vue.global.prod.js", "web/static/vendor/vue.global.prod.js");
copy("node_modules/@fortawesome/fontawesome-free/css/all.min.css", "web/static/vendor/fontawesome/css/all.min.css");
copy("node_modules/@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2", "web/static/vendor/fontawesome/webfonts/fa-solid-900.woff2");
copyFirst(["node_modules/vue/LICENSE"], "web/static/vendor/licenses/vue-MIT.txt");
copyFirst(["node_modules/tailwindcss/LICENSE"], "web/static/vendor/licenses/tailwindcss-MIT.txt");
copyFirst(["node_modules/@fortawesome/fontawesome-free/LICENSE.txt", "node_modules/@fortawesome/fontawesome-free/LICENSE"], "web/static/vendor/licenses/fontawesome-free.txt");

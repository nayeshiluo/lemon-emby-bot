const fs = require("node:fs");
const path = require("node:path");
const { compile } = require("@vue/compiler-dom");

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

const template = fs.readFileSync("web/src/admin-template.html", "utf8");
const compiled = compile(template, { mode: "function", prefixIdentifiers: true });
if (compiled.errors && compiled.errors.length) {
  throw new Error("Vue template compilation failed: " + JSON.stringify(compiled.errors));
}
const renderModule =
  "window.LemonAdminRender = (function (Vue) {\n" +
  compiled.code +
  "\n})(Vue);\n";
fs.writeFileSync("web/static/app-template.js", renderModule);

copy("node_modules/vue/dist/vue.runtime.global.prod.js", "web/static/vendor/vue.runtime.global.prod.js");
fs.rmSync("web/static/vendor/vue.global.prod.js", { force: true });
copy("node_modules/@fortawesome/fontawesome-free/css/all.min.css", "web/static/vendor/fontawesome/css/all.min.css");
copy("node_modules/@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2", "web/static/vendor/fontawesome/webfonts/fa-solid-900.woff2");
copyFirst(["node_modules/vue/LICENSE"], "web/static/vendor/licenses/vue-MIT.txt");
copyFirst(["node_modules/tailwindcss/LICENSE"], "web/static/vendor/licenses/tailwindcss-MIT.txt");
copyFirst(["node_modules/@fortawesome/fontawesome-free/LICENSE.txt", "node_modules/@fortawesome/fontawesome-free/LICENSE"], "web/static/vendor/licenses/fontawesome-free.txt");

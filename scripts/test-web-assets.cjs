const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const index = fs.readFileSync("web/static/index.html", "utf8");
const runtimePath = "web/static/vendor/vue.runtime.global.prod.js";
const renderPath = "web/static/app-template.js";
const runtimeSource = fs.readFileSync(runtimePath, "utf8");
const renderSource = fs.readFileSync(renderPath, "utf8");

assert.match(index, /vue\.runtime\.global\.prod\.js/);
assert.match(index, /\/static\/app-template\.js/);
assert.doesNotMatch(index, /\/static\/vendor\/vue\.global\.prod\.js/);
assert.doesNotMatch(runtimeSource, /\bnew Function\b|\beval\s*\(/);
assert.doesNotMatch(renderSource, /\bnew Function\b|\beval\s*\(/);

const sandbox = { console };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(runtimeSource, sandbox, { filename: runtimePath });
assert.equal(sandbox.Vue.version, "3.5.43");
vm.runInContext(renderSource, sandbox, { filename: renderPath });
assert.equal(typeof sandbox.LemonAdminRender, "function");

const state = {
  stats: {
    total_users: 2,
    active_sessions: 1,
    server_info: { ServerName: "Test Emby", Version: "1" },
    sessions: [{
      Id: "session-1",
      UserName: "Alice",
      DeviceName: "iPhone",
      Client: "iOS",
      NowPlayingItem: { Name: "Test Movie" },
      RemoteEndPoint: "127.0.0.1"
    }]
  },
  users: [{
    tg_id: 123,
    emby_username: "test-user",
    expiry_date: "2026-10-01T12:00:00",
    max_devices: 3,
    is_disabled: false
  }],
  token: "",
  genForm: { value: 30, count: 5 },
  generatedCodes: ["TEST-CODE"],
  fetchData() {},
  generateCodes() {},
  killSession() {}
};
const tree = sandbox.LemonAdminRender(state, []);
const text = [];
function collect(node) {
  if (node == null) return;
  if (typeof node === "string" || typeof node === "number") {
    text.push(String(node));
    return;
  }
  if (Array.isArray(node)) {
    for (const child of node) collect(child);
    return;
  }
  if (node.children) collect(node.children);
}
collect(tree);
const renderedText = text.join(" ");
for (const expected of ["Lemon Emby Control Panel", "Test Emby", "Alice", "test-user", "Test Movie"]) {
  assert.ok(renderedText.includes(expected), "render output missing " + expected);
}
console.log("Vue runtime-only precompiled render smoke test passed.");

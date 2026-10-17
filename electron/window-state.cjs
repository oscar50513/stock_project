const fs = require("fs");
const path = require("path");

const DEFAULT_STATE = {
  width: 1440,
  height: 920,
  isMaximized: false,
};

function stateFilePath(app) {
  return path.join(app.getPath("userData"), "window-state.json");
}

function load(app) {
  try {
    const file = stateFilePath(app);
    if (fs.existsSync(file)) {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      return {
        width: Math.max(1024, Number(data.width) || DEFAULT_STATE.width),
        height: Math.max(700, Number(data.height) || DEFAULT_STATE.height),
        x: typeof data.x === "number" ? data.x : undefined,
        y: typeof data.y === "number" ? data.y : undefined,
        isMaximized: Boolean(data.isMaximized),
      };
    }
  } catch (_) {
    // Ignore corrupted state file
  }
  return { ...DEFAULT_STATE };
}

function save(app, win) {
  if (!win || win.isDestroyed()) return;
  try {
    const bounds = win.getBounds();
    const state = {
      width: bounds.width,
      height: bounds.height,
      x: bounds.x,
      y: bounds.y,
      isMaximized: win.isMaximized(),
    };
    fs.mkdirSync(app.getPath("userData"), { recursive: true });
    fs.writeFileSync(stateFilePath(app), JSON.stringify(state, null, 2), "utf8");
  } catch (_) {
    // Ignore write errors
  }
}

module.exports = { load, save };

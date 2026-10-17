const { app, BrowserWindow, dialog, Menu, shell } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const http = require("http");
const net = require("net");
const os = require("os");
const path = require("path");
const windowState = require("./window-state.cjs");

const FALLBACK_PROJECT_ROOT = "/Users/zyxu/Desktop/zyxu/stock_project";

let backendProcess = null;
let backendReadyPromise = null;
let backendUrl = null;
let mainWindow = null;
let quitting = false;

function resolveProjectRoot() {
  const localCandidate = path.resolve(__dirname, "..");
  if (fs.existsSync(path.join(localCandidate, "streamlit_app.py"))) {
    return localCandidate;
  }
  if (fs.existsSync(path.join(FALLBACK_PROJECT_ROOT, "streamlit_app.py"))) {
    return FALLBACK_PROJECT_ROOT;
  }
  return localCandidate;
}

function resolvePythonBin(root) {
  const venvPy =
    process.platform === "win32"
      ? path.join(root, ".venv", "Scripts", "python.exe")
      : path.join(root, ".venv", "bin", "python");
  if (fs.existsSync(venvPy)) {
    return venvPy;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const address = srv.address();
      const port = address && typeof address === "object" ? address.port : 8518;
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

function checkHealth(url) {
  return new Promise((resolve) => {
    const req = http.get(`${url}/_stcore/health`, { timeout: 1200 }, (res) => {
      let body = "";
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        resolve(res.statusCode === 200 && body.trim() === "ok");
      });
    });
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

function buildEnhancedEnv() {
  const env = { ...process.env, PYTHONUTF8: "1", PYTHONUNBUFFERED: "1" };
  if (process.platform !== "win32") {
    const extraPaths = [
      path.join(os.homedir(), ".local", "bin"),
      "/opt/homebrew/bin",
      "/usr/local/bin",
      "/usr/bin",
      "/bin",
    ];
    env.PATH = [
      ...new Set([
        ...(env.PATH || "").split(":"),
        ...extraPaths.filter((p) => fs.existsSync(p)),
      ]),
    ]
      .filter(Boolean)
      .join(":");
  }
  return env;
}

function startBackend() {
  if (backendReadyPromise) return backendReadyPromise;

  backendReadyPromise = (async () => {
    const root = resolveProjectRoot();
    const python = resolvePythonBin(root);
    const appScript = path.join(root, "streamlit_app.py");

    if (!fs.existsSync(appScript)) {
      throw new Error(`找不到主程式檔案：${appScript}`);
    }

    const port = await findFreePort();
    const targetUrl = `http://127.0.0.1:${port}`;
    const env = buildEnhancedEnv();

    const args = [
      "-m",
      "streamlit",
      "run",
      appScript,
      "--server.port",
      String(port),
      "--server.address",
      "127.0.0.1",
      "--server.headless",
      "true",
      "--browser.gatherUsageStats",
      "false",
      "--client.toolbarMode",
      "minimal",
    ];

    let logOutput = "";
    backendProcess = spawn(python, args, {
      cwd: root,
      env,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });

    backendProcess.stdout.on("data", (chunk) => {
      logOutput = (logOutput + chunk.toString()).slice(-16384);
    });
    backendProcess.stderr.on("data", (chunk) => {
      logOutput = (logOutput + chunk.toString()).slice(-16384);
    });

    backendProcess.once("exit", (code, signal) => {
      backendProcess = null;
      backendReadyPromise = null;
      backendUrl = null;
      if (!quitting && mainWindow && !mainWindow.isDestroyed()) {
        console.warn(`Backend exited unexpectedly (code=${code}, signal=${signal})`);
      }
    });

    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (quitting) throw new Error("啟動已取消");
      if (!backendProcess) {
        throw new Error(`Python 後端異常退出：\n${logOutput.slice(-600)}`);
      }
      const healthy = await checkHealth(targetUrl);
      if (healthy) {
        backendUrl = targetUrl;
        return targetUrl;
      }
      await new Promise((r) => setTimeout(r, 250));
    }

    throw new Error(`量化引擎啟動超時（30 秒）：\n${logOutput.slice(-600)}`);
  })();

  backendReadyPromise.catch(() => {
    backendReadyPromise = null;
  });

  return backendReadyPromise;
}

function stopBackend() {
  if (!backendProcess) return;
  try {
    backendProcess.kill("SIGTERM");
  } catch (_) {
    // Ignore kill error
  }
  backendProcess = null;
  backendReadyPromise = null;
  backendUrl = null;
}

function runDailyDiscordPush() {
  const root = resolveProjectRoot();
  const python = resolvePythonBin(root);
  const script = path.join(root, "daily_report.py");

  const proc = spawn(python, [script, "--no-update", "--force"], {
    cwd: root,
    env: buildEnhancedEnv(),
  });

  let out = "";
  proc.stdout.on("data", (c) => (out += c.toString()));
  proc.stderr.on("data", (c) => (out += c.toString()));
  proc.on("close", (code) => {
    if (code === 0) {
      dialog.showMessageBox(mainWindow, {
        type: "info",
        title: "Discord 訊號推播成功",
        message: "已成功將最新收盤技術訊號雷達推播至您的 Discord 頻道！",
        detail: out.trim().slice(-400),
      });
    } else {
      dialog.showErrorBox("Discord 推播失敗", out.trim().slice(-600) || `Exit code ${code}`);
    }
  });
}

function buildMenu() {
  const template = [
    {
      label: app.name,
      submenu: [
        { role: "about", label: "關於 StockRadar 台股量化工作站" },
        { type: "separator" },
        {
          label: "立即發送 Discord 收盤訊號報告",
          accelerator: "CmdOrCtrl+Shift+D",
          click: () => runDailyDiscordPush(),
        },
        {
          label: "開啟專案資料夾",
          click: () => shell.openPath(resolveProjectRoot()),
        },
        { type: "separator" },
        { role: "hide", label: "隱藏視窗" },
        { role: "hideOthers", label: "隱藏其他應用程式" },
        { role: "unhide", label: "顯示全部" },
        { type: "separator" },
        { role: "quit", label: "結束 StockRadar" },
      ],
    },
    {
      label: "編輯",
      submenu: [
        { role: "undo", label: "復原" },
        { role: "redo", label: "重做" },
        { type: "separator" },
        { role: "cut", label: "剪下" },
        { role: "copy", label: "複製" },
        { role: "paste", label: "貼上" },
        { role: "selectAll", label: "全選" },
      ],
    },
    {
      label: "檢視",
      submenu: [
        {
          label: "重新整理面板",
          accelerator: "CmdOrCtrl+R",
          click: () => {
            if (mainWindow && !mainWindow.isDestroyed()) {
              mainWindow.webContents.reload();
            }
          },
        },
        { type: "separator" },
        { role: "resetZoom", label: "實際大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "縮小" },
        { type: "separator" },
        { role: "togglefullscreen", label: "切換全螢幕" },
        { role: "toggleDevTools", label: "開發者工具" },
      ],
    },
    {
      label: "視窗",
      submenu: [
        { role: "minimize", label: "最小化" },
        { role: "zoom", label: "縮放" },
        { type: "separator" },
        { role: "front", label: "全部移至最前" },
        { role: "close", label: "關閉視窗" },
      ],
    },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createMainWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
    return;
  }

  const saved = windowState.load(app);
  const iconPath = path.join(__dirname, "icon.png");

  mainWindow = new BrowserWindow({
    width: saved.width,
    height: saved.height,
    x: saved.x,
    y: saved.y,
    minWidth: 1080,
    minHeight: 700,
    title: "StockRadar — 台股與主動式 ETF 量化分析工作站",
    backgroundColor: "#0b101b",
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  if (saved.isMaximized) {
    mainWindow.maximize();
  }

  // Open external links in default system browser instead of inside app window
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (backendUrl && url.startsWith(backendUrl)) {
      return { action: "allow" };
    }
    if (url.startsWith("http://") || url.startsWith("https://")) {
      shell.openExternal(url);
    }
    return { action: "deny" };
  });

  mainWindow.on("close", () => {
    windowState.save(app, mainWindow);
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  const splashPath = path.join(__dirname, "splash.html");
  await mainWindow.loadFile(splashPath);
  mainWindow.show();

  try {
    const url = await startBackend();
    if (mainWindow && !mainWindow.isDestroyed()) {
      await mainWindow.loadURL(url);
    }
  } catch (err) {
    dialog.showErrorBox(
      "StockRadar 後端啟動失敗",
      err && err.message ? err.message : String(err)
    );
  }
}

app.setName("StockRadar");

app.whenReady().then(async () => {
  const iconPath = path.join(__dirname, "icon.png");
  if (process.platform === "darwin" && app.dock && fs.existsSync(iconPath)) {
    try {
      app.dock.setIcon(iconPath);
    } catch (_) {}
  }

  buildMenu();
  await createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
});

app.on("before-quit", () => {
  quitting = true;
  if (mainWindow && !mainWindow.isDestroyed()) {
    windowState.save(app, mainWindow);
  }
  stopBackend();
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

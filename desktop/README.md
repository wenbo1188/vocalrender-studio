# VocalRender Studio · Windows 桌面版

桌面版用 [Electron](https://www.electronjs.org/) 打包，界面就是仓库根目录的 `index.html`，构建时自动复制进来，所以网页版和桌面版功能始终一致。桌面版另外提供：

- **Windows 11 外观**：Mica 背景、Segoe UI Variable 字体、跟随系统强调色和深浅色、标题栏与窗口一体（系统最小化/最大化/关闭按钮）。Windows 10 上自动改用纯色背景。
- **工程文件**：新建 / 打开 / 保存 / 另存为（`.vrproj`），标题栏显示文件名，有未保存更改时显示 ●，关闭窗口时提示保存。
- **双击打开**：安装版会关联 `.vrproj`，双击工程文件直接打开；也可以把文件拖进窗口。“打开”对话框和拖放同样接受 MusicXML（`.musicxml` / `.xml` / `.mxl`）、MIDI（`.mid` / `.midi` / `.kar`）和 JSON 乐谱，会进入导入流程。
- **导出 WAV**：48 kHz、16/24-bit，整首或当前乐句，可混入伴奏。
- **连接渲染服务**：请求从主进程发出，不受浏览器跨域（CORS）限制。
- **离线可用**：不加载任何在线资源，页面本身被 CSP 禁止访问网络。

## 生成 exe

需要一台 **Windows 10/11 x64** 电脑。

1. 安装 [Node.js](https://nodejs.org/) 20 或更新的 LTS 版本（安装时保持默认选项即可）。
2. 下载本仓库代码（`git clone`，或在 GitHub 上 Code → Download ZIP 后解压）。
3. 打开“终端”或 PowerShell，进入 `desktop` 目录，安装依赖：

   ```powershell
   cd vocalrender-studio\desktop
   npm install
   ```

4. 生成安装包和便携版：

   ```powershell
   npm run dist
   ```

完成后在 `desktop\dist\` 下得到两个文件（文件名里的版本号取自 `package.json`）：

| 文件 | 说明 |
|---|---|
| `VocalRender-Studio-1.0.1-Setup.exe` | 安装版：可选安装位置，创建开始菜单和桌面快捷方式，关联 `.vrproj` |
| `VocalRender-Studio-1.0.1-Portable.exe` | 便携版：单个 exe，双击直接运行，不写注册表 |

其他命令：

| 命令 | 作用 |
|---|---|
| `npm start` | 不打包，直接以开发模式运行（F12 打开开发者工具） |
| `npm run dist:setup` | 只生成安装版 |
| `npm run dist:portable` | 只生成便携版 |
| `npm run dist:dir` | 只生成未打包的程序目录 `dist\win-unpacked\`，最快，适合自测 |

修改了根目录的 `index.html` 后重新运行上面的命令即可，脚本会先同步最新页面（`npm run sync`）。

### 不想在本机构建：用 GitHub Actions

仓库里带了工作流 `.github/workflows/build-windows.yml`。在 GitHub 仓库页面打开 **Actions → Build Windows app → Run workflow**，几分钟后在这次运行的 **Artifacts** 里下载 `VocalRender-Studio-windows`，里面就是上面两个 exe。推送 `v*` 格式的标签（如 `v1.0.0`）也会自动触发。

## 常见问题

**`npm install` 很慢或下载 Electron 失败**：国内网络可以先设置镜像再安装：

```powershell
$env:ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
$env:ELECTRON_BUILDER_BINARIES_MIRROR="https://npmmirror.com/mirrors/electron-builder-binaries/"
npm install --registry=https://registry.npmmirror.com
npm run dist
```

**运行 exe 时出现“Windows 已保护你的电脑”**：exe 没有代码签名，SmartScreen 会提示。点“更多信息 → 仍要运行”即可。要去掉提示需要购买代码签名证书，并在 `package.json` 的 `build.win` 中配置签名。

**看不到 Mica 半透明效果**：Mica 需要 Windows 11 22H2 及以上，并且在“设置 → 个性化 → 颜色”中开启“透明效果”。

**改版本号或图标**：版本号在 `package.json` 的 `version`；图标是 `build/icon.ico`（多尺寸）和 `build/icon.png`（512×512），替换这两个文件后重新构建。

## 目录结构

```
desktop/
├─ main.js              主进程：窗口、Mica/标题栏、文件对话框、网络请求、关闭确认
├─ preload.js           向页面暴露 window.vrDesktop
├─ scripts/sync-web.js  把 ../index.html 复制到 app/，去掉在线字体并加上 CSP
├─ build/icon.ico|png   应用和工程文件图标
├─ package.json         依赖和 electron-builder 打包配置
└─ app/                 （生成）打包用的页面副本，不提交
```

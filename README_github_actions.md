# 用 GitHub Actions 自动出 macOS dmg（无需 Mac）

你没有 Mac 也能拿到可直接安装的 `.dmg`：把项目推到 GitHub，用免费云编译机打包。

## 一、前提

- 有一个 GitHub 账号（免费即可）
- 本机装了 `git`（或直接用 GitHub 网页上传）

## 二、操作步骤（3 步）

### 1. 在 GitHub 上建一个空仓库

打开 https://github.com/new 新建仓库，名字随意（如 `guizang`），**不要**勾选初始化 README。

### 2. 推送代码

在本项目目录下执行：

```bash
cd GuiZang
git init
git add .
git commit -m "归藏 初版"
git branch -M main
git remote add origin https://github.com/<你的用户名>/guizang.git
git push -u origin main
```

> 没有 git 命令？也可以直接在 GitHub 网页端点「uploading an existing file」，
> 把整个 `GuiZang/` 目录拖上去（注意别漏 `.github/workflows/build-mac.yml` 这个隐藏目录，
> 网页上传时可能默认不显示隐藏文件，可先本地用 git）。

### 3. 触发打包

1. 进入仓库页面的 **Actions** 标签
2. 左侧点 **Build macOS DMG**
3. 右侧点 **Run workflow** → 绿色 **Run workflow** 按钮
4. 等待约 5~10 分钟，出现 ✅ 后进入该次运行
5. 页面底部 **Artifacts** 处下载两个文件：
   - `GuiZang-x64-dmg`（Intel 芯片 Mac 用）
   - `GuiZang-arm64-dmg`（Apple 芯片 M 系列 Mac 用）

解压后就是 `GuiZang-<版本>-*.dmg`（版本号见仓库根 `VERSION`，如 `1.0.4` → `GuiZang-1.0.4-x64.dmg`），双击即可安装运行。

## 三、判断你的 Mac 用哪个

- 左上角  → 关于本机 → 处理器/芯片
  - 显示「Apple M1/M2/M3/M4」→ 用 **arm64**
  - 显示「Intel」→ 用 **x64**

## 四、说明

- 触发方式：手动（Run workflow），或打 `v*` 标签（如 `v1.0.4`）自动触发。
  版本号唯一来源是仓库根的 `VERSION` 文件；打 tag 时以 tag 为准，手动触发时读 `VERSION`。
- 未签名：产物未做 Apple 签名/公证，首次运行若被拦截，右键 App → 打开 即可。
- 想改成只出一个架构（更快），把 `.github/workflows/build-mac.yml` 里
  `matrix.include` 删掉不需要的那一行即可。

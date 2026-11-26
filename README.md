# 轻译 (QingYi) — 实时屏幕与声音字幕翻译

支持 **Windows 桌面独立 EXE** 与 **Android 手机全局悬浮窗** 的实时屏幕区域、快捷键截图及电脑/麦克风声音字幕翻译软件。

## 直接下载安装（免配置开箱即用）

- **Windows 电脑端（免安装便携版）**：**[点击下载 QingYi-Windows-x64.zip](https://github.com/huilygyc/qingyi-translator/releases/latest/download/QingYi-Windows-x64.zip)**（下载解压后直接双击 `轻译/轻译.exe` 即可打开主面板，无需安装 Python 环境）
- **Android 手机端（全局悬浮窗版）**：**[点击下载 QingYi-Android.apk](https://github.com/huilygyc/qingyi-translator/releases/latest/download/QingYi-Android.apk)**
- 历史版本与更新说明：**[前往 Releases 页面查看](https://github.com/huilygyc/qingyi-translator/releases)**

---

## 功能简介

1. **屏幕区域实时翻译**
   框选视频外语字幕区域，台词变化时自动识别并刷新译文；内置防重复识别穿透机制（`WDA_EXCLUDEFROMCAPTURE`），可直接将悬浮字幕覆盖在原字幕正上方观看。
2. **快捷键鼠标截图翻译**
   点击面板按钮、顶部迷你悬浮条或按下全局快捷键（默认 `Alt+Q`），拖动鼠标框选屏幕任意区域即可识别翻译。
3. **电脑原声与麦克风实时翻译**
   支持直接捕获 **电脑内部播放原声（WASAPI Loopback 内录）** 或 **麦克风说话声音**，本地离线识别语音并实时生成中文字幕。
4. **歌词级悬浮字幕与词表**
   - 支持自由调节预设主题、字体、字号（长句自动缩放）、颜色渐变、描边粗细、阴影强度与底板透明度。
   - 双击悬浮字幕或点击「修改译文」可直接修改当前文字，支持添加固定专有名词/角色译名词表并导出 `.srt` 双语字幕。
   - 支持开启「鼠标穿透锁定」，点击直接穿透到底层播放器。
5. **点击按键修改快捷键**
   在左侧「快捷键」页面点击按键框后直接按下键盘组合键即可修改（默认：截图 `Alt+Q`、框选 `Alt+R`、区域开关 `Alt+S`、声音开关 `Alt+A`、穿透锁定 `Alt+L`）。

---

## 源码目录结构

- `desktop/`：Windows 桌面端源码（PySide6 极简浅色界面 + RapidOCR PP-OCRv6 多语种识别 + Faster-Whisper + WASAPI 内录 + 多源免费/DeepSeek 翻译）
- `android/`：Android 原生端工程源码（Kotlin + Jetpack Compose + WindowManager 全局悬浮歌词 + MediaProjection 屏幕抓词 + ML Kit 离线多语种识别 + 内录/麦克风听译）

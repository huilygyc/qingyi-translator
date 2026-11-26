# 轻译 (QingYi) — 实时屏幕与声音字幕翻译

极简浅色设计的双端（**Windows 独立 EXE** + **Android 全局悬浮窗 APK**）实时屏幕区域、快捷键截图与电脑/麦克风声音字幕翻译软件。

## 直接下载安装（开箱即用，支持国内免代理直连）

- **Windows 电脑端（免安装便携版）**：**[点击下载 QingYi-Windows-x64.zip](https://github.com/huilygyc/qingyi-translator/releases/latest/download/QingYi-Windows-x64.zip)**
  - 解压后直接双击 `轻译/轻译.exe` 即可弹出浅色控制面板，无需安装 Python。
  - **Windows 安全提示说明**：因个人开源软件未购买商业代码签名证书，首次双击时若 Windows Defender SmartScreen 弹出蓝框提醒，点击「更多信息 -> 仍要运行」即可。
- **Android 手机端（浅色全局悬浮窗版）**：**[点击下载 QingYi-Android.apk](https://github.com/huilygyc/qingyi-translator/releases/latest/download/QingYi-Android.apk)**
- **全部历史版本**：**[前往 Releases 页面查看](https://github.com/huilygyc/qingyi-translator/releases)**

---

## 核心特性（v1.2.0）

1. **多线路并发竞速翻译（免代理可用）**
   - 内置 **Google Keep-Alive 长连接** 与 **国内免代理直连线路（有道直连 + MyMemory）** 并发竞速，无论是否开启代理均可快速出字幕；亦可在「偏好设置」切换为「国内直连免代理」或接入 **DeepSeek / 任意 OpenAI 兼容大模型**。
2. **极速本地离线多语种识字（~56 ms）**
   - 桌面端内置优化后的 RapidOCR PP-OCRv6，支持日/英/韩/俄/法等多语种，支持 **双帧防抖** 与 **防重复识别覆盖**（可直接把悬浮字幕拖到视频原外语字幕正上方覆盖观看）。
3. **电脑原声与麦克风语音翻译（支持 SenseVoiceSmall）**
   - 支持 Windows WASAPI 内录电脑正在播放的视频声音或麦克风说话声；除内置 Faster-Whisper 外，还支持一键切换阿里开源 **SenseVoiceSmall（ONNX）**，针对中日韩动漫人声与背景音乐场景准确率更高。
4. **歌词级悬浮字幕与看番细节**
   - 支持 6 套电影/歌词预设主题、字体、长句智能自适应字号、渐变色、描边、底板透明与双语切换。
   - **无台词自动隐身**：画面无文字或超过设定秒数（默认 6 秒）无新台词时字幕自动淡出，不遮挡纯画面。
   - **托盘防误退**：点击主面板关闭按钮默认最小化到系统托盘，悬浮字幕与悬浮条持续运行；双击悬浮字幕可直接修改译文并记忆专有名词词表，支持导出 `.srt` 字幕。
   - **内置更新检查**：在「偏好设置」点击「检查新版本」即可检测 GitHub 最新版本。
5. **自定义快捷键与双端浅色统一**
   - 桌面端左侧「快捷键」页支持点击按键框直接按键盘录制修改（默认：截图 `Alt+Q`、框选 `Alt+R`、区域翻译 `Alt+S`、声音翻译 `Alt+A`、穿透锁定 `Alt+L`）。
   - Android 手机端已全面同步为清爽浅色「轻译」界面，支持悬浮窗抓词、框选截屏翻译、语音听译及同局域网连接电脑端。

# Linux.do 刷帖助手 GUI 打包指南

本项目现在只保留本地 GUI 版本，打包目标是 `src/linux_do_gui.py`。

## 运行要求

- Python 3.8+
- Chrome 浏览器
- 项目依赖：见 `requirements.txt`
- 打包依赖：`pyinstaller`

安装依赖：

```bash
pip install -r requirements.txt
pip install pyinstaller
```

## 使用打包脚本

在对应平台执行：

```bash
python scripts/build.py
```

脚本会根据当前系统生成对应的 GUI 可执行文件。

## 手动打包命令

### Windows

```powershell
pyinstaller --onefile --windowed --name "LinuxDoHelper_Windows" `
  --hidden-import tkinter `
  --hidden-import tkinter.ttk `
  --hidden-import tkinter.scrolledtext `
  --hidden-import DrissionPage `
  --hidden-import pystray `
  --hidden-import PIL `
  --hidden-import PIL.Image `
  --hidden-import PIL.ImageDraw `
  --add-data "assets/icon.ico;." `
  --icon "assets/icon.ico" `
  --clean --noconfirm `
  src/linux_do_gui.py
```

输出目录：`dist/`

### macOS / Linux

```bash
pyinstaller --onefile --windowed --name "LinuxDoHelper" \
  --hidden-import tkinter \
  --hidden-import tkinter.ttk \
  --hidden-import tkinter.scrolledtext \
  --hidden-import DrissionPage \
  --hidden-import pystray \
  --hidden-import PIL \
  --hidden-import PIL.Image \
  --hidden-import PIL.ImageDraw \
  --add-data "assets/icon.ico:." \
  --clean --noconfirm \
  src/linux_do_gui.py
```

Linux 需要图形界面环境和 Tk 支持，例如 Ubuntu/Debian：

```bash
sudo apt update
sudo apt install python3 python3-pip python3-tk
```

## 从源码运行

如果打包版本有问题，可以直接运行源码：

```bash
pip install -r requirements.txt
python src/linux_do_gui.py
```

Windows 用户也可以直接运行：

```bat
start.bat
```

## 常见问题

### 程序启动后没有反应

确认已安装 Chrome 浏览器，并尝试从终端运行 `python src/linux_do_gui.py` 查看错误日志。

### 提示 tkinter 相关错误

Linux 需要安装 Tk 组件，例如 `python3-tk`。

### macOS 提示无法验证开发者

在“系统设置 → 隐私与安全性”中允许运行，或对打包产物执行：

```bash
xattr -cr /path/to/LinuxDoHelper
```

### 打包后缺少托盘图标或 PIL 相关模块

确认已安装 `Pillow` 和 `pystray`，并使用本指南中的 hidden import 参数。

## 文件说明

```text
linuxdosss/
├── src/
│   └── linux_do_gui.py              # GUI 主程序
├── scripts/
│   └── build.py                     # 多平台打包脚本
├── assets/
│   └── icon.ico                     # 应用图标
├── requirements.txt                 # 运行依赖
├── start.bat                        # Windows 一键启动
└── .github/workflows/
    └── build-pyinstaller.yml       # GUI 自动构建 workflow
```



# 双语文献阅读器

本地英文论文双语转换工具。上传 PDF 后，后端本地完成页面渲染、文本层提取或 Tesseract OCR，再调用用户选择的 OpenAI 或 DeepSeek 模型翻译，生成对页式 HTML 预览和 PDF 导出。

## 功能

- 本地网页上传 PDF
- 前端选择 OpenAI 或 DeepSeek
- 前端输入个人 API key，后端只在当前任务内存中使用
- 文字版 PDF 优先读取文本层
- 扫描版 PDF 使用 Tesseract OCR
- 对页式 HTML 预览：左页原文页面图，右页中文译文
- Playwright Chromium 导出 PDF

## 环境

- Python 3.11+
- Node.js 20+
- Tesseract 5：处理扫描版 PDF 必需
- Playwright Chromium：使用 `/export.pdf` 必需

Windows 上安装 Tesseract 后，需要确认 `tesseract.exe` 在 `PATH` 中，或把安装目录加入系统环境变量。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r api/requirements.txt
python -m playwright install chromium

npm install
npm --prefix web install
```

## 运行

最快方式是在 Windows 资源管理器里双击：

```powershell
start.bat
```

它会自动创建 `.venv`、安装缺失依赖、构建前端、启动本地 API 和网页，并打开 `http://127.0.0.1:3000`。如果 `3000` 或 `8000` 端口已经被占用，先关闭旧服务后再运行。

也可以在 PowerShell 里运行：

```powershell
.\start.ps1
```

开发模式：

```powershell
npm run dev
```

也可以分别运行：

```powershell
npm run dev:api
npm run dev:web
```

打开 `http://127.0.0.1:3000`。

## 配置

复制 `.env.example` 为 `.env` 后可调整：

- `DATA_DIR`：任务文件和导出结果目录，默认 `./data`
- `PUBLIC_BASE_URL`：后端用于 Playwright 导出时访问预览页，默认 `http://127.0.0.1:8000`
- `NEXT_PUBLIC_API_BASE_URL`：前端访问后端地址，默认 `http://127.0.0.1:8000`

API key 在网页里输入，不需要写入 `.env`。

## 模型

默认模型：

- OpenAI：`gpt-5.5`
- DeepSeek：`deepseek-v4-pro`

前端模型输入框支持改成供应商可用的其它模型名。

## 注意

- 当前任务状态存在后端内存中，重启 API 后任务列表会清空，但已生成文件仍在 `data/jobs` 下。
- 如果 PDF 没有文本层且未安装 Tesseract，任务会失败并提示安装 OCR。
- 如果未安装 Playwright Chromium，HTML 预览仍可用，PDF 导出接口会提示安装命令。

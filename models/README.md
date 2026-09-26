# 本地模型目录

GGUF 文件只保存在本机，Git 不跟踪或上传模型权重。

当前模型：`deepseek-r1-0528-qwen3-8b-q4_k_m.gguf`（约 5.2 GB）。
已有 Ollama 注册名称为 `deepseek-r1-local`，移动源文件不会影响已注册的模型。

在项目根目录重新注册时运行：

```powershell
ollama create deepseek-r1-local -f models/Modelfile.deepseek-r1
```

如 `ollama` 未在 PATH 中，请使用本机 `ollama.exe` 的完整安装路径。

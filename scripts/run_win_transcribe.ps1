# PowerShell 脚本：清华 26-0825 采访转录
# 运行环境：Windows + Python + FunASR (已装)
# Usage: .\run_win_transcribe.ps1

# 配置转录目录
$WorkDir = "H:/街头采访/清华 26-0825/_work/"
if (-not (Test-Path $WorkDir)) {
    Write-Host "错误：工作目录不存在 - $WorkDir" -ForegroundColor Red
    exit 1
}

# 配置 API（可选）
$DASHSCOPE_API_KEY = "sk-ws-H.RXIIRYP..."  # 替换为你的完整 Key（存 .env）
if ($env:DASHSCOPE_API_KEY) { $DASHSCOPE_API_KEY = $env:DASHSCOPE_API_KEY }

# 视频列表
$Videos = @("IMG_0118.MOV", "IMG_0112.MOV", "IMG_0113.MOV", "IMG_0114.MOV", "IMG_0115.MOV", "IMG_0116.MOV")

Write-Host "===== 开始转录 =====" -ForegroundColor Cyan
foreach ($v in $Videos) {
    $path = Join-Path $WorkDir $v
    if (-not (Test-Path $path)) {
        Write-Host "跳过：$v 不存在" -ForegroundColor Yellow; continue
    }
    # 调用技能接口或本地脚本
    & python "C:\Users\admin\.workbuddy\skills\interview-transcriber\scripts\transcribe_qwen.py" --input-file $path `
        --output-dir $WorkDir `
        --api-key $DASHSCOPE_API_KEY
    # 或使用本地 MOSS（如果已装）：
    # & python "C:\Users\admin\.workbuddy\skills\interview-transcriber\scripts\transcribe_local.py" ...
}

Write-Host "===== 全部处理完成 =====" -ForegroundColor Green
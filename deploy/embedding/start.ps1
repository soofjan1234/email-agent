param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('snowflake', 'nomic', 'bge-m3', 'qwen3')]
    [string]$Model,
    [string]$Context = 'desktop-linux'
)

$ErrorActionPreference = 'Stop'
# 从唯一模型清单读取权重版本，避免手工填写不匹配的模型与 revision。
$modelManifest = Join-Path $PSScriptRoot '../../evals/embedding-models.json'
$modelConfiguration = (Get-Content -Raw -Encoding UTF8 $modelManifest | ConvertFrom-Json).$Model
$previousModel = $env:EMBED_MODEL_ID
$previousRevision = $env:EMBED_MODEL_REVISION
try {
    $env:EMBED_MODEL_ID = $modelConfiguration.model
    $env:EMBED_MODEL_REVISION = $modelConfiguration.revision
    # 同一个实验服务顺序重建，只保留一个模型运行，缓存卷持续复用。
    docker --context $Context compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d --force-recreate
    if ($LASTEXITCODE -ne 0) { throw 'Embedding container startup failed' }
} finally {
    $env:EMBED_MODEL_ID = $previousModel
    $env:EMBED_MODEL_REVISION = $previousRevision
}

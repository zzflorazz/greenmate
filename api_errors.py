"""One public error shape, retaining existing evidence fields for old clients."""
from fastapi.responses import JSONResponse


def failure(http_status: int, code: str, message: str, hint: str, **evidence) -> JSONResponse:
    return JSONResponse(status_code=http_status, content={
        **evidence, 'error': {'code': code, 'message': message, 'hint': hint},
    })


def hint_for(status: int) -> str:
    if status == 422 or status == 400:
        return '请检查输入内容后重试。'
    if status == 404:
        return '请检查请求地址；预测指标缺失时请先运行训练脚本。'
    if status in (502, 503, 504):
        return '请检查网络与 .env 中的模型配置，稍后重试；已取得的工具证据会保留。'
    return '请稍后重试；若仍失败，请查看启动终端日志。'

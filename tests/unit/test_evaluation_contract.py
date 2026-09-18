"""验证评估运行的纯输入边界，不访问真实邮箱或模型。"""
import pytest

from services.evaluation import EvaluationError


def test_evaluation_error_keeps_stable_reason_code():
    """命令层可以只暴露受控原因码，不泄露数据库细节。"""
    error = EvaluationError('evaluation_run_immutable')
    assert error.code == str(error) == 'evaluation_run_immutable'

"""应用侧生成适配器，复用已验证的 OpenAI-compatible JSON 客户端。"""
import asyncio

from evals.harness.agent_schema import AGENT_RESPONSE_SCHEMA
from evals.harness.generator import GeneratorConfig, HttpGenerator


class AgentGenerator:
    """把同步 HTTP 客户端隔离在线程中，并固定 B2 输出 Schema。"""

    def __init__(self, settings):
        """从受控运行配置构建客户端；密钥不会进入 repr 或业务日志。"""
        config = GeneratorConfig(base_url=settings.generator_base_url,
            api_key=settings.generator_api_key.get_secret_value(), model=settings.generator_model,
            timeout_seconds=settings.generator_timeout_seconds)
        self.client = HttpGenerator(config)

    async def generate(self, messages):
        """生成一个冻结结构的可审核决定。"""
        return await asyncio.to_thread(self.client.generate, messages, AGENT_RESPONSE_SCHEMA)

    def close(self):
        """释放持有的 HTTP 连接。"""
        self.client.close()

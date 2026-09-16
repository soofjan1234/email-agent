"""应用配置与开发候选索引身份；不读取历史生产冻结记录。"""
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from evals.harness.local_embedding import LocalModel


class Settings(BaseSettings):
    """环境变量覆盖本地开发默认值，凭据字段禁止出现在 repr 中。"""
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', hide_input_in_errors=True)

    database_url: SecretStr
    test_database_url: SecretStr | None = None
    # 同一模拟邮箱的原生进程和容器必须使用同一个稳定标识。
    mailbox_id: str = Field(default='local-mock', min_length=1, max_length=128)
    mailbox_root: Path = Path('data/mock-mailbox')
    mail_sync_page_size: int = Field(default=100, ge=1, le=1000)
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # 仅此可信目录下的 Markdown 可导入；运行配置指定，HTTP 请求不能更改。
    knowledge_root: Path = Path('data/knowledge')
    knowledge_source_id: str = Field(default='local-products', min_length=1, max_length=128)
    knowledge_max_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    embedding_model: str = 'Snowflake/snowflake-arctic-embed-m-v1.5'
    embedding_revision: str = 'e58a8f756156a1293d763f17e3aae643474e9b8a'
    embedding_dimensions: int = Field(default=768, ge=1, le=16000)
    embedding_query_prefix: str = 'Represent this sentence for searching relevant passages: '
    embedding_document_prefix: str = ''
    # 独立开发索引标识，不等同于生产模型冻结。
    embedding_index_version: str = 'dev-snowflake-m-v1.5-001'
    embedding_base_url: str = 'http://127.0.0.1:18080'

    @field_validator('embedding_model', 'embedding_revision', 'embedding_index_version')
    @classmethod
    def require_identity(cls, value):
        """禁止缺失关键身份而降级为不受约束的索引。"""
        if not value.strip():
            raise ValueError('embedding identity must not be empty')
        return value

    @field_validator('database_url')
    @classmethod
    def require_postgresql(cls, value):
        """业务层只支持显式 psycopg PostgreSQL 连接。"""
        url = make_url(value.get_secret_value())
        if url.drivername != 'postgresql+psycopg' or not url.database:
            raise ValueError('database_url must use postgresql+psycopg and name a database')
        return value

    def local_model(self):
        """复用现有 TEI 身份验证所使用的模型及角色模板。"""
        return LocalModel(self.embedding_model, self.embedding_revision, self.embedding_dimensions,
                          self.embedding_query_prefix, self.embedding_document_prefix)

    def embedding_identity(self):
        """比较完整编码身份，避免仅比较维度而混用向量空间。"""
        return {'model': self.embedding_model, 'revision': self.embedding_revision,
                'dimensions': self.embedding_dimensions, 'query_prefix': self.embedding_query_prefix,
                'document_prefix': self.embedding_document_prefix,
                'index_version': self.embedding_index_version}


def validate_test_database(business_url, test_url):
    """拒绝业务库及不显式命名为测试库的地址，不依赖主机别名判断。"""
    business, test = make_url(business_url), make_url(test_url)
    if (test.drivername != 'postgresql+psycopg' or not test.database
            or not test.database.endswith('_test') or test.database == business.database):
        raise ValueError('TEST_DATABASE_URL must reference an independent *_test database')

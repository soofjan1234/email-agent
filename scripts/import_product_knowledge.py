"""将受控的 LincStation 产品资料导入当前隔离知识库。"""
import asyncio
import json
import sys

from sqlalchemy import func, select

from config import Settings
from db import Database
from models import KnowledgeChunk
from services.knowledge import KnowledgeService


# 仅导入本脚本明确列出的相对路径，调用方不能传入任意本机文件。
# 产品资料的唯一导入清单；每项均绑定可审计的官方来源元数据。
PRODUCT_DOCUMENTS = (
    ('lincstation-e1-lincos-support.md', 'LincStation E1 与 LincOS 支持入口', 'LincStation E1',
     'https://www.lincplustech.com/support/lincstation-e1.html', 'E1 的 LincOS 基础支持入口'),
    ('lincstation-n1-n2-s1-unraid-hardware-support.md', 'LincStation N1、N2、S1 的 Unraid 与硬件支持',
     'LincStation N1/N2/S1', 'https://www.lincplustech.com/support/lincstation-s1.html',
     'N1、N2、S1 的 Unraid 与硬件支持入口'),
    ('lincstation-model-selection-and-common-use.md', 'LincStation 型号选择与常见使用场景',
     'LincStation E1/N1/N2/S1', 'https://store.lincplustech.com/pages/choose-lincstation-nas',
     '型号选择与官方教程入口'),
    ('lincstation-e1-lincos-download-upgrade.md', 'LincStation E1 的 LincOS 下载与升级', 'LincStation E1',
     'https://www.lincplustech.com/support/lincstation-e1.html', 'E1 的下载、版本核对与升级前后检查'),
    ('lincstation-e1-services-docker.md', 'LincStation E1 的服务管理与 Docker', 'LincStation E1',
     'https://www.lincplustech.com/support/lincstation-e1.html', 'E1 的服务状态与容器功能入口'),
    ('lincstation-e1-install-network-access.md', 'LincStation E1 的安装与网络访问', 'LincStation E1',
     'https://www.lincplustech.com/support/lincstation-e1.html', 'E1 安装、Web UI、客户端与远程访问路径'),
    ('lincstation-s1-boot-recovery-migration.md', 'LincStation S1 的启动、恢复与迁移', 'LincStation S1',
     'https://www.lincplustech.com/support/lincstation-s1.html', 'S1 启动、恢复和迁移前置检查'),
    ('lincstation-n1-n2-storage-nvme-thermal-accessories.md', 'LincStation N1、N2 的存储与配件检查',
     'LincStation N1/N2', 'https://www.lincplustech.com/support/lincstation-s1.html',
     'N1、N2 的 SSD、NVMe、温度与配件支持入口'),
)


async def import_product_documents(settings: Settings):
    """导入固定八份官方资料摘要，只返回文档标识和版本等脱敏元数据。"""
    database = Database(settings)
    try:
        await database.check_ready()
        service = KnowledgeService(database)
        results = []
        # 1. 固定文件清单由代码定义；服务层继续校验可信根、编码和大小。
        for path, title, product_model, official_url, scope in PRODUCT_DOCUMENTS:
            document = await service.import_document(path, title=title, product_model=product_model,
                category='official-support-summary', source_metadata={
                    'official_url': official_url,
                    'retrieved_at': '2026-09-18',
                    'applicable_models': product_model,
                    'applicable_scope': scope,
                })
            async with database.session() as session:
                chunk_count = await session.scalar(select(func.count()).select_from(KnowledgeChunk).where(
                    KnowledgeChunk.document_id == document['id']))
            result = {key: document[key] for key in ('id', 'title', 'version', 'status', 'source_type')}
            result['chunk_count'] = chunk_count
            results.append(result)
        return results
    finally:
        await database.close()


def run_async(coroutine):
    """在 Windows 上选择 Psycopg 可用的 Selector 事件循环。"""
    if sys.platform != 'win32':
        return asyncio.run(coroutine)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def main():
    """使用当前 .env 的隔离数据库与可信知识根完成导入。"""
    print(json.dumps(run_async(import_product_documents(Settings())), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()

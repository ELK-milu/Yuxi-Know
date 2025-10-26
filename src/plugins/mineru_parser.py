"""
MinerU 文档解析器

使用 MinerU 服务进行文档版面分析和内容提取
"""

import os
import time
from pathlib import Path

import requests

from src.plugins.document_processor_base import BaseDocumentProcessor, DocumentParserException
from src.utils import logger


class MinerUParser(BaseDocumentProcessor):
    """MinerU 文档解析器 - 使用 HTTP API 进行文档理解和解析"""

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url or os.getenv("MINERU_API_URI", "http://localhost:30001")
        self.parse_endpoint = f"{self.server_url}/file_parse"

    def get_service_name(self) -> str:
        return "mineru_ocr"

    def get_supported_extensions(self) -> list[str]:
        """MinerU 支持 PDF 和多种图像格式"""
        return [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

    def check_health(self) -> dict:
        """检查 MinerU 服务健康状态"""
        try:
            # 尝试访问 OpenAPI JSON 端点来检查服务是否可用
            health_url = f"{self.server_url}/openapi.json"
            response = requests.get(health_url, timeout=5)

            if response.status_code == 200:
                try:
                    openapi_data = response.json()
                    # 检查是否包含 file_parse 端点
                    has_file_parse = "/file_parse" in openapi_data.get("paths", {})

                    if has_file_parse:
                        return {
                            "status": "healthy",
                            "message": "MinerU 服务运行正常",
                            "details": {
                                "server_url": self.server_url,
                                "api_version": openapi_data.get("info", {}).get("version", "unknown"),
                            },
                        }
                    else:
                        return {
                            "status": "unhealthy",
                            "message": "MinerU 服务缺少必要的端点",
                            "details": {"server_url": self.server_url},
                        }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "message": f"MinerU 响应格式错误: {str(e)}",
                        "details": {"server_url": self.server_url},
                    }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"MinerU 服务响应异常: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "MinerU 服务无法连接,请检查服务是否启动",
                "details": {"server_url": self.server_url},
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "message": "MinerU 服务连接超时",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"MinerU 健康检查失败: {str(e)}",
                "details": {"server_url": self.server_url, "error": str(e)},
            }

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
        使用 MinerU 处理文档

        Args:
            file_path: 文件路径
            params: 处理参数
                - lang_list: 语言列表 (默认: ["ch"])
                - backend: 后端类型 (默认: "pipeline", 支持 "vlm-*" 系列)
                - parse_method: 解析方法 (默认: "auto")
                - start_page_id: 起始页码 (默认: 0)
                - end_page_id: 结束页码 (默认: 99999)
                - formula_enable: 启用公式解析 (默认: True)
                - table_enable: 启用表格解析 (默认: True)
                - server_url: VLM 服务器地址 (vlm-http-client 时需要)

        Returns:
            str: 提取的 Markdown 文本
        """
        if not os.path.exists(file_path):
            raise DocumentParserException(f"文件不存在: {file_path}", self.get_service_name(), "file_not_found")

        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise DocumentParserException(
                f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type"
            )

        # 解析参数
        params = params or {}

        # 构建请求数据 - 只保留核心参数
        data = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", "vlm-http-client"),
            "parse_method": params.get("parse_method", "auto"),
            # 固定返回 markdown 格式
            "return_md": True,
        }

        # vlm-http-client 后端需要 server_url
        if data["backend"] == "vlm-http-client":
            data["server_url"] = params.get("server_url")

        try:
            start_time = time.time()

            logger.info(
                f"MinerU 开始处理: {os.path.basename(file_path)} (backend={data['backend']}, lang={data['lang_list']})"
            )

            # 打开文件并发送请求
            with open(file_path, "rb") as f:
                files = {"files": (os.path.basename(file_path), f, "application/octet-stream")}

                # 发送 POST 请求
                response = requests.post(
                    self.parse_endpoint,
                    files=files,
                    data=data,
                    timeout=300,  # 5分钟超时
                )

            # 检查响应状态
            if response.status_code != 200:
                error_detail = "未知错误"
                try:
                    error_data = response.json()
                    error_detail = error_data.get("detail", str(error_data))
                except Exception:
                    error_detail = response.text or f"HTTP {response.status_code}"

                raise DocumentParserException(
                    f"MinerU 处理失败: {error_detail}",
                    self.get_service_name(),
                    f"http_{response.status_code}",
                )

            # 解析响应
            try:
                result = response.json()

                # 简化响应处理 - 专注于获取 markdown 内容
                if isinstance(result, dict) and "results" in result:
                    file_result = list(result["results"].values())[0]
                    text = file_result.get("md") or file_result.get("markdown") or file_result.get("md_content", "")
                else:
                    # 降级处理
                    text = str(result) if result else ""

                if not text:
                    logger.error(f"MinerU 未返回任何文本内容: {str(result)[:500]}")
                    raise DocumentParserException(
                        "MinerU 未返回任何文本内容",
                        self.get_service_name(),
                        "no_content",
                    )

                processing_time = time.time() - start_time
                logger.info(
                    f"MinerU 处理成功: {os.path.basename(file_path)} - {len(text)} 字符 ({processing_time:.2f}s)"
                )

                return text

            except Exception as e:
                raise DocumentParserException(
                    f"MinerU 响应解析失败: {str(e)}",
                    self.get_service_name(),
                    "response_parse_error",
                )

        except DocumentParserException:
            raise
        except requests.exceptions.Timeout:
            error_msg = f"MinerU 处理超时 ({time.time() - start_time:.2f}s)"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "timeout")
        except requests.exceptions.ConnectionError:
            error_msg = "MinerU 连接失败,请检查服务是否运行"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "connection_error")
        except Exception as e:
            error_msg = f"MinerU 处理失败: {str(e)}"
            logger.error(f"{error_msg} ({time.time() - start_time:.2f}s)")
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed")

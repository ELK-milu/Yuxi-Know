"""
RapidOCR 处理器 - 纯OCR文字识别

使用 RapidOCR (PP-OCRv4) 进行文字识别
"""

import os
import tempfile
import time
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from src.plugins.document_processor_base import BaseDocumentProcessor, OCRException
from src.utils import logger


class RapidOCRProcessor(BaseDocumentProcessor):
    """RapidOCR 处理器 - 使用 ONNX 模型进行文字识别"""

    def __init__(self, det_box_thresh: float = 0.3):
        self.ocr = None
        self.det_box_thresh = det_box_thresh
        self.model_dir_root = (
            os.getenv("MODEL_DIR") if not os.getenv("RUNNING_IN_DOCKER") else os.getenv("MODEL_DIR_IN_DOCKER")
        )

    def get_service_name(self) -> str:
        return "rapid_ocr"

    def get_supported_extensions(self) -> list[str]:
        return [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

    def _get_model_paths(self) -> tuple[str, str]:
        """获取模型文件路径"""
        model_dir = os.path.join(self.model_dir_root, "SWHL/RapidOCR")
        det_model_path = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_det_infer.onnx")
        rec_model_path = os.path.join(model_dir, "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx")
        return det_model_path, rec_model_path

    def check_health(self) -> dict:
        """检查 RapidOCR 模型是否可用"""
        try:
            det_model_path, rec_model_path = self._get_model_paths()
            model_dir = os.path.dirname(os.path.dirname(det_model_path))

            if not os.path.exists(model_dir):
                return {
                    "status": "unavailable",
                    "message": f"模型目录不存在: {model_dir}",
                    "details": {"model_dir": model_dir},
                }

            if not os.path.exists(det_model_path) or not os.path.exists(rec_model_path):
                return {
                    "status": "unavailable",
                    "message": "模型文件缺失",
                    "details": {"det_model": det_model_path, "rec_model": rec_model_path},
                }

            # 尝试加载模型
            try:
                test_ocr = RapidOCR(
                    det_box_thresh=self.det_box_thresh, det_model_path=det_model_path, rec_model_path=rec_model_path
                )
                del test_ocr  # 释放资源
                return {
                    "status": "healthy",
                    "message": "RapidOCR模型可用",
                    "details": {"model_path": self._get_model_paths()},
                }
            except Exception as e:
                return {"status": "error", "message": f"模型加载失败: {str(e)}", "details": {"error": str(e)}}

        except Exception as e:
            return {"status": "error", "message": f"健康检查失败: {str(e)}", "details": {"error": str(e)}}

    def _load_model(self):
        """延迟加载 OCR 模型"""
        if self.ocr is not None:
            return

        logger.info("加载 RapidOCR 模型...")

        # 先检查健康状态
        health = self.check_health()
        if health["status"] != "healthy":
            raise OCRException(health["message"], self.get_service_name(), health["status"])

        try:
            det_model_path, rec_model_path = self._get_model_paths()
            self.ocr = RapidOCR(
                det_box_thresh=self.det_box_thresh, det_model_path=det_model_path, rec_model_path=rec_model_path
            )
            logger.info(f"RapidOCR 模型加载成功 (det_box_thresh={self.det_box_thresh})")
        except Exception as e:
            raise OCRException(f"RapidOCR模型加载失败: {str(e)}", self.get_service_name(), "load_failed")

    def process_image(self, image, params: dict | None = None) -> str:
        """
        处理单张图像并提取文本

        Args:
            image: 图像数据,支持:
                  - str: 图像文件路径
                  - PIL.Image: PIL图像对象
                  - numpy.ndarray: numpy图像数组
            params: 处理参数 (当前未使用)

        Returns:
            str: 提取的文本内容
        """
        self._load_model()

        try:
            # 处理不同类型的输入
            if isinstance(image, str):
                image_path = image
                cleanup_needed = False
            else:
                # 创建临时文件
                image_path = self._create_temp_image_file(image)
                cleanup_needed = True

            try:
                # 执行 OCR
                start_time = time.time()
                result, _ = self.ocr(image_path)
                processing_time = time.time() - start_time

                # 提取文本
                if result:
                    text = "\n".join([line[1] for line in result])
                    logger.info(
                        f"RapidOCR 成功: {os.path.basename(image_path) if isinstance(image, str) else 'temp_image'}"
                        f" ({processing_time:.2f}s)"
                    )
                    return text
                else:
                    logger.warning(f"RapidOCR 未识别到文本: {image_path}")
                    return ""

            finally:
                # 清理临时文件
                if cleanup_needed and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        logger.warning(f"临时文件清理失败: {image_path} - {e}")

        except Exception as e:
            error_msg = f"图像OCR处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "processing_failed")

    def _create_temp_image_file(self, image) -> str:
        """将图像数据保存为临时文件"""
        try:
            # 使用系统临时目录
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
                temp_path = tmp_file.name

                if isinstance(image, Image.Image):
                    image.save(temp_path)
                elif isinstance(image, np.ndarray):
                    Image.fromarray(image).save(temp_path)
                else:
                    raise ValueError("不支持的图像类型,必须是 PIL.Image 或 numpy.ndarray")

                return temp_path

        except Exception as e:
            raise OCRException(f"临时图像文件创建失败: {str(e)}", self.get_service_name(), "temp_file_error")

    def process_pdf(self, pdf_path: str, params: dict | None = None) -> str:
        """
        处理 PDF 文件并提取文本 (流式处理,避免内存占用)

        Args:
            pdf_path: PDF 文件路径
            params: 处理参数
                - zoom_x: 横向缩放 (默认 2)
                - zoom_y: 纵向缩放 (默认 2)

        Returns:
            str: 提取的文本
        """
        if not os.path.exists(pdf_path):
            raise OCRException(f"PDF 文件不存在: {pdf_path}", self.get_service_name(), "file_not_found")

        params = params or {}
        zoom_x = params.get("zoom_x", 2)
        zoom_y = params.get("zoom_y", 2)

        try:
            all_text = []
            pdf_doc = fitz.open(pdf_path)
            total_pages = pdf_doc.page_count

            logger.info(f"开始处理 PDF: {os.path.basename(pdf_path)} ({total_pages} 页)")

            # 流式处理每一页,避免一次性加载所有图片到内存
            for page_num in range(total_pages):
                page = pdf_doc[page_num]

                # 转换为图像
                mat = fitz.Matrix(zoom_x, zoom_y)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # 立即处理,不保存到列表
                text = self.process_image(img_pil)
                all_text.append(text)

                if (page_num + 1) % 10 == 0:
                    logger.info(f"已处理 {page_num + 1}/{total_pages} 页")

            pdf_doc.close()

            result_text = "\n\n".join(all_text)
            logger.info(f"PDF OCR 完成: {os.path.basename(pdf_path)} - {len(result_text)} 字符")
            return result_text

        except OCRException:
            raise
        except Exception as e:
            error_msg = f"PDF OCR 处理失败: {str(e)}"
            logger.error(error_msg)
            raise OCRException(error_msg, self.get_service_name(), "pdf_processing_failed")

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
        处理文件 (PDF 或图像)

        Args:
            file_path: 文件路径
            params: 处理参数

        Returns:
            str: 提取的文本
        """
        file_ext = Path(file_path).suffix.lower()

        if not self.supports_file_type(file_ext):
            raise OCRException(f"不支持的文件类型: {file_ext}", self.get_service_name(), "unsupported_file_type")

        if file_ext == ".pdf":
            return self.process_pdf(file_path, params)
        else:
            return self.process_image(file_path, params)

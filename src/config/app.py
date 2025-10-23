"""
应用配置模块

使用 Pydantic BaseModel 实现配置管理，支持：
- 从 TOML 文件加载用户配置
- 仅保存用户修改过的配置项
- 默认配置定义在代码中
"""

import os
from pathlib import Path
from typing import Any

import tomli
import tomli_w
from pydantic import BaseModel, Field

from src.config.static.models import (
    DEFAULT_CHAT_MODEL_PROVIDERS,
    DEFAULT_EMBED_MODELS,
    DEFAULT_RERANKERS,
    ChatModelProvider,
    EmbedModelInfo,
    RerankerInfo,
)
from src.utils.logging_config import logger


class Config(BaseModel):
    """应用配置类"""

    # ============================================================
    # 基础配置
    # ============================================================
    save_dir: str = Field(default="saves", description="保存目录")
    model_dir: str = Field(default="", description="本地模型目录")

    # ============================================================
    # 功能开关
    # ============================================================
    enable_reranker: bool = Field(default=False, description="是否开启重排序")
    enable_content_guard: bool = Field(default=False, description="是否启用内容审查")
    enable_content_guard_llm: bool = Field(default=False, description="是否启用LLM内容审查")
    enable_web_search: bool = Field(default=False, description="是否启用网络搜索")

    # ============================================================
    # 模型配置
    # ============================================================
    default_model: str = Field(
        default="siliconflow/deepseek-ai/DeepSeek-V3.2-Exp",
        description="默认对话模型",
    )
    fast_model: str = Field(
        default="siliconflow/THUDM/GLM-4-9B-0414",
        description="快速响应模型",
    )
    embed_model: str = Field(
        default="siliconflow/BAAI/bge-m3",
        description="Embedding 模型",
    )
    reranker: str = Field(
        default="siliconflow/BAAI/bge-reranker-v2-m3",
        description="Re-Ranker 模型",
    )
    content_guard_llm_model: str = Field(
        default="siliconflow/Qwen/Qwen3-235B-A22B-Instruct-2507",
        description="内容审查LLM模型",
    )

    # ============================================================
    # 智能体配置
    # ============================================================
    default_agent_id: str = Field(default="", description="默认智能体ID")

    # ============================================================
    # 模型信息（只读，不持久化）
    # ============================================================
    model_names: dict[str, ChatModelProvider] = Field(
        default_factory=lambda: DEFAULT_CHAT_MODEL_PROVIDERS.copy(),
        description="聊天模型提供商配置",
        exclude=True,
    )
    embed_model_names: dict[str, EmbedModelInfo] = Field(
        default_factory=lambda: DEFAULT_EMBED_MODELS.copy(),
        description="嵌入模型配置",
        exclude=True,
    )
    reranker_names: dict[str, RerankerInfo] = Field(
        default_factory=lambda: DEFAULT_RERANKERS.copy(),
        description="重排序模型配置",
        exclude=True,
    )

    # ============================================================
    # 运行时状态（不持久化）
    # ============================================================
    model_provider_status: dict[str, bool] = Field(
        default_factory=dict,
        description="模型提供商可用状态",
        exclude=True,
    )
    valuable_model_provider: list[str] = Field(
        default_factory=list,
        description="可用的模型提供商列表",
        exclude=True,
    )

    # 内部状态
    _config_file: Path | None = None
    _user_modified_fields: set[str] = set()
    _modified_providers: set[str] = set()  # 记录具体修改的模型提供商

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    def __init__(self, **data):
        super().__init__(**data)
        self._setup_paths()
        self._load_user_config()
        self._handle_environment()

    def _setup_paths(self):
        """设置配置文件路径"""
        self.save_dir = os.getenv("SAVE_DIR", self.save_dir)
        self._config_file = Path(self.save_dir) / "config" / "base.toml"
        self._config_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_user_config(self):
        """从 TOML 文件加载用户配置"""
        if not self._config_file or not self._config_file.exists():
            logger.info(f"Config file not found, using defaults: {self._config_file}")
            return

        logger.info(f"Loading config from {self._config_file}")
        try:
            with open(self._config_file, "rb") as f:
                user_config = tomli.load(f)

            # 记录用户修改的字段
            self._user_modified_fields = set(user_config.keys())

            # 更新配置
            for key, value in user_config.items():
                if key == "model_names":
                    # 特殊处理模型配置
                    self._load_model_names(value)
                elif hasattr(self, key):
                    setattr(self, key, value)
                else:
                    logger.warning(f"Unknown config key: {key}")

        except Exception as e:
            logger.error(f"Failed to load config from {self._config_file}: {e}")

    def _load_model_names(self, model_names_data):
        """加载用户自定义的模型配置"""
        try:
            for provider, provider_data in model_names_data.items():
                if provider in self.model_names:
                    # 更新现有提供商的模型列表
                    if "models" in provider_data:
                        self.model_names[provider].models = provider_data["models"]
                else:
                    # 添加新的提供商
                    self.model_names[provider] = ChatModelProvider(**provider_data)
            logger.info(f"Loaded custom model configurations for {len(model_names_data)} providers")
        except Exception as e:
            logger.error(f"Failed to load model names: {e}")

    def _handle_environment(self):
        """处理环境变量和运行时状态"""
        # 处理模型目录
        self.model_dir = os.environ.get("MODEL_DIR", self.model_dir)
        if self.model_dir:
            if os.path.exists(self.model_dir):
                logger.debug(f"Model directory ({self.model_dir}) contains: {os.listdir(self.model_dir)}")
            else:
                logger.warning(
                    f"Model directory ({self.model_dir}) does not exist. If not configured, please ignore it."
                )

        # 检查模型提供商的环境变量
        self.model_provider_status = {}
        for provider, info in self.model_names.items():
            env_var = info.env
            if env_var == "NO_API_KEY":
                self.model_provider_status[provider] = True
            else:
                self.model_provider_status[provider] = bool(os.getenv(env_var))

        # 检查网络搜索
        if os.getenv("TAVILY_API_KEY"):
            self.enable_web_search = True

        # 获取可用的模型提供商
        self.valuable_model_provider = [k for k, v in self.model_provider_status.items() if v]

        if not self.valuable_model_provider:
            raise ValueError("No model provider available, please check your `.env` file.")

    def save(self):
        """保存配置到 TOML 文件（仅保存用户修改的字段）"""
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving config to {self._config_file}")

        # 获取默认配置
        default_config = Config.model_construct()

        # 对比当前配置和默认配置，找出用户修改的字段
        user_modified = {}
        for field_name in self.model_fields.keys():
            # 跳过 exclude=True 的字段
            field_info = self.model_fields[field_name]
            if field_info.exclude:
                continue

            current_value = getattr(self, field_name)
            default_value = getattr(default_config, field_name)

            # 如果值不同，说明用户修改了
            if current_value != default_value:
                user_modified[field_name] = current_value

        # 写入 TOML 文件
        try:
            with open(self._config_file, "wb") as f:
                tomli_w.dump(user_modified, f)
            logger.info(f"Config saved to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save config to {self._config_file}: {e}")

    def dump_config(self) -> dict[str, Any]:
        """导出配置为字典（用于 API 返回）"""
        config_dict = self.model_dump(
            exclude={
                "model_names",
                "embed_model_names",
                "reranker_names",
                "model_provider_status",
                "valuable_model_provider",
            }
        )

        # 添加模型信息（转换为字典格式供前端使用）
        config_dict["model_names"] = {provider: info.model_dump() for provider, info in self.model_names.items()}
        config_dict["embed_model_names"] = {
            model_id: info.model_dump() for model_id, info in self.embed_model_names.items()
        }
        config_dict["reranker_names"] = {model_id: info.model_dump() for model_id, info in self.reranker_names.items()}

        # 添加运行时状态信息
        config_dict["model_provider_status"] = self.model_provider_status
        config_dict["valuable_model_provider"] = self.valuable_model_provider

        fields_info = {}
        for field_name, field_info in Config.model_fields.items():
            if not field_info.exclude:  # 排除内部字段
                fields_info[field_name] = {
                    "des": field_info.description,
                    "default": field_info.default,
                    "type": field_info.annotation.__name__
                    if hasattr(field_info.annotation, "__name__")
                    else str(field_info.annotation),
                    "exclude": field_info.exclude if hasattr(field_info, "exclude") else False,
                }
        config_dict["_config_items"] = fields_info

        return config_dict

    def get_model_choices(self) -> list[str]:
        """获取所有可用的聊天模型列表"""
        choices = []
        for provider, info in self.model_names.items():
            if self.model_provider_status.get(provider, False):
                for model in info.models:
                    choices.append(f"{provider}/{model}")
        return choices

    def get_embed_model_choices(self) -> list[str]:
        """获取所有可用的嵌入模型列表"""
        return list(self.embed_model_names.keys())

    def get_reranker_choices(self) -> list[str]:
        """获取所有可用的重排序模型列表"""
        return list(self.reranker_names.keys())

    # ============================================================
    # 兼容旧代码的方法
    # ============================================================

    def __getitem__(self, key: str) -> Any:
        """支持字典式访问 config[key]"""
        logger.warning("Using deprecated dict-style access for Config. Please use attribute access instead.")
        return getattr(self, key, None)

    def __setitem__(self, key: str, value: Any):
        """支持字典式赋值 config[key] = value"""
        logger.warning("Using deprecated dict-style assignment for Config. Please use attribute access instead.")
        setattr(self, key, value)

    def update(self, other: dict):
        """批量更新配置（兼容旧代码）"""
        for key, value in other.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                logger.warning(f"Unknown config key: {key}")

    def _save_models_to_file(self, provider_name: str = None):
        """保存模型配置到主配置文件

        Args:
            provider_name: 如果提供，只保存特定provider的修改；否则保存所有model_names
        """
        if not self._config_file:
            logger.warning("Config file path not set")
            return

        logger.info(f"Saving models config to {self._config_file}")

        try:
            # 读取现有配置
            user_config = {}
            if self._config_file.exists():
                with open(self._config_file, "rb") as f:
                    user_config = tomli.load(f)

            # 初始化 model_names 配置（如果不存在）
            if "model_names" not in user_config:
                user_config["model_names"] = {}

            if provider_name:
                # 只保存特定 provider 的修改
                if provider_name in self.model_names:
                    user_config["model_names"][provider_name] = self.model_names[provider_name].model_dump()
                    # 记录具体修改的 provider
                    self._modified_providers.add(provider_name)
                    logger.info(f"Saved models config for provider: {provider_name}")
            else:
                # 保存所有 model_names
                user_config["model_names"] = {
                    provider: info.model_dump() for provider, info in self.model_names.items()
                }
                # 记录整个 model_names 字段的修改
                self._user_modified_fields.add("model_names")
                logger.info("Saved all models config")

            # 写入配置文件
            with open(self._config_file, "wb") as f:
                tomli_w.dump(user_config, f)
            logger.info(f"Models config saved to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save models config to {self._config_file}: {e}")


# 全局配置实例
config = Config()

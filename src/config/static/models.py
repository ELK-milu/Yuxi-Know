"""
默认模型配置

该文件定义了系统支持的所有默认模型配置，包括：
- 聊天模型（LLM）
- 嵌入模型（Embedding）
- 重排序模型（Reranker）
"""

from pydantic import BaseModel, Field


class ChatModelProvider(BaseModel):
    """聊天模型提供商配置"""

    name: str = Field(..., description="提供商显示名称")
    url: str = Field(..., description="提供商文档或模型列表 URL")
    base_url: str = Field(..., description="API 基础 URL")
    default: str = Field(..., description="默认模型名称")
    env: str = Field(..., description="API Key 环境变量名")
    models: list[str] = Field(default_factory=list, description="支持的模型列表")


class EmbedModelInfo(BaseModel):
    """嵌入模型配置"""

    name: str = Field(..., description="模型名称")
    dimension: int = Field(..., description="向量维度")
    base_url: str = Field(..., description="API 基础 URL")
    api_key: str = Field(..., description="API Key 或环境变量名")


class RerankerInfo(BaseModel):
    """重排序模型配置"""

    name: str = Field(..., description="模型名称")
    base_url: str = Field(..., description="API 基础 URL")
    api_key: str = Field(..., description="API Key 或环境变量名")


# ============================================================
# 默认聊天模型配置
# ============================================================

DEFAULT_CHAT_MODEL_PROVIDERS: dict[str, ChatModelProvider] = {
    "openai": ChatModelProvider(
        name="OpenAI",
        url="https://platform.openai.com/docs/models",
        base_url="https://api.openai.com/v1",
        default="gpt-4o-mini",
        env="OPENAI_API_KEY",
        models=["gpt-4", "gpt-4o", "gpt-4o-mini"],
    ),
    "deepseek": ChatModelProvider(
        name="DeepSeek",
        url="https://platform.deepseek.com/api-docs/zh-cn/pricing",
        base_url="https://api.deepseek.com/v1",
        default="deepseek-chat",
        env="DEEPSEEK_API_KEY",
        models=["deepseek-chat", "deepseek-reasoner"],
    ),
    "zhipu": ChatModelProvider(
        name="智谱AI (Zhipu)",
        url="https://open.bigmodel.cn/dev/api",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
        default="glm-4.5-flash",
        env="ZHIPUAI_API_KEY",
        models=["glm-4.6", "glm-4.5-air", "glm-4.5-flash"],
    ),
    "siliconflow": ChatModelProvider(
        name="SiliconFlow",
        url="https://cloud.siliconflow.cn/models",
        base_url="https://api.siliconflow.cn/v1",
        default="deepseek-ai/DeepSeek-V3.2-Exp",
        env="SILICONFLOW_API_KEY",
        models=[
            "deepseek-ai/DeepSeek-V3.2-Exp",
            "Qwen/Qwen3-235B-A22B-Thinking-2507",
            "Qwen/Qwen3-235B-A22B-Instruct-2507",
            "moonshotai/Kimi-K2-Instruct-0905",
            "zai-org/GLM-4.6",
        ],
    ),
    "together.ai": ChatModelProvider(
        name="Together.ai",
        url="https://api.together.ai/models",
        base_url="https://api.together.xyz/v1/",
        default="meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        env="TOGETHER_API_KEY",
        models=["meta-llama/Llama-3.3-70B-Instruct-Turbo-Free"],
    ),
    "dashscope": ChatModelProvider(
        name="阿里百炼 (DashScope)",
        url="https://bailian.console.aliyun.com/?switchAgent=10226727&productCode=p_efm#/model-market",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default="qwen-max-latest",
        env="DASHSCOPE_API_KEY",
        models=[
            "qwen-max-latest",
            "qwen-plus-latest",
            "qwen-turbo-latest",
            "qwen3-235b-a22b-thinking-2507",
            "qwen3-235b-a22b-instruct-2507",
        ],
    ),
    "ark": ChatModelProvider(
        name="豆包（Ark）",
        url="https://console.volcengine.com/ark/region:ark+cn-beijing/model",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default="doubao-seed-1-6-250615",
        env="ARK_API_KEY",
        models=[
            "doubao-seed-1-6-250615",
            "doubao-seed-1-6-thinking-250715",
            "doubao-seed-1-6-flash-250715",
        ],
    ),
    "openrouter": ChatModelProvider(
        name="OpenRouter",
        url="https://openrouter.ai/models",
        base_url="https://openrouter.ai/api/v1",
        default="openai/gpt-4o",
        env="OPENROUTER_API_KEY",
        models=[
            "openai/gpt-4o",
            "x-ai/grok-4",
            "google/gemini-2.5-pro",
            "anthropic/claude-sonnet-4",
        ],
    ),
}


# ============================================================
# 默认嵌入模型配置
# ============================================================

DEFAULT_EMBED_MODELS: dict[str, EmbedModelInfo] = {
    "siliconflow/BAAI/bge-m3": EmbedModelInfo(
        name="BAAI/bge-m3",
        dimension=1024,
        base_url="https://api.siliconflow.cn/v1/embeddings",
        api_key="SILICONFLOW_API_KEY",
    ),
    "siliconflow/Pro/BAAI/bge-m3": EmbedModelInfo(
        name="Pro/BAAI/bge-m3",
        dimension=1024,
        base_url="https://api.siliconflow.cn/v1/embeddings",
        api_key="SILICONFLOW_API_KEY",
    ),
    "siliconflow/Qwen/Qwen3-Embedding-0.6B": EmbedModelInfo(
        name="Qwen/Qwen3-Embedding-0.6B",
        dimension=1024,
        base_url="https://api.siliconflow.cn/v1/embeddings",
        api_key="SILICONFLOW_API_KEY",
    ),
    "vllm/Qwen/Qwen3-Embedding-0.6B": EmbedModelInfo(
        name="Qwen3-Embedding-0.6B",
        dimension=1024,
        base_url="http://localhost:8000/v1/embeddings",
        api_key="no_api_key",
    ),
    "ollama/nomic-embed-text": EmbedModelInfo(
        name="nomic-embed-text",
        dimension=768,
        base_url="http://localhost:11434/api/embed",
        api_key="no_api_key",
    ),
    "ollama/bge-m3": EmbedModelInfo(
        name="bge-m3",
        dimension=1024,
        base_url="http://localhost:11434/api/embed",
        api_key="no_api_key",
    ),
}


# ============================================================
# 默认重排序模型配置
# ============================================================

DEFAULT_RERANKERS: dict[str, RerankerInfo] = {
    "siliconflow/BAAI/bge-reranker-v2-m3": RerankerInfo(
        name="BAAI/bge-reranker-v2-m3",
        base_url="https://api.siliconflow.cn/v1/rerank",
        api_key="SILICONFLOW_API_KEY",
    ),
    "siliconflow/Pro/BAAI/bge-reranker-v2-m3": RerankerInfo(
        name="Pro/BAAI/bge-reranker-v2-m3",
        base_url="https://api.siliconflow.cn/v1/rerank",
        api_key="SILICONFLOW_API_KEY",
    ),
    "vllm/BAAI/bge-reranker-v2-m3": RerankerInfo(
        name="BAAI/bge-reranker-v2-m3",
        base_url="http://localhost:8000/v1/rerank",
        api_key="no_api_key",
    ),
}

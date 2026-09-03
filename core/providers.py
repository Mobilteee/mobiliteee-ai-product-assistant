"""Built-in provider presets for chat and embedding APIs."""


CHAT_PROVIDERS = [
    {
        "label": "OpenAI 官方",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "extra_models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"],
    },
    {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "extra_models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "label": "月之暗面 Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "extra_models": ["moonshot-v1-8k", "moonshot-v1-32k", "kimi-latest"],
    },
    {
        "label": "阿里通义千问 DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "extra_models": ["qwen-plus", "qwen-max", "qwen-turbo"],
    },
    {
        "label": "智谱 BigModel",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "extra_models": ["glm-4-flash", "glm-4-plus", "glm-4-air"],
    },
    {
        "label": "SiliconFlow 硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "extra_models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct"],
    },
    {
        "label": "中转站 / One-API / 自定义",
        "base_url": "",
        "default_model": "",
        "extra_models": [],
    },
]

CHAT_LABELS = [p["label"] for p in CHAT_PROVIDERS]


EMBED_PROVIDERS = [
    {
        "label": "OpenAI Embedding",
        "base_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
        "extra_models": ["text-embedding-3-small", "text-embedding-3-large"],
    },
    {
        "label": "SiliconFlow Embedding（支持 bge）",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "BAAI/bge-m3",
        "extra_models": ["BAAI/bge-m3", "BAAI/bge-large-zh-v1.5"],
    },
    {
        "label": "DashScope Embedding",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "text-embedding-v3",
        "extra_models": ["text-embedding-v3", "text-embedding-v2"],
    },
    {
        "label": "自定义 Embedding 地址",
        "base_url": "",
        "default_model": "",
        "extra_models": [],
    },
]

EMBED_LABELS = [p["label"] for p in EMBED_PROVIDERS]


def chat_preset(label: str) -> dict:
    for item in CHAT_PROVIDERS:
        if item["label"] == label:
            return dict(item)
    return {"label": label, "base_url": "", "default_model": "", "extra_models": []}


def embed_preset(label: str) -> dict:
    for item in EMBED_PROVIDERS:
        if item["label"] == label:
            return dict(item)
    return {"label": label, "base_url": "", "default_model": "", "extra_models": []}

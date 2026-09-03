import os
from pathlib import Path

import streamlit as st

from core import exporters, providers, rag, storage


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = storage.init_db(DATA_DIR)

st.set_page_config(
    page_title="AI 产品知识助手",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------- 免填 Key 演示通道配置（管理员在 Streamlit Secrets 配置）----------
def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name, default)


DEMO_CHAT_API_KEY = _secret("DEMO_CHAT_API_KEY")
DEMO_CHAT_BASE_URL = _secret("DEMO_CHAT_BASE_URL", "https://api.deepseek.com/v1")
DEMO_CHAT_MODEL = _secret("DEMO_CHAT_MODEL", "deepseek-chat")
DEMO_EMBED_API_KEY = _secret("DEMO_EMBED_API_KEY")
DEMO_EMBED_BASE_URL = _secret("DEMO_EMBED_BASE_URL", "")
DEMO_EMBED_MODEL = _secret("DEMO_EMBED_MODEL", "")


def seed_demo_account():
    if not any(u["username"] == "demo" for u in storage.list_users(DB_PATH)):
        storage.register_user(DB_PATH, "demo", "demo1234")


seed_demo_account()


# ---------- 配置初始状态 ----------
def init_state():
    defaults = {
        "current_user": None,
        "api_mode": "demo",
        "chat_provider_label": providers.CHAT_LABELS[1],
        "chat_base_url": "",
        "chat_model": "",
        "chat_api_key": "",
        "embed_enabled": False,
        "embed_provider_label": providers.EMBED_LABELS[0],
        "embed_base_url": "",
        "embed_model": "",
        "embed_api_key": "",
        "conversation_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # 保证对话默认值跟提供商联动
    preset = providers.chat_preset(st.session_state["chat_provider_label"])
    if preset["base_url"] and not st.session_state["chat_base_url"]:
        st.session_state["chat_base_url"] = preset["base_url"]
    if preset["default_model"] and not st.session_state["chat_model"]:
        st.session_state["chat_model"] = preset["default_model"]

    # 保证 Embedding 配置有合理默认值
    embed_preset = providers.embed_preset(st.session_state["embed_provider_label"])
    if embed_preset["base_url"] and not st.session_state["embed_base_url"]:
        st.session_state["embed_base_url"] = embed_preset["base_url"]
    if embed_preset["default_model"] and not st.session_state["embed_model"]:
        st.session_state["embed_model"] = embed_preset["default_model"]


init_state()


def _apply_chat_preset():
    preset = providers.chat_preset(st.session_state["chat_provider_label"])
    if preset["base_url"]:
        st.session_state["chat_base_url"] = preset["base_url"]
    if preset["default_model"]:
        st.session_state["chat_model"] = preset["default_model"]


def _apply_embed_preset():
    preset = providers.embed_preset(st.session_state["embed_provider_label"])
    if preset["base_url"]:
        st.session_state["embed_base_url"] = preset["base_url"]
    if preset["default_model"]:
        st.session_state["embed_model"] = preset["default_model"]


def resolve_chat_cfg() -> dict:
    if st.session_state["api_mode"] == "demo":
        return {
            "api_key": DEMO_CHAT_API_KEY,
            "base_url": DEMO_CHAT_BASE_URL,
            "model": DEMO_CHAT_MODEL,
        }
    return {
        "api_key": st.session_state["chat_api_key"],
        "base_url": st.session_state["chat_base_url"],
        "model": st.session_state["chat_model"],
    }


def resolve_embed_cfg() -> dict:
    if st.session_state["api_mode"] == "demo":
        if DEMO_EMBED_API_KEY and DEMO_EMBED_MODEL:
            return {
                "api_key": DEMO_EMBED_API_KEY,
                "base_url": DEMO_EMBED_BASE_URL,
                "model": DEMO_EMBED_MODEL,
            }
        return {"api_key": "", "base_url": "", "model": ""}
    if not st.session_state["embed_enabled"]:
        return {"api_key": "", "base_url": "", "model": ""}
    return {
        "api_key": st.session_state["embed_api_key"],
        "base_url": st.session_state["embed_base_url"],
        "model": st.session_state["embed_model"],
    }


# ---------- 登录 / 注册 ----------
def require_login():
    if st.session_state.get("current_user"):
        return

    st.markdown(
        """
        <div style="text-align:center; margin: 8vh auto 1rem; max-width: 620px;">
        <h1 style="font-size:2.4rem; margin-bottom:.4rem;">🧠 AI 产品知识助手</h1>
        <p style="color:#666; font-size:1.05rem;">支持 OpenAI / DeepSeek / Kimi / 通义 / 中转站 · BYOK · RAG 知识库</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        mode = st.radio("登录 / 注册", ["登录", "注册"], horizontal=True, label_visibility="collapsed")
        with st.form("auth_form"):
            username = st.text_input("用户名", placeholder="至少 3 个字符")
            password = st.text_input("密码", type="password", placeholder="至少 6 位")
            submitted = st.form_submit_button("登录" if mode == "登录" else "创建账号", use_container_width=True)
        if submitted:
            if mode == "注册":
                ok = storage.register_user(DB_PATH, username, password)
                if not ok:
                    st.error("注册失败：用户名已存在，或用户名/密码不符合要求")
                else:
                    user = storage.authenticate_user(DB_PATH, username, password)
                    st.session_state["current_user"] = user
                    st.rerun()
            else:
                user = storage.authenticate_user(DB_PATH, username, password)
                if not user:
                    st.error("用户名或密码错误")
                else:
                    st.session_state["current_user"] = user
                    st.rerun()
    st.stop()


require_login()

user = st.session_state["current_user"]
user_id = user["id"]
username = user["username"]


def ensure_conversation():
    if st.session_state.get("conversation_id") is None:
        conv_id = storage.create_conversation(DB_PATH, user_id, "新的会话")
        st.session_state["conversation_id"] = conv_id
    return st.session_state["conversation_id"]


conversation_id = ensure_conversation()


def get_kb() -> dict:
    return rag.load_kb(DATA_DIR, user_id)


# ---------- 侧边栏 ----------
with st.sidebar:
    st.markdown(f"**👤 {username}**")
    if st.button("退出登录", use_container_width=True):
        for key in ["current_user", "api_key", "conversation_id"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    st.markdown("### ⚙️ 模型接入")
    api_mode = st.radio(
        "使用模式",
        ["体验通道（免 Key）", "BYOK（我自己的 Key / 中转站）"],
        index=0 if st.session_state["api_mode"] == "demo" else 1,
        label_visibility="collapsed",
    )
    st.session_state["api_mode"] = "demo" if "体验" in api_mode else "byok"

    if st.session_state["api_mode"] == "demo":
        st.success("演示通道已就绪" if DEMO_CHAT_API_KEY else "未配置演示通道")
        if not DEMO_CHAT_API_KEY:
            with st.expander("部署者配置方法"):
                st.code(
                    "DEMO_CHAT_API_KEY=你的key\n"
                    "DEMO_CHAT_BASE_URL=https://api.deepseek.com/v1\n"
                    "DEMO_CHAT_MODEL=deepseek-chat\n\n"
                    "# 可选：向量 Embedding（没有则自动用关键词检索）\n"
                    "DEMO_EMBED_API_KEY=你的key\n"
                    "DEMO_EMBED_BASE_URL=https://api.siliconflow.cn/v1\n"
                    "DEMO_EMBED_MODEL=BAAI/bge-m3",
                    language="text",
                )
                st.caption("在 Streamlit 的 Settings → Secrets 中配置")
    else:
        chat_idx = providers.CHAT_LABELS.index(st.session_state["chat_provider_label"])
        st.selectbox(
            "对话服务商",
            providers.CHAT_LABELS,
            index=chat_idx,
            key="chat_provider_label",
            on_change=_apply_chat_preset,
        )
        st.text_input("API Base URL", key="chat_base_url", placeholder="https://api.xxx.com/v1")
        st.text_input("模型名称", key="chat_model", placeholder="deepseek-chat / gpt-4o-mini")
        st.text_input("API Key", type="password", key="chat_api_key", placeholder="sk-...")
        st.caption("Key 仅存当前浏览器会话，不写入服务器")

    st.divider()
    with st.expander("🧩 检索模式（Embedding）", expanded=not st.session_state["embed_enabled"]):
        st.caption("不配置 Embedding 时自动使用关键词检索，任何聊天模型都能用。")
        st.toggle("启用向量 Embedding（更精准）", key="embed_enabled")
        if st.session_state["embed_enabled"]:
            if st.session_state["api_mode"] == "demo":
                st.info("使用演示通道的 Embedding 配置" if DEMO_EMBED_API_KEY else "演示通道未配置 Embedding，将自动降级为关键词检索")
            else:
                embed_idx = providers.EMBED_LABELS.index(
                    st.session_state["embed_provider_label"]
                )
                st.selectbox(
                    "Embedding 服务",
                    providers.EMBED_LABELS,
                    index=embed_idx,
                    key="embed_provider_label",
                    on_change=_apply_embed_preset,
                )
                reuse = st.checkbox("复用上方对话 API Key", value=True)
                if reuse:
                    st.session_state["embed_api_key"] = st.session_state["chat_api_key"]
                    if st.session_state["embed_api_key"] and not st.session_state.get(
                        "embed_base_url"
                    ):
                        st.session_state["embed_base_url"] = st.session_state[
                            "chat_base_url"
                        ]
                else:
                    st.text_input("Embedding API Key", type="password", key="embed_api_key")
                    st.text_input("Embedding Base URL", key="embed_base_url")
                    st.text_input("Embedding 模型", key="embed_model")

    st.divider()
    st.markdown("### 📁 文档知识库")
    files = st.file_uploader(
        "上传 PRD / 竞品 / 报告（PDF/DOCX/MD/TXT）",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    chat_cfg = resolve_chat_cfg()
    can_parse = bool(chat_cfg["api_key"]) and bool(files)
    if st.button("解析并建立索引", disabled=not can_parse, use_container_width=True):
        embed_cfg = resolve_embed_cfg()
        try:
            count, mode = rag.save_kb(
                DATA_DIR,
                user_id,
                chat_cfg["api_key"],
                files,
                base_url=chat_cfg["base_url"],
                embed_model=embed_cfg["model"],
                embed_api_key=embed_cfg["api_key"],
                embed_base_url=embed_cfg["base_url"],
            )
            suffix = "向量检索" if mode == "vector" else "关键词检索（免费降级）"
            st.success(f"已索引 {count} 个片段 · {suffix}")
        except Exception as exc:
            st.error(f"解析失败：{exc}")

    kb = get_kb()
    if kb["chunks"]:
        st.success(f"知识库就绪：{len(kb['chunks'])} 个片段 · {kb['mode']}")
    else:
        st.info("知识库为空，上传文档后即可提问。")

    st.divider()
    st.markdown("### 💬 会话记录")
    conversations = storage.list_conversations(DB_PATH, user_id)
    if conversations:
        labels = [f"{c['title']}（{c['message_count']}条）" for c in conversations]
        conv_ids = [c["id"] for c in conversations]
        current_index = (
            conv_ids.index(conversation_id) if conversation_id in conv_ids else 0
        )
        selected_label = st.selectbox(
            "选择会话", labels, index=current_index, label_visibility="collapsed"
        )
        selected_id = conv_ids[labels.index(selected_label)]
        st.session_state["conversation_id"] = selected_id
        if st.button("新建会话", use_container_width=True):
            new_id = storage.create_conversation(DB_PATH, user_id, "新的会话")
            st.session_state["conversation_id"] = new_id
            st.rerun()
        if st.button("🗑️ 删除当前", use_container_width=True):
            storage.delete_conversation(DB_PATH, selected_id)
            remaining = storage.list_conversations(DB_PATH, user_id)
            st.session_state["conversation_id"] = (
                remaining[0]["id"] if remaining else None
            )
            st.rerun()
    else:
        st.caption("暂无历史会话")
        if st.button("新建会话", use_container_width=True):
            st.session_state["conversation_id"] = storage.create_conversation(
                DB_PATH, user_id, "新的会话"
            )
            st.rerun()


conversation_id = st.session_state.get("conversation_id")
if conversation_id is None:
    conversation_id = storage.create_conversation(DB_PATH, user_id, "新的会话")
    st.session_state["conversation_id"] = conversation_id


# ---------- 主界面 ----------
title = storage.get_conversation_title(DB_PATH, conversation_id)
chat_cfg = resolve_chat_cfg()
embed_cfg = resolve_embed_cfg()
ready = bool(chat_cfg["api_key"])

header_col, action_col = st.columns([3, 1.5])
with header_col:
    new_title = st.text_input("会话标题", value=title, label_visibility="collapsed")
    if new_title and new_title != title:
        storage.rename_conversation(DB_PATH, conversation_id, new_title)
        title = new_title
    mode_note = (
        f"{st.session_state['chat_provider_label']} · {chat_cfg['model']}"
        if st.session_state["api_mode"] == "byok"
        else "演示通道"
    )
    st.caption(f"当前会话 · {username} · {mode_note}")

messages = storage.list_messages(DB_PATH, conversation_id)

with action_col:
    if messages:
        md_bytes = exporters.messages_to_markdown(title, messages).encode("utf-8")
        st.download_button(
            "⬇️ 导出 Markdown",
            data=md_bytes,
            file_name=f"{title}.md",
            use_container_width=True,
        )
        try:
            pdf_bytes = exporters.text_to_pdf_bytes(title, md_bytes.decode("utf-8"))
            st.download_button(
                "⬇️ 导出 PDF",
                data=pdf_bytes,
                file_name=f"{title}.pdf",
                use_container_width=True,
            )
        except Exception as exc:
            st.warning(f"PDF 导出不可用：{exc}")


for msg in messages:
    with st.chat_message("user" if msg["role"] == "user" else "assistant"):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("📚 引用来源"):
                for source in msg["sources"]:
                    st.write(f"`{source['source']}`（相关度 {source['score']}）")
                    st.caption(source["excerpt"])


def add_and_render(role, content, sources=None):
    storage.add_message(DB_PATH, conversation_id, role, content, sources)


kb = get_kb()

if st.button("✨ 生成 PRD 诊断与改进建议", disabled=not (ready and kb["chunks"])):
    with st.spinner("正在基于你的文档生成诊断建议..."):
        try:
            report = rag.generate_suggestions(
                chat_cfg["api_key"],
                kb,
                base_url=chat_cfg["base_url"],
                model=chat_cfg["model"],
            )
            st.session_state["last_report"] = report
            with st.chat_message("assistant"):
                st.markdown(report)
            report_md = exporters.suggestion_to_markdown(report)
            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button(
                    "⬇️ 下载建议报告 (MD)",
                    data=report_md.encode("utf-8"),
                    file_name="PRD诊断建议.md",
                )
            with col_b:
                try:
                    pdf_bytes = exporters.text_to_pdf_bytes("PRD 诊断建议", report_md)
                    st.download_button(
                        "⬇️ 下载建议报告 (PDF)",
                        data=pdf_bytes,
                        file_name="PRD诊断建议.pdf",
                    )
                except Exception:
                    st.warning("PDF 导出不可用，可使用 Markdown 导出")
        except Exception as exc:
            st.error(f"生成失败：{exc}")


def send_question(question: str):
    add_and_render("user", question)
    with st.spinner("检索知识库并生成回答..."):
        history_for_llm = [
            {"role": m["role"], "content": m["content"]}
            for m in storage.list_messages(DB_PATH, conversation_id)[-6:]
        ]
        try:
            result = rag.answer(
                chat_cfg["api_key"],
                question,
                kb,
                history=history_for_llm,
                base_url=chat_cfg["base_url"],
                model=chat_cfg["model"],
                embed_model=embed_cfg["model"],
                embed_api_key=embed_cfg["api_key"],
                embed_base_url=embed_cfg["base_url"],
            )
        except ValueError as exc:
            result = {"answer": str(exc), "sources": []}
        except Exception as exc:
            result = {"answer": f"调用出错：{exc}", "sources": []}
    add_and_render("assistant", result["answer"], result.get("sources"))


chat_disabled = not (ready and kb["chunks"])
if prompt := st.chat_input(
    "请输入关于 PRD / 产品 / 面试准备的问题...",
    disabled=chat_disabled,
):
    send_question(prompt)
    st.rerun()


if not ready:
    st.info("请先在左侧配置 API Key，或选择体验通道。")
elif not kb["chunks"]:
    st.info("请在左侧上传文档并点击「解析并建立索引」。")

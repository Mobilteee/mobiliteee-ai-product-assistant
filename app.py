import os
from pathlib import Path

import streamlit as st

from core import exporters, rag, storage


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = storage.init_db(DATA_DIR)

st.set_page_config(
    page_title="AI 产品知识助手",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)


def seed_demo_account():
    if not any(u["username"] == "demo" for u in storage.list_users(DB_PATH)):
        storage.register_user(DB_PATH, "demo", "demo1234")


seed_demo_account()


def require_login():
    if st.session_state.get("current_user"):
        return

    st.markdown(
        """
        <div style="text-align:center; margin: 10vh auto; max-width: 560px;">
        <h1 style="font-size: 2.4rem; margin-bottom: 0.4rem;">🧠 AI 产品知识助手</h1>
        <p style="color:#666; font-size:1.05rem;">多用户 · BYOK · RAG 知识库 · 诊断建议 · 报告导出</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        mode = st.radio("登录 / 注册", ["登录", "注册"], horizontal=True, label_visibility="collapsed")
        with st.form("auth_form", clear_on_submit=False):
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
api_key = st.session_state.get("api_key", "")


def ensure_conversation():
    if st.session_state.get("conversation_id") is None:
        conv_id = storage.create_conversation(DB_PATH, user_id, "新的会话")
        st.session_state["conversation_id"] = conv_id
    return st.session_state["conversation_id"]


conversation_id = ensure_conversation()


def get_kb():
    return rag.load_kb(DATA_DIR, user_id)


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown(f"**👤 {username}**")
    if st.button("退出登录", use_container_width=True):
        for key in ["current_user", "api_key", "conversation_id"]:
            st.session_state.pop(key, None)
        st.rerun()

    st.divider()
    st.markdown("### 🔑 你的 API Key（BYOK）")
    st.caption("Key 仅保存在本次浏览器会话，不会写入服务器或数据库。")
    new_key = st.text_input(
        "OpenAI API Key",
        type="password",
        value=api_key,
        placeholder="sk-...",
        label_visibility="collapsed",
    )
    if new_key and new_key != api_key:
        api_key = new_key
        st.session_state["api_key"] = new_key
        st.success("已保存到当前会话")

    st.divider()
    st.markdown("### 📁 文档知识库")
    files = st.file_uploader(
        "上传 PRD / 竞品 / 报告",
        type=["pdf", "docx", "md", "txt"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if st.button("解析并建立索引", disabled=not (api_key and files), use_container_width=True):
        try:
            count = rag.save_kb(DATA_DIR, user_id, api_key, files)
            st.success(f"已索引 {count} 个片段")
            st.session_state["kb_updated"] = True
        except Exception as exc:
            st.error(f"解析失败：{exc}")

    kb_chunks = get_kb()
    if kb_chunks:
        st.success(f"知识库就绪：{len(kb_chunks)} 个片段")
    else:
        st.info("知识库为空，上传文档后即可提问。")

    st.divider()
    st.markdown("### 💬 会话记录")
    conversations = storage.list_conversations(DB_PATH, user_id)
    if conversations:
        labels = [f"{c['title']}（{c['message_count']}条）" for c in conversations]
        conv_ids = [c["id"] for c in conversations]
        current_index = conv_ids.index(conversation_id) if conversation_id in conv_ids else 0
        selected_label = st.selectbox(
            "选择会话",
            labels,
            index=current_index,
            label_visibility="collapsed",
        )
        selected_id = conv_ids[labels.index(selected_label)]
        st.session_state["conversation_id"] = selected_id
        if st.button("新建会话", use_container_width=True):
            new_id = storage.create_conversation(DB_PATH, user_id, "新的会话")
            st.session_state["conversation_id"] = new_id
            st.rerun()

        col_del, _ = st.columns([1, 1])
        if col_del.button("🗑️ 删除当前", use_container_width=True):
            storage.delete_conversation(DB_PATH, selected_id)
            remaining = storage.list_conversations(DB_PATH, user_id)
            if remaining:
                st.session_state["conversation_id"] = remaining[0]["id"]
            else:
                st.session_state["conversation_id"] = None
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


# ---------------- Main area ----------------
title = storage.get_conversation_title(DB_PATH, conversation_id)

header_col, action_col = st.columns([3, 1.5])
with header_col:
    new_title = st.text_input("会话标题", value=title, label_visibility="collapsed")
    if new_title and new_title != title:
        storage.rename_conversation(DB_PATH, conversation_id, new_title)
        title = new_title
    st.caption(f"当前会话 · {username} · BYOK")

messages = storage.list_messages(DB_PATH, conversation_id)

with action_col:
    if messages:
        md_bytes = exporters.messages_to_markdown(title, messages).encode("utf-8")
        st.download_button("⬇️ 导出 Markdown", data=md_bytes, file_name=f"{title}.md", use_container_width=True)
        try:
            pdf_bytes = exporters.text_to_pdf_bytes(title, md_bytes.decode("utf-8"))
            st.download_button("⬇️ 导出 PDF", data=pdf_bytes, file_name=f"{title}.pdf", use_container_width=True)
        except Exception as exc:
            st.warning(f"PDF 导出不可用：{exc}")


chat_container = st.container()
with chat_container:
    for msg in messages:
        role = "🧑 用户" if msg["role"] == "user" else "🧠 助手"
        with st.chat_message("user" if msg["role"] == "user" else "assistant"):
            st.markdown(msg["content"])
            if msg.get("sources"):
                with st.expander("📚 引用来源"):
                    for source in msg["sources"]:
                        st.write(f"`{source['source']}`（相关度 {source['score']}）")
                        st.caption(source["excerpt"])


def add_and_render(role, content, sources=None):
    storage.add_message(DB_PATH, conversation_id, role, content, sources)


if st.button("✨ 生成 PRD 诊断与改进建议", disabled=not (api_key and kb_chunks)):
    with st.spinner("正在基于你的文档生成诊断建议..."):
        try:
            report = rag.generate_suggestions(api_key, kb_chunks)
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
            result = rag.answer(api_key, question, kb_chunks, history=history_for_llm)
        except ValueError as exc:
            result = {"answer": str(exc), "sources": []}
        except Exception as exc:
            result = {"answer": f"调用出错：{exc}", "sources": []}
    add_and_render("assistant", result["answer"], result.get("sources"))


if prompt := st.chat_input(
    "请输入关于你的 PRD / 产品 / 面试准备问题...",
    disabled=not (api_key and kb_chunks),
):
    send_question(prompt)
    st.rerun()


if not api_key:
    st.info("请在左侧输入你的 OpenAI API Key（BYOK），开始使用。")
elif not kb_chunks:
    st.info("请在左侧上传文档并点击「解析并建立索引」。")

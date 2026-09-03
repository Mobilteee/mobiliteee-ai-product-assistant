import streamlit as st
from langchain_community.document_loaders import UnstructuredFileLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_community.vectorstores import Chroma
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
import os
import tempfile

st.set_page_config(page_title="AI 知识库助手", page_icon="", layout="wide")

st.title(" AI 知识库助手")
st.caption("面向 AI 产品岗的专业知识问答系统 | V1.0")

# 侧边栏：API Key + 文档上传
with st.sidebar:
    st.header("⚙️ 配置")
    openai_api_key = st.text_input("OpenAI API Key", type="password", placeholder="sk-...")
    st.caption("🔒 你的 Key 仅存储在本地浏览器会话中，不会上传到服务器")

    st.subheader(" 文档上传")
    uploaded_files = st.file_uploader(
        "上传 PRD / 竞品分析 / 行业报告",
        accept_multiple_files=True,
        type=["pdf", "docx", "md"]
    )

    if uploaded_files and openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key
        with st.spinner("正在解析文档并构建向量索引..."):
            documents = []
            for file in uploaded_files:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.name)[1]) as tmp:
                    tmp.write(file.getbuffer())
                    tmp_path = tmp.name
                loader = UnstructuredFileLoader(tmp_path)
                docs = loader.load()
                documents.extend(docs)
                os.remove(tmp_path)

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=200, length_function=len,
            )
            splits = text_splitter.split_documents(documents)

            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            vectorstore = Chroma.from_documents(splits, embeddings)
            retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

            def format_docs(docs):
                return "\n\n".join(
                    f"📄 {doc.metadata.get('source', '文档')}:\n{doc.page_content}"
                    for doc in docs
                )

            template = (
                "你是一个 AI 产品专家，请严格基于以下上下文回答问题。\n"
                "如果上下文中没有相关信息，请明确说明。\n\n"
                "上下文：\n{context}\n\n"
                "问题：{question}\n\n"
                "请用专业但简洁的方式回答，并在末尾标注引用来源。"
            )
            prompt = ChatPromptTemplate.from_template(template)

            chain = (
                {"context": retriever | format_docs, "question": RunnablePassthrough()}
                | prompt
                | ChatOpenAI(model="gpt-4o-mini", temperature=0)
                | StrOutputParser()
            )

            st.session_state.qa_chain = chain
            st.session_state.retriever = retriever
            st.success(f"✅ 成功处理 {len(uploaded_files)} 个文档，共 {len(splits)} 个文本块")

# 主界面：聊天
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "你好！我是 AI 产品知识助手。\n\n1️⃣ 在左侧输入你的 OpenAI API Key\n2️⃣ 上传 PRD / 竞品分析 / 行业报告\n3️⃣ 向我提问，我会基于文档内容回答并标注来源"}
    ]

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt_text := st.chat_input("关于 AI 产品岗的问题..."):
    st.session_state.messages.append({"role": "user", "content": prompt_text})
    with st.chat_message("user"):
        st.markdown(prompt_text)

    with st.chat_message("assistant"):
        if "qa_chain" not in st.session_state:
            error_msg = "️ 请先在左侧输入 API Key 并上传文档"
            st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        else:
            with st.spinner("检索文档并生成回答..."):
                try:
                    answer = st.session_state.qa_chain.invoke(prompt_text)
                    # 额外获取引用来源
                    docs = st.session_state.retriever.invoke(prompt_text)
                    sources = "\n".join(
                        f"- 📄 **来源 {i+1}**: `{doc.metadata.get('source', '未知')}`"
                        for i, doc in enumerate(docs)
                    )
                    full_response = f"{answer}\n\n---\n**参考资料**:\n{sources}"
                except Exception as e:
                    full_response = f"❌ 调用出错：{str(e)}\n\n请检查 API Key 是否正确，或稍后重试。"

            st.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})

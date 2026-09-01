import streamlit as st
 from langchain_community.document_loaders import UnstructuredFileLoader
 from langchain.text_splitter import RecursiveCharacterTextSplitter
 from langchain_openai import OpenAIEmbeddings
 from langchain_community.vectorstores import Chroma
 from langchain.chains import RetrievalQA
 from langchain_openai import ChatOpenAI
 from langchain_core.runnables import RunnablePassthrough
 from langchain_core.output_parsers import StrOutputParser
 from langchain_core.prompts import ChatPromptTemplate
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

st.set_page_config(page_title="AI 知识库助手", page_icon="🧠", layout="wide")

st.title("🧠 AI 知识库助手")
st.caption("面向 AI 产品岗的专业知识问答系统 | V1.0")

# 初始化向量数据库
@st.cache_resource
def initialize_vectorstore(uploaded_files):
    documents = []
    for file in uploaded_files:
        with open(f"temp_{file.name}", "wb") as f:
            f.write(file.getbuffer())
        loader = UnstructuredFileLoader(f"temp_{file.name}")
        docs = loader.load()
        documents.extend(docs)
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )
    splits = text_splitter.split_documents(documents)
    
    embeddings = OpenAIEmbeddings()
    vectorstore = Chroma.from_documents(splits, embeddings, persist_directory="./vectorstore")
    
    # 清理临时文件
    for file in uploaded_files:
        os.remove(f"temp_{file.name}")
    
    return vectorstore

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置")
    openai_api_key = st.text_input("OpenAI API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
    
    st.subheader("📂 文档上传")
    uploaded_files = st.file_uploader(
        "上传 PRD/竞品分析/行业报告",
        accept_multiple_files=True,
        type=["pdf", "docx", "md"]
    )
    
    if uploaded_files and openai_api_key:
        os.environ["OPENAI_API_KEY"] = openai_api_key
        with st.spinner("正在处理文档..."):
            vectorstore = initialize_vectorstore(uploaded_files)
            retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
            llm = ChatOpenAI(model_name="gpt-4o", temperature=0)
            # 新增文档格式化函数（解决LangChain 0.2.14+的上下文格式问题）
            def format_docs(docs):
                return "\n\n".join([f"📄 {doc.metadata.get('source', '文档')}:\n{doc.page_content}" for doc in docs])
            
            # 使用新式LangChain链构建方式（兼容0.2.14+）
            template = """你是一个AI产品专家，请基于以下上下文回答问题：
            {context}
            
            问题：{question}
            请用专业但简洁的方式回答，并标注引用来源。"""
            prompt = ChatPromptTemplate.from_template(template)
            
            chain = (
                {"context": retriever | format_docs, "question": RunnablePassthrough()}
                | prompt
                | llm
                | StrOutputParser()
            )
            
            st.session_state.chain = chain
            st.success(f"成功处理 {len(uploaded_files)} 个文档！")

# 主界面
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "你好！我是 AI 产品知识助手。请上传 PRD 或行业文档，然后向我提问。"}
    ]

# 显示聊天记录
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 用户输入
if prompt := st.chat_input("关于 AI 产品岗的问题..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            if "qa_chain" in st.session_state:
                response = st.session_state.qa_chain({"query": prompt})
                
                # 格式化显示引用来源
                sources = "\n".join([
                    f"📄 **来源 {i+1}**: {doc.metadata.get('source', '未知')}\n   > {doc.page_content[:200]}..."
                    for i, doc in enumerate(response["source_documents"])
                ])
                
                full_response = f"{response['result']}\n\n---\n**参考资料**:\n{sources}"
                st.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
            else:
                error_msg = "⚠️ 请先上传文档并配置 API Key"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})

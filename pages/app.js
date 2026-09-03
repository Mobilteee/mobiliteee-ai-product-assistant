import { useState, useRef } from 'react';
import { motion } from 'framer-motion';
import Head from 'next/head';

export default function App() {
  const [files, setFiles] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState([
    { role: 'assistant', content: '你好！我是AI产品知识助手。请上传PRD文档或行业报告，然后向我提问。' }
  ]);
  const [input, setInput] = useState('');
  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleFileUpload = (e) => {
    const uploadedFiles = Array.from(e.target.files);
    setFiles(prev => [...prev, ...uploadedFiles]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    // 添加用户消息
    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // 模拟API调用（实际部署时替换为真实API）
      const response = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: input,
          files: files.map(f => f.name)
        })
      });

      const data = await response.json();
      
      // 添加助手回复
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.answer,
        sources: data.sources
      }]);
    } catch (error) {
      console.error('API调用失败:', error);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: '抱歉，处理请求时出错。请检查网络连接或稍后重试。'
      }]);
    } finally {
      setIsLoading(false);
      scrollToBottom();
    }
  };

  return (
    <>
      <Head>
        <title>AI产品知识助手 | RAG系统演示</title>
      </Head>

      <motion.div 
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="min-h-screen bg-gray-50"
      >
        {/* 顶部导航 */}
        <header className="bg-white shadow-sm">
          <div className="container mx-auto px-4 py-3 flex justify-between items-center">
            <a href="/" className="flex items-center space-x-2">
              <span className="text-2xl">🧠</span>
              <span className="text-xl font-bold text-indigo-600">产品知识助手</span>
            </a>
            <button 
              onClick={() => fileInputRef.current.click()}
              className="bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700 transition"
            >
              上传文档
            </button>
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileUpload}
              multiple
              accept=".pdf,.docx,.md"
              className="hidden"
            />
          </div>
        </header>

        {/* 文档状态栏 */}
        {files.length > 0 && (
          <div className="container mx-auto px-4 py-2">
            <div className="bg-white p-3 rounded-lg shadow">
              <h3 className="font-medium text-gray-700 mb-2">已上传文档 ({files.length})</h3>
              <div className="flex flex-wrap gap-2">
                {files.map((file, index) => (
                  <span 
                    key={index}
                    className="bg-indigo-50 text-indigo-700 px-3 py-1 rounded-full text-sm"
                  >
                    {file.name}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* 聊天界面 */}
        <main className="container mx-auto px-4 py-6 max-w-3xl">
          <div className="bg-white rounded-2xl shadow overflow-hidden">
            <div className="h-[60vh] overflow-y-auto p-4 space-y-4" style={{ scrollbarWidth: 'thin' }}>
              {messages.map((msg, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 ${
                      msg.role === 'user' 
                        ? 'bg-indigo-600 text-white rounded-br-none' 
                        : 'bg-gray-100 text-gray-800 rounded-bl-none'
                    }`}
                  >
                    <p>{msg.content}</p>
                    {msg.sources && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        <h4 className="text-sm font-medium text-gray-600 mb-1">参考资料：</h4>
                        {msg.sources.map((source, i) => (
                          <p key={i} className="text-xs text-gray-500 truncate">
                            📄 {source}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                </motion.div>
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* 输入区域 */}
            <div className="border-t p-3 bg-white">
              <form onSubmit={handleSubmit} className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="关于AI产品的专业问题..."
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  disabled={isLoading}
                />
                <button
                  type="submit"
                  disabled={isLoading}
                  className={`px-4 py-2 bg-indigo-600 text-white rounded-lg ${
                    isLoading ? 'opacity-50 cursor-not-allowed' : 'hover:bg-indigo-700'
                  } transition`}
                >
                  {isLoading ? '思考中...' : '发送'}
                </button>
              </form>
              <p className="text-xs text-gray-500 mt-2 text-center">
                提示：上传PRD文档后提问 "如何设计RAG系统的验收标准？"
              </p>
            </div>
          </div>
        </main>
      </motion.div>
    </>
  );
}

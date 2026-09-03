import { motion } from 'framer-motion';
import Head from 'next/head';

export default function Home() {
  return (
    <>
      <Head>
        <title>AI Product Knowledge Assistant</title>
        <meta name="description" content="RAG-powered knowledge assistant for AI product roles" />
      </Head>
      
      <motion.div 
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5 }}
        className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100"
      >
        {/* Hero Section */}
        <motion.section
          initial={{ y: 20, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="container mx-auto px-4 py-16"
        >
          <div className="text-center max-w-3xl mx-auto">
            <motion.h1 
              initial={{ scale: 0.9 }}
              animate={{ scale: 1 }}
              className="text-4xl md:text-6xl font-bold text-gray-900 mb-6"
            >
              AI Product <span className="text-indigo-600">Knowledge Assistant</span>
            </motion.h1>
            <motion.p 
              initial={{ y: 10, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.4 }}
              className="text-xl text-gray-600 mb-10"
            >
              Your RAG-powered companion for AI product interviews, PRD writing, and technical documentation
            </motion.p>
            
            <motion.div
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="inline-block"
            >
              <a 
                href="/app"
                className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-3 px-8 rounded-xl shadow-lg transition-colors"
              >
                Launch Application →
              </a>
            </motion.div>
          </div>
        </motion.section>
        
        {/* Features Section */}
        <motion.section
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true }}
          className="py-16 bg-white"
        >
          <div className="container mx-auto px-4">
            <h2 className="text-3xl font-bold text-center text-gray-900 mb-12">Key Features</h2>
            
            <div className="grid md:grid-cols-3 gap-8">
              {features.map((feature, index) => (
                <FeatureCard key={index} {...feature} index={index} />
              ))}
            </div>
          </div>
        </motion.section>
      </motion.div>
    </>
  );
}

const FeatureCard = ({ title, description, icon, index }) => (
  <motion.div
    initial={{ y: 20, opacity: 0 }}
    whileInView={{ y: 0, opacity: 1 }}
    transition={{ delay: index * 0.1 }}
    viewport={{ once: true }}
    className="bg-gray-50 p-6 rounded-xl border border-gray-100 hover:shadow-md transition-shadow"
  >
    <div className="text-indigo-600 text-3xl mb-4">{icon}</div>
    <h3 className="text-xl font-semibold text-gray-900 mb-2">{title}</h3>
    <p className="text-gray-600">{description}</p>
  </motion.div>
);

const features = [
  {
    title: "RAG-Powered Insights",
    description: "Ask questions about PRDs, technical specifications, and AI product concepts with citation-based answers",
    icon: "🔍",
    index: 0
  },
  {
    title: "PRD Template Generator",
    description: "Generate structured product requirement documents with industry-standard sections and examples",
    icon: "📝",
    index: 1
  },
  {
    title: "Interview Prep",
    description: "Practice AI product interview questions with expert-level answers and talking points",
    icon: "🎯",
    index: 2
  }
];

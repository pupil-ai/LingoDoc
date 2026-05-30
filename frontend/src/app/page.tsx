'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import { useRouter } from 'next/navigation';
import { Header } from '@/components/Header';
import { FileUploader } from '@/components/FileUploader';
import { LanguageSelector } from '@/components/LanguageSelector';
import { FeatureCard } from '@/components/FeatureCard';
import { uploadFile } from '@/lib/api';

export default function Home() {
  const router = useRouter();
  const [sourceLang, setSourceLang] = useState('en');
  const [targetLang, setTargetLang] = useState('zh');
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState('');

  const handleFileUpload = async (file: File) => {
    setIsUploading(true);
    setError('');

    try {
      const response = await uploadFile(file);
      if (response.success) {
        const params = new URLSearchParams({
          fileId: response.fileId,
          sourceLang,
          targetLang,
        });
        router.push(`/translate?${params.toString()}`);
      } else {
        setError('Failed to upload file');
      }
    } catch (err) {
      setError('An error occurred during upload. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50">
      <Header />

      <section className="max-w-6xl mx-auto px-4 py-16">
        <motion.div
          className="text-center mb-12"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <motion.div
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary-100 rounded-full text-primary-700 text-sm font-medium mb-6"
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ delay: 0.2, type: 'spring' }}
          >
            <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            Supports large PDF files up to 3000 pages
          </motion.div>
          <h1 className="font-display text-4xl md:text-5xl lg:text-6xl font-bold text-gray-900 mb-6">
            Translate PDF Documents
            <br />
            <span className="gradient-text">Easily & Accurately</span>
          </h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Upload your PDF files, select your languages, and get accurate translations
            while preserving the original layout. Perfect for academic papers, technical documents, and more.
          </p>
        </motion.div>

        <motion.div
          className="bg-white/70 backdrop-blur-sm rounded-3xl p-8 shadow-xl border border-white/50 mb-16"
          initial={{ opacity: 0, y: 30 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
        >
          <div className="mb-8">
            <LanguageSelector
              sourceLang={sourceLang}
              targetLang={targetLang}
              onSourceLangChange={setSourceLang}
              onTargetLangChange={setTargetLang}
              disabled={isUploading}
            />
          </div>

          <FileUploader onFileUpload={handleFileUpload} disabled={isUploading} />

          {error && (
            <motion.p
              className="mt-4 text-center text-red-500"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              {error}
            </motion.p>
          )}
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <FeatureCard
            icon={
              <svg className="w-7 h-7 text-primary-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
            }
            title="Large File Support"
            description="Handles PDF files with up to 3000 pages efficiently, ensuring smooth translation even for academic theses and lengthy documents."
            delay={0.3}
          />
          <FeatureCard
            icon={
              <svg className="w-7 h-7 text-cyan-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            }
            title="Preserve Layout"
            description="Maintains the original document formatting, including fonts, spacing, images, and table structures."
            delay={0.4}
          />
          <FeatureCard
            icon={
              <svg className="w-7 h-7 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.25 15L12 18.75 15.75 15m-7.5-6L12 5.25 15.75 9" />
              </svg>
            }
            title="Bilingual Reading"
            description="View original and translated content side by side with synchronized scrolling for easy comparison."
            delay={0.5}
          />
        </div>
      </section>

      <footer className="bg-white border-t border-gray-100 mt-16">
        <div className="max-w-6xl mx-auto px-4 py-8 text-center text-gray-500 text-sm">
          <p>LingoDoc - Fast, accurate PDF translation service</p>
        </div>
      </footer>
    </div>
  );
}

'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { PageResult } from '@/types';

interface BilingualReaderProps {
  pages: PageResult[];
}

export function BilingualReader({ pages }: BilingualReaderProps) {
  const [currentPage, setCurrentPage] = useState(0);
  const [activeBlockIndex, setActiveBlockIndex] = useState<number | null>(null);
  const leftRef = useRef<HTMLDivElement>(null);
  const rightRef = useRef<HTMLDivElement>(null);

  const currentPageData = pages[currentPage];

  useEffect(() => {
    setCurrentPage(0);
    setActiveBlockIndex(null);
  }, [pages]);

  const handleScroll = useCallback((sourceRef: HTMLDivElement | null, targetRef: HTMLDivElement | null) => {
    if (!sourceRef || !targetRef) return;
    const scrollPercent = sourceRef.scrollTop / (sourceRef.scrollHeight - sourceRef.clientHeight);
    targetRef.scrollTop = scrollPercent * (targetRef.scrollHeight - targetRef.clientHeight);
  }, []);

  const handleLeftScroll = () => {
    handleScroll(leftRef.current, rightRef.current);
  };

  const handleRightScroll = () => {
    handleScroll(rightRef.current, leftRef.current);
  };

  const handleBlockHover = (index: number) => {
    setActiveBlockIndex(index);
  };

  const handleBlockLeave = () => {
    setActiveBlockIndex(null);
  };

  const goToPage = (pageNum: number) => {
    if (pageNum >= 0 && pageNum < pages.length) {
      setCurrentPage(pageNum);
      if (leftRef.current) leftRef.current.scrollTop = 0;
      if (rightRef.current) rightRef.current.scrollTop = 0;
    }
  };

  if (!currentPageData) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="text-gray-500">No pages to display</p>
      </div>
    );
  }

  return (
    <motion.div
      className="w-full"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
    >
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-xl font-semibold text-gray-800">
          Page {currentPage + 1} / {pages.length}
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage === 0}
            className="p-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <span className="text-sm text-gray-500 w-20 text-center">{currentPage + 1}</span>
          <button
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage === pages.length - 1}
            className="p-2 rounded-lg bg-white border border-gray-200 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-2xl shadow-lg p-6">
          <div className="flex items-center gap-2 mb-4 pb-4 border-b border-gray-100">
            <div className="w-3 h-3 rounded-full bg-blue-500" />
            <h4 className="font-semibold text-gray-700">Original</h4>
          </div>
          <div
            ref={leftRef}
            onScroll={handleLeftScroll}
            className="h-[500px] overflow-y-auto pr-2 space-y-4"
          >
            {currentPageData.textBlocks.map((block, index) => (
              <motion.div
                key={`original-${index}`}
                className={`p-4 rounded-xl transition-all duration-200 cursor-pointer ${
                  activeBlockIndex === index
                    ? 'bg-primary-50 border-2 border-primary-200'
                    : 'hover:bg-gray-50'
                }`}
                onMouseEnter={() => handleBlockHover(index)}
                onMouseLeave={handleBlockLeave}
                whileHover={{ scale: 1.01 }}
              >
                <p className="text-gray-800 leading-relaxed whitespace-pre-wrap">{block.text}</p>
              </motion.div>
            ))}
            {currentPageData.textBlocks.length === 0 && (
              <p className="text-gray-400 text-center py-8">{currentPageData.original}</p>
            )}
          </div>
        </div>

        <div className="bg-white rounded-2xl shadow-lg p-6">
          <div className="flex items-center gap-2 mb-4 pb-4 border-b border-gray-100">
            <div className="w-3 h-3 rounded-full bg-green-500" />
            <h4 className="font-semibold text-gray-700">Translation</h4>
          </div>
          <div
            ref={rightRef}
            onScroll={handleRightScroll}
            className="h-[500px] overflow-y-auto pr-2 space-y-4"
          >
            {currentPageData.textBlocks.map((block, index) => (
              <motion.div
                key={`translated-${index}`}
                className={`p-4 rounded-xl transition-all duration-200 cursor-pointer ${
                  activeBlockIndex === index
                    ? 'bg-cyan-50 border-2 border-cyan-200'
                    : 'hover:bg-gray-50'
                }`}
                onMouseEnter={() => handleBlockHover(index)}
                onMouseLeave={handleBlockLeave}
                whileHover={{ scale: 1.01 }}
              >
                <p className="text-gray-800 leading-relaxed whitespace-pre-wrap">{block.translatedText}</p>
              </motion.div>
            ))}
            {currentPageData.textBlocks.length === 0 && (
              <p className="text-gray-400 text-center py-8">{currentPageData.translated}</p>
            )}
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-center justify-center gap-2 flex-wrap">
        {pages.map((_, index) => (
          <button
            key={index}
            onClick={() => goToPage(index)}
            className={`w-10 h-10 rounded-lg font-medium transition-all duration-200 ${
              index === currentPage
                ? 'bg-gradient-to-r from-primary-500 to-cyan-500 text-white shadow-lg'
                : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            {index + 1}
          </button>
        ))}
      </div>
    </motion.div>
  );
}

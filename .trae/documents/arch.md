
## 1. 架构设计

```mermaid
graph TB
    subgraph "前端层"
        A["React + Next.js"]
        B["Tailwind CSS"]
        C["Framer Motion"]
        D["react-pdf"]
    end
    
    subgraph "后端层"
        E["FastAPI"]
        F["PyMuPDF (fitz)"]
        G["翻译服务模块"]
        H["文件管理"]
    end
    
    subgraph "外部服务"
        I["DeepL API"]
        J["Google Translate"]
        K["OpenAI API"]
    end
    
    A --&gt; E
    E --&gt; F
    E --&gt; G
    G --&gt; I
    G --&gt; J
    G --&gt; K
```

## 2. 技术描述
- **前端**：React@18 + Next.js@15 + TypeScript + Tailwind CSS@3 + Framer Motion
- **初始化工具**：create-next-app
- **后端**：Python@3.11 + FastAPI
- **PDF处理**：PyMuPDF (fitz)
- **翻译服务**：支持 DeepL / Google Translate / OpenAI（可配置）
- **文件存储**：本地临时存储

## 3. 路由定义
| 路由 | 用途 |
|------|------|
| / | 首页 - 文件上传 |
| /translate/[id] | 翻译页面 - 进度显示与对照阅读 |
| /result/[id] | 结果页面 - 预览与导出 |

## 4. API 定义

### 4.1 文件上传
```typescript
// POST /api/upload
Request: FormData { file: File }
Response: {
  success: boolean
  fileId: string
  filename: string
  totalPages: number
  fileSize: number
}
```

### 4.2 开始翻译
```typescript
// POST /api/translate
Request: {
  fileId: string
  sourceLang: string
  targetLang: string
}
Response: {
  success: boolean
  taskId: string
}
```

### 4.3 翻译进度
```typescript
// GET /api/translate/[taskId]/progress
Response: {
  status: 'processing' | 'completed' | 'error'
  progress: number
  processedPages: number
  totalPages: number
}
```

### 4.4 获取翻译结果
```typescript
// GET /api/translate/[taskId]/result
Response: {
  success: boolean
  pages: Array<{
    pageNum: number
    original: string
    translated: string
    textBlocks: Array<{
      // 为词语高亮预留位置信息
      bbox: { x0: number, y0: number, x1: number, y1: number }
      text: string
      translatedText: string
    }>
  }>
}
```

### 4.5 导出文件
```typescript
// GET /api/export/[taskId]?format=pdf_bilingual|pdf_translated|text
Response: Binary file
```

## 5. 翻译服务接口设计（通用抽象）

```python
from abc import ABC, abstractmethod
from typing import List, Dict

class TranslationService(ABC):
    @abstractmethod
    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        pass
    
    @abstractmethod
    def get_supported_languages(self) -> List[str]:
        pass

class TranslationServiceFactory:
    _services: Dict[str, TranslationService] = {}
    
    @classmethod
    def register(cls, name: str, service: TranslationService):
        cls._services[name] = service
    
    @classmethod
    def get(cls, name: str) -> TranslationService:
        return cls._services.get(name)
```

## 6. 项目结构
```
PDFTranslate/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   │   ├── FileUploader.tsx
│   │   │   ├── ProgressBar.tsx
│   │   │   ├── BilingualReader.tsx  # 双语对照阅读
│   │   │   └── LanguageSelector.tsx
│   │   ├── lib/
│   │   └── types/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── services/
│   │   │   ├── pdf_service.py
│   │   │   ├── translate_service.py
│   │   │   └── export_service.py
│   │   └── models/
│   ├── main.py
│   └── requirements.txt
└── README.md
```

## 7. 核心实现方案

### 7.1 大文件处理策略
- 流式上传，分块处理
- 每10页为一个批次
- WebSocket实时推送进度

### 7.2 保持排版方案
- PyMuPDF提取文本位置信息
- 翻译后保留文本块边界框
- 生成新PDF时还原布局

### 7.3 词语高亮预留设计
- 在textBlocks中存储每个文本块的边界框
- 前端维护选中状态
- 预留词语级映射字段（第二阶段扩展）

### 7.4 双语对照阅读
- react-pdf渲染左右两栏
- 同步滚动实现
- 分页导航

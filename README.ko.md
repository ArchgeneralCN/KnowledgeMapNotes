<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.ja.md">日本語</a> |
  <strong>한국어</strong>
</p>

# KnowledgeMapNotes

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Xikcn/KnowledgeMapNotes)

KnowledgeMapNotes는 지식 그래프 기반 노트 시스템입니다. TXT, Markdown, PDF 문서를 지식 그래프로 변환하고 벡터 검색, 엔터티 관계, 그래프 커뮤니티 정보를 결합한 HybridRAG 질의응답을 제공합니다.

Vue 3 웹 인터페이스와 FastAPI 백엔드로 구성되며 문서 증분 업데이트, 청크 단위 처리 진행률, 대규모 그래프 커뮤니티 페이지 분할, 스트리밍 답변, 런타임 AI 설정을 지원합니다.

## 데모

https://github.com/user-attachments/assets/5e9e6ffd-4e18-4915-b3a4-85198eb8bb0f

## 주요 기능

- **다중 형식 문서 처리**: `.txt`, `.md`, `.pdf`를 지원하며 PDF 이미지는 선택적으로 비전 모델을 사용해 추출할 수 있습니다.
- **지식 그래프 구축**: 엔터티와 관계 추출, 관계 가중치 계산, 지식 융합을 자동으로 수행합니다.
- **처리 프롬프트 제어**: 일반, 스토리, 사용자 지정 노트 유형을 제공합니다. 사용자 지정 유형에서는 엔터티 추출, 관계 추출, 지식 융합 프롬프트를 각각 편집할 수 있습니다.
- **안정적인 파일 업데이트**: 완료된 동일 이름 파일은 증분 업데이트할 수 있으며, 실패한 파일은 남은 데이터를 제거한 후 전체 재처리합니다.
- **처리 진행률**: 업로드, 처리, 증분 업데이트, 완료, 실패 상태와 함께 청크 수, 백분율, 청크별 시간, 예상 남은 시간을 표시합니다.
- **HybridRAG 질의응답**: 벡터 검색, 엔터티 인식, 그래프 커뮤니티를 결합하며 일반 응답, SSE 스트리밍, 생성 중지, 대화 기록을 지원합니다.
- **그래프 시각화**: 노드 및 관계 검색, 강조 표시, 엣지 가중치, 대규모 그래프용 Louvain 커뮤니티 개요와 상세 페이지를 제공합니다.
- **읽기 쉬운 그래프 배치**: 정적 ForceAtlas2를 사용하고 고립 노드를 관계 그래프 주변에 배치합니다. 좌표 확대와 충돌 해소로 노드 겹침을 줄입니다.
- **지식 베이스 관리**: 파일 검색과 필터링, 원문 미리보기와 다운로드, 주요 엔터티 확인, 파일 삭제, RAG 기록만 별도로 삭제할 수 있습니다.
- **근거 원문 이동**: 노드나 관계를 클릭하면 출처 청크로 이동하며 현재 대상, 다른 대상, 관계 설명을 계층적으로 강조합니다.
- **문서 워크플로**: 기본 미리보기, 소스 보기, 리치 텍스트 편집, 초안, 문서 이력, 버전 복원, 증분 업데이트, 자동 그래프 다시 그리기를 지원합니다.
- **통합 이력 복원**: 그래프 이력에 문서 스냅샷도 저장하며 그래프를 복원할 때 문서도 함께 복원합니다.
- **테마와 가독성**: 기본, 다크, 블루, 눈 보호 테마가 텍스트, 패널, 코드 블록, 초안 알림, 근거 강조 색상을 일관되게 적용합니다.
- **중단 후 재개**: 텍스트 청크마다 체크포인트를 저장해 마지막 완료 지점부터 처리를 재개할 수 있습니다.
- **AI 자동 장애 전환**: 기본 AI 요청이 실패하거나 잘못된 JSON을 반환하면 현재 청크를 예비 AI로 자동 처리합니다.
- **그래프 이전 패키지**: 원본 문서, 그래프 페이지, 처리 상태, RAG 기록을 포함한 `.kmn.zip`을 내보내고 다른 인스턴스에 드롭하여 AI 재처리 없이 복원할 수 있습니다.
- **기본 사용 안내서**: 첫 배포 시 텍스트 AI가 필요 없는 처리 완료 사용 안내서를 자동으로 가져옵니다. 추가 예시는 `backend/kmnzips`에서 제공합니다.
- **유연한 작업 공간**: 원문, 지식 그래프, RAG 패널을 나란히 보거나 숨기고 너비를 조절할 수 있습니다.
- **런타임 AI 설정**: 텍스트 모델 Base URL이나 API 키 없이 백엔드를 시작하고 웹 화면에서 연결을 테스트하고 저장할 수 있습니다.
- **단일 프로세스 실행**: 프런트엔드를 빌드한 뒤 FastAPI가 `frontend/dist`를 제공하므로 백엔드 프로세스 하나로 전체 웹 앱을 실행할 수 있습니다.

## 최근 업데이트

- 텍스트 모델을 설정하지 않아도 백엔드를 시작할 수 있으며 모델이 필요한 작업은 웹 설정을 안내합니다.
- 제출한 설정을 저장하지 않고 요청 지연 시간도 보여 주는 AI 연결 테스트를 추가했습니다.
- 사용자 지정 노트 유형과 3단계 처리 프롬프트 편집기를 추가했습니다.
- 실패한 파일 재업로드가 잘못 증분 업데이트되는 문제를 수정하고 재시도 전에 남은 데이터를 정리합니다.
- Markdown 원시 HTML 차단, DOMPurify 정리, 외부 링크 보안 속성, 경로 매개변수 인코딩으로 프런트엔드 보안을 강화했습니다.
- 프런트엔드 의존성과 SVG 로딩 방식을 갱신했으며 현재 `npm audit`에 알려진 취약점이 없습니다.
- 백엔드 정적 프런트엔드 호스팅, SPA 경로 폴백, `/api` 접두사 호환성을 추가했습니다.
- 문서 미리보기, 소스 및 리치 텍스트 모드, 초안 저장, 버전 복원, 증분 업데이트, 자동 그래프 다시 그리기를 추가했습니다.

## 개선 계획

- 노트 사이의 공통 지식과 주제 관계를 찾는 통합 개요 그래프를 추가합니다.
- 매우 큰 문서를 위한 지연 로딩, 로딩 스켈레톤, 분할 렌더링을 개선합니다.
- 사용자가 설정할 수 있는 테마 색상과 글꼴 밀도를 추가합니다.

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| 백엔드 | FastAPI, OpenAI Python SDK, ChromaDB, SentenceTransformers |
| 그래프 | NetworkX, PyVis, Louvain Community Detection |
| 프런트엔드 | Vue 3, Vite, Element Plus, Axios |
| 콘텐츠 렌더링 | Markdown-It, DOMPurify |
| 배포 | FastAPI 정적 호스팅, Docker Compose, Nginx |

## 문서 사이트

`docs-site/`에는 독립적인 VitePress 애플리케이션 문서 사이트가 있습니다. 빠른 시작, 핵심 기능, 배포, 보안, 환경 변수, HTTP API 및 FAQ를 제공하며 로컬 검색, 다크 모드와 모바일 탐색을 지원합니다.

```bash
cd docs-site
npm install
npm run dev
```

기본 주소는 http://localhost:5173 입니다. 프로덕션 빌드는 `npm run build`를 사용하며 정적 결과물은 `docs-site/docs/.vitepress/dist`에 생성됩니다.

## 빠른 시작

### 요구 사항

- Python 3.10 이상
- 프런트엔드 빌드 또는 개발용 Node.js 18 이상
- 그래프 구축과 RAG에 사용할 텍스트 모델 API. 백엔드 시작 전에는 설정하지 않아도 됩니다.
- CUDA GPU는 선택 사항입니다. CPU 환경에서는 `DEVICE=cpu`를 사용하세요.

처음 시작할 때 임베딩 및 재순위화 모델을 불러오므로 충분한 디스크 공간이 필요합니다. Hugging Face에서 온라인으로 모델을 받는 경우 인터넷 연결도 필요합니다.

첫 배포에서는 `backend/default_examples/本软件使用说明.kmn.zip`만 자동으로 가져옵니다. 이 과정은 텍스트 AI를 호출하지 않고 동일 이름의 데이터도 덮어쓰지 않습니다. `backend/kmnzips`의 추가 패키지는 업로드 화면에서 직접 가져올 수 있습니다. 빈 인스턴스로 시작하려면 `backend/.env`에 `DEFAULT_EXAMPLES_ENABLED=False`를 설정하세요.

### 1. 저장소 복제

```bash
git clone https://github.com/Xikcn/KnowledgeMapNotes.git
cd KnowledgeMapNotes
```

### 2. 백엔드 설정 생성

```bash
cp backend/.env.example backend/.env
```

실제 인증 정보가 들어 있는 `backend/.env`는 커밋하지 마세요.

텍스트 모델 항목은 비워 둔 채 시작할 수 있습니다. 시작 후 웹 화면의 **설정 -> AI 모델 설정**에서 Base URL, API 키, 모델 이름을 입력하고 연결 테스트가 성공하면 저장하세요.

CPU 및 온라인 모델 로딩 환경의 설정 예시:

```dotenv
# 프롬프트 버전: v1은 빠르고 v2는 더 오래 걸리지만 결과가 좋습니다
PROMPTVISION=v1

# OpenAI 호환 텍스트 모델. 웹 화면에서도 설정할 수 있습니다
BASE_URL=
API_KEY=
MODEL_NAME=
TEMPERATURE=0
ENABLE_THINKING=False
AI_MAX_OUTPUT_TOKENS=8192
AI_MAX_OUTPUT_PARAMETER=max_tokens
RELATION_TEXT_BATCH_CHARS=2000
RELATION_SOURCE_BATCH_SIZE=20
RELATION_MAX_SPLIT_DEPTH=10
FALLBACK_ENABLED=False
FALLBACK_BASE_URL=
FALLBACK_API_KEY=
FALLBACK_MODEL_NAME=
DEFAULT_EXAMPLES_ENABLED=True

# 선택적 PDF 이미지 인식
VL_API_KEY=
VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VL_MODEL=qwen-vl-max-latest

# 임베딩 및 재순위화 모델
IS_USE_LOCAL=False
EMBEDDINGS=BAAI/bge-base-zh
EMBEDDINGS_PATH=/absolute/path/to/bge-base-zh
RERANK_MODEL=BAAI/bge-reranker-base
DEVICE=cpu

# 텍스트 분할기
SIMPLE=[txt,pdf]
SEMANTIC=[]
CHARACTER=[md]

# backend/ 기준 런타임 데이터 디렉터리
CHROMADB_PATH=./chroma_data
UPLOAD_FOLDER=uploads
TXT_FOLDER=txt_files
RESULT_FOLDER=results
```

`SIMPLE`, `SEMANTIC`, `CHARACTER`는 `[txt,pdf]` 또는 `txt,pdf` 형식의 쉼표로 구분된 확장자를 받습니다. 같은 확장자는 하나의 분할기에만 설정하세요. 일치하지 않는 확장자에는 기본 분할기가 적용됩니다.

로컬 임베딩 모델을 사용하려면 `IS_USE_LOCAL=True`로 설정하고 `EMBEDDINGS_PATH`가 모델 디렉터리를 가리키게 하세요. 현재 PDF 처리기는 `qwen-vl-max-latest`를 사용합니다. `VL_MODEL`은 예약 설정이며 지금은 변경해도 비전 모델이 바뀌지 않습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 백엔드 수신 주소 |
| `PORT` | `8000` | 백엔드 수신 포트 |
| `FRONTEND_DIST` | `<project>/frontend/dist` | 프런트엔드 빌드 디렉터리. 재정의 시 절대 경로 권장 |
| `RAG_WORKER_COUNT` | `4` | RAG 스레드 풀 크기 |
| `CORS_ALLOW_ORIGINS` | `*` | 쉼표로 구분한 허용 오리진 |

### 3. 백엔드 의존성 설치

표준 `venv` 사용:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

`uv` 사용:

```bash
uv venv
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

Windows PowerShell 활성화 명령:

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 실행 방식 선택

#### 방식 A: FastAPI에서 빌드된 프런트엔드 제공

일상적인 사용과 단일 머신 배포에 적합합니다.

```bash
cd frontend
npm ci
npm run build
cd ../backend
python main.py
```

- 웹 인터페이스: http://localhost:8000
- API 문서: http://localhost:8000/docs
- 상태 확인: http://localhost:8000/health

백엔드는 `frontend/dist`를 자동으로 마운트합니다. 디렉터리가 없어도 API는 시작되며 로그에 `npm run build` 실행 안내가 표시됩니다.

#### 방식 B: 프런트엔드와 백엔드 개발 서버

터미널 1:

```bash
cd backend
python main.py
```

터미널 2:

```bash
cd frontend
npm ci
npm run dev
```

http://localhost:8080 을 여세요. Vite는 `/api` 요청을 `http://127.0.0.1:8000`으로 프록시합니다. 서로 다른 사이트로 배포할 때는 다음을 설정하세요.

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## Docker 배포

`backend/.env`를 만들고 검토한 다음 저장소 루트에서 실행합니다.

```bash
docker compose up --build
```

백그라운드 실행:

```bash
docker compose up -d --build
```

- 웹 인터페이스: http://localhost:8080
- 백엔드 API: http://localhost:8000
- API 문서: http://localhost:8000/docs

백엔드 이미지는 처음 빌드할 때 `BAAI/bge-base-zh`와 `BAAI/bge-reranker-base`를 다운로드합니다. Compose는 `backend/`를 `/app`에 마운트하고 런타임 데이터를 호스트의 `backend/uploads`, `backend/txt_files`, `backend/results`, `backend/chroma_data`에 저장합니다.

이미지에 미리 받은 모델 사용 설정:

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/app/models/bge-base-zh
RERANK_MODEL=/app/models/bge-reranker-base
```

## 보안

이 프로젝트에는 사용자 로그인이나 API 인증이 내장되어 있지 않습니다. 신뢰할 수 없는 공용 네트워크에 백엔드 포트를 직접 노출하지 마세요.

- 로컬에서만 사용할 경우 `HOST=127.0.0.1`로 설정하세요.
- LAN 또는 공용 배포에서는 인증과 HTTPS가 적용된 리버스 프록시를 사용하세요.
- 공용 배포에서 `CORS_ALLOW_ORIGINS`를 실제 프런트엔드 오리진으로 제한하세요.
- `backend/.env`, 로그, 업로드 파일, 지식 베이스 데이터를 커밋하지 마세요.
- AI 연결 테스트는 고정된 최소 메시지만 보내며 업로드한 문서 내용은 전송하지 않습니다.

## 사용 방법

### AI 모델 설정

1. 앱을 시작하고 설정 패널을 엽니다.
2. OpenAI 호환 서비스의 Base URL, API 키, 모델 이름을 입력합니다.
3. 서비스 기능에 따라 온도와 사고 모드를 설정합니다.
4. **연결 테스트**를 실행합니다. 최소 요청만 보내며 설정은 저장하지 않습니다.
5. 성공하면 **AI 설정 저장**을 선택합니다. 이후 그래프 추출과 RAG 요청에 즉시 적용됩니다.

런타임 설정은 백엔드 메모리에만 저장되고 재시작하면 `backend/.env`에서 다시 읽습니다. 백엔드는 API 키 전체를 반환하지 않습니다. 기존 키를 유지하려면 저장하거나 테스트할 때 키 입력란을 비워 둘 수 있습니다.

### 노트 유형 선택

- **일반**: 현재 프롬프트 버전의 일반 처리 템플릿을 사용합니다.
- **스토리**: 이야기 콘텐츠에 맞춘 그래프 처리 방식을 사용합니다.
- **사용자 지정**: 엔터티 추출, 관계 추출, 지식 융합 프롬프트를 각각 편집할 수 있습니다.

사용자 지정을 처음 선택하면 일반 프롬프트가 초기값으로 로드됩니다. 각 프롬프트는 최대 30,000자이며 브라우저 로컬 저장소에 보관됩니다. 업로드 요청과 함께 전송되지만 서버 템플릿은 변경하지 않습니다.

### 파일 업로드 및 재처리

1. 노트 유형을 선택하고 스캔 PDF나 이미지를 처리할 때 PDF 이미지 인식을 켭니다.
2. `.txt`, `.md`, `.pdf`를 클릭하거나 드래그하여 업로드합니다.
3. 파일 목록에서 처리 상태와 청크 진행률을 확인합니다.
4. 완료된 파일을 선택해 결과 작업 공간을 엽니다.

파일 컨텍스트 메뉴에서 처리를 일시 중지할 수 있습니다. 백엔드는 현재 청크를 완료하고 체크포인트를 저장한 뒤 중지하므로 완료된 AI 요청을 반복하지 않고 재개할 수 있습니다.

- 텍스트, 지식 베이스, 그래프가 완전한 동일 이름 파일은 증분 업데이트할 수 있습니다.
- 실패한 동일 이름 파일은 남은 데이터를 제거한 후 전체 재구축합니다.
- 완료 파일은 `.kmn.zip`으로 내보내고 다른 인스턴스에 드롭하여 복원할 수 있습니다.
- 데이터가 불완전하면 항상 전체 처리를 수행합니다.

### 결과 보기

- **원본 파일**: Markdown 미리보기와 소스를 전환하고 복사하거나 다운로드합니다.
- **지식 그래프**: 노드, 관계, 가중치를 탐색하며 대규모 그래프는 커뮤니티 개요와 상세 페이지를 제공합니다.
- **RAG 질의응답**: 현재 파일에 질문하고 스트리밍, 기록, 생성 중지를 사용할 수 있습니다.

### 관계 가중치와 검색 매개변수

관계 가중치는 `0`에서 `1` 사이이며 현재 문맥에서의 중요도를 나타냅니다.

| 매개변수 | 기본값 | 설명 |
| --- | --- | --- |
| `top_k` | `1` | 벡터 검색 결과 수 |
| `weight_threshold` | `0.3` | 질의응답에 사용할 최소 관계 가중치 |
| `max_relations` | `20` | 사용할 최대 관계 수 |

## API 개요

전체 요청 및 응답 스키마는 실행 중인 백엔드의 `/docs`를 참고하세요. 아래 경로는 직접 호출할 수 있고 빌드된 프런트엔드, Vite, Nginx에서는 `/api` 접두사도 지원합니다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/health` | 상태 확인 |
| `GET` | `/ai-settings` | 전체 API 키를 제외한 텍스트 모델 설정 조회 |
| `PUT` | `/ai-settings` | 현재 프로세스의 모델 설정 변경 |
| `POST` | `/ai-settings/test` | 저장하지 않고 설정 테스트 |
| `GET` | `/processing-prompts/defaults` | 일반 3단계 처리 프롬프트 조회 |
| `POST` | `/upload` | 문서 업로드 후 전체 처리 또는 증분 업데이트 시작 |
| `GET` | `/export-package/{filename}` | 이동 가능한 문서 및 그래프 패키지 다운로드 |
| `GET` | `/processing-status/{filename}` | 상태, 청크 진행률, 예상 남은 시간 조회 |
| `POST` | `/pause-processing/{filename}` | 현재 청크 완료 후 일시 중지 |
| `POST` | `/resume-processing/{filename}` | 저장된 체크포인트에서 재개 |
| `GET` | `/list-files` | 지식 베이스 파일 목록 조회 |
| `GET` | `/file-content/{filename}` | 변환된 텍스트 조회 |
| `GET` | `/file-entities/{filename}?count=5` | 주요 엔터티 조회 |
| `GET` | `/result/{filename}` | 그래프 홈 페이지 조회 |
| `GET` | `/result-page/{graph_name}/{page_name}` | 그래프 또는 커뮤니티 페이지 조회 |
| `DELETE` | `/delete/{filename}` | 파일과 관련 데이터 삭제 |
| `DELETE` | `/rag-history/{filename}` | 파일의 RAG 기록 삭제 |
| `POST` | `/create_session` | 질의응답 세션 생성 |
| `POST` | `/hybridrag` | 비스트리밍 HybridRAG 실행 |
| `POST` | `/hybridrag/stream` | SSE 스트리밍 HybridRAG 실행 |
| `GET` | `/session_status/{session_id}` | 세션 상태와 대기열 길이 조회 |
| `DELETE` | `/session/{session_id}` | 유휴 세션 삭제 |

`POST /upload`는 `multipart/form-data`를 사용합니다.

| 필드 | 필수 | 설명 |
| --- | --- | --- |
| `file` | 예 | `.txt`, `.md`, `.pdf` 파일 |
| `noteType` | 아니요 | `general`, `story`, `custom`. 기본값은 `general` |
| `use_img2txt` | 아니요 | PDF 이미지 내용을 인식할지 여부 |
| `entityPrompt` | custom에서 선택 | 엔터티 추출 프롬프트 |
| `relationshipPrompt` | custom에서 선택 | 관계 추출 프롬프트 |
| `fusionPrompt` | custom에서 선택 | 지식 융합 프롬프트 |

HybridRAG 요청 예시:

```json
{
  "request": "이 문서의 핵심 내용은 무엇인가요?",
  "filename": "example.pdf",
  "flow": true,
  "top_k": 3,
  "weight_threshold": 0.3,
  "max_relations": 20,
  "messages": [],
  "session_id": null
}
```

## 데이터와 디렉터리

```text
KnowledgeMapNotes/
├── backend/
│   ├── main.py                    # FastAPI 애플리케이션 진입점
│   ├── KnowledgeGraphManager/     # 그래프 구축, 융합, 시각화
│   ├── LLM/                       # 모델 호출과 RAG 출력 처리
│   ├── OmniStore/                 # ChromaDB 및 지식 베이스 저장소
│   ├── OmniText/                  # PDF, Markdown 텍스트 추출
│   ├── TextSlicer/                # 텍스트 분할기
│   ├── embedding_tools/           # 임베딩 및 재순위화 도구
│   ├── prompt/                    # v1/v2 프롬프트 템플릿
│   ├── uploads/                   # 업로드 원본 파일
│   ├── txt_files/                 # 변환된 텍스트 파일
│   ├── results/<document>/        # 그래프 및 커뮤니티 페이지
│   └── chroma_data/               # ChromaDB 영구 데이터
└── frontend/
    ├── src/                       # Vue 3 애플리케이션 소스
    ├── dist/                      # npm run build 결과
    ├── vite.config.js             # 개발 서버 및 API 프록시
    └── nginx.conf                 # Docker 프런트엔드 Nginx 설정
```

`uploads`, `txt_files`, `results`, `chroma_data`는 서로 연관된 하나의 런타임 데이터 집합입니다. 지식 베이스를 이전, 복원, 백업할 때 함께 일관되게 관리하세요.

## Douyin 채팅 JSON을 TXT로 변환

저장소에는 `douyin-chat-export`가 내보낸 JSON을 변환하는 도우미 스크립트가 포함되어 있습니다.

```bash
python "backend/validation/将抖音聊天转txt.py" chat.json chat.txt
```

두 번째 인수를 생략하면 현재 디렉터리에 `result.txt`를 출력합니다. 표준 입력에서도 읽을 수 있습니다.

```bash
python "backend/validation/将抖音聊天转txt.py" < chat.json
```

일반 메시지(`type=0`, `[系统消息]` 제외)와 `type=24` 메시지를 유지하고 각 줄을 `accountName:content` 형식으로 기록합니다. 생성된 TXT 파일은 바로 업로드할 수 있습니다.

## FAQ

### Base URL과 API 키 없이 백엔드를 시작할 수 있나요?

예. 시작 후 웹 설정에서 텍스트 모델을 구성할 수 있습니다. 설정 전에는 모델이 필요한 업로드 및 RAG API가 명확한 메시지와 함께 `503`을 반환합니다.

### API는 열리지만 웹 화면이 보이지 않는 이유는 무엇인가요?

`frontend/`에서 `npm run build`를 실행하고 `frontend/dist/index.html`이 있는지 확인하세요. 사용자 지정 빌드 디렉터리를 사용한다면 `FRONTEND_DIST`를 설정하세요.

### 백엔드 시작 시 프롬프트나 `.env`를 찾지 못하는 이유는 무엇인가요?

대부분의 백엔드 경로는 `backend/` 기준 상대 경로입니다.

```bash
cd backend
python main.py
```

### AI 연결 테스트 후 재시작하면 설정이 사라지는 이유는 무엇인가요?

웹에서 저장한 설정은 현재 백엔드 프로세스에만 적용됩니다. 영구 저장하려면 `backend/.env`에 값을 넣고 백엔드를 재시작하세요.

### 로컬 임베딩 모델은 어떻게 사용하나요?

`IS_USE_LOCAL=True`로 설정하고 `EMBEDDINGS_PATH`가 로컬 모델을 가리키도록 하세요. CUDA 버전에 맞는 PyTorch가 없다면 `DEVICE=cpu`를 사용하세요.

### 대규모 그래프가 여러 페이지로 열리는 이유는 무엇인가요?

Louvain이 여러 커뮤니티를 찾고 페이지 분할 임계값에 도달하면 전체 개요와 큰 커뮤니티의 상세 페이지를 생성합니다. 기본적으로 노드가 20개 이상인 커뮤니티만 상세 페이지가 생성됩니다. 모든 커뮤니티를 만들려면 `GRAPH_COMMUNITY_MIN_SIZE=1`로 설정하고 그래프를 다시 생성하세요.

### `.env` 변경이 적용되지 않는 이유는 무엇인가요?

환경 변수는 백엔드를 시작할 때 읽습니다. 수정 후 백엔드를 재시작하세요. Docker에서는 `docker compose restart backend`를 실행합니다.

## 로드맵

- 로컬 지식 그래프가 답하지 못할 때 필요에 따라 온라인 지식을 보완합니다.
- 텍스트 청킹과 벡터/트리플 융합을 개선합니다.
- 노트 사실 확인, 복습 시험, 설명 영상 생성을 추가합니다.
- 개인정보 비식별화와 복원 흐름을 개선합니다.

## 라이선스

이 프로젝트는 GNU AGPL-3.0으로 오픈 소스 공개되며 이중 라이선스 모델을 사용합니다.

| 사용 사례 | 비용 | 요구 사항 |
| --- | --- | --- |
| 개인 학습, 연구 및 비상업적 사용 | 무료 | AGPL-3.0을 준수하고 수정 사항을 공개하며 저작권 고지를 유지해야 합니다 |
| 오픈 소스 프로젝트의 2차 개발 | 무료 | 파생 저작물을 AGPL-3.0으로 공개해야 합니다 |
| 배포하지 않는 기업 내부 도구 | 무료 | AGPL-3.0을 준수해야 합니다 |
| 비공개 소스 상업 사용 또는 패키지 판매 | 상업용 라이선스 필요 | AGPL-3.0은 비공개 소스 배포를 허용하지 않습니다 |
| 소스 코드를 공개하지 않는 SaaS / 네트워크 서비스 | 상업용 라이선스 필요 | AGPL-3.0은 네트워크 사용자에게 소스 제공을 요구합니다 |
| 독점 소프트웨어에 통합하여 재배포 | 상업용 라이선스 필요 | AGPL-3.0 카피레프트 요구 사항과 호환되지 않습니다 |

요약하면 개인 및 오픈 소스 사용은 무료입니다. 비공개 소스로 판매하거나 소스를 공개하지 않는 SaaS를 운영하려면 상업용 라이선스가 필요합니다.

### 상업용 라이선스

AGPL-3.0 요구 사항의 적용을 받지 않는 상업용 라이선스가 필요한 경우 다음으로 문의하세요.

- QQ: `1615242125`
- WeChat: `XKJ1615242125`

AGPL-3.0 전체 내용은 [LICENSE](LICENSE), 이중 라이선스 설명은 [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)를 참조하세요.

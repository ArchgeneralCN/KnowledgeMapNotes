<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> |
  <strong>日本語</strong> |
  <a href="README.ko.md">한국어</a>
</p>

# KnowledgeMapNotes

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Xikcn/KnowledgeMapNotes)

KnowledgeMapNotes は、知識グラフを基盤とするノートシステムです。TXT、Markdown、PDF 文書を知識グラフへ変換し、ベクトル検索、エンティティ間の関係、グラフコミュニティ情報を組み合わせた HybridRAG 質疑応答を提供します。

Vue 3 の Web インターフェースと FastAPI バックエンドで構成され、文書の差分更新、チャンク単位の処理進捗、大規模グラフのコミュニティページ分割、ストリーミング応答、実行時の AI 設定に対応しています。

## デモ

https://github.com/user-attachments/assets/5e9e6ffd-4e18-4915-b3a4-85198eb8bb0f

## 主な機能

- **複数形式の文書処理**：`.txt`、`.md`、`.pdf` に対応し、PDF 内の画像はオプションで視覚モデルを使って抽出できます。
- **知識グラフ構築**：エンティティと関係の抽出、関係重みの計算、知識融合を自動で実行します。
- **処理プロンプトの制御**：汎用、ストーリー、カスタムのノート種別を提供し、カスタムではエンティティ抽出、関係抽出、知識融合のプロンプトを個別に編集できます。
- **信頼できるファイル更新**：処理済みの同名ファイルは差分更新でき、失敗したファイルは残存データを削除してから完全に再処理します。
- **処理進捗の表示**：アップロード、処理、差分更新、完了、失敗の状態に加え、チャンク数、進捗率、チャンク処理時間、残り時間の予測を表示します。
- **HybridRAG 質疑応答**：ベクトル検索、エンティティ認識、グラフコミュニティを統合し、通常応答、SSE ストリーミング、生成停止、会話履歴に対応します。
- **グラフ可視化**：ノードと関係の検索、ハイライト、エッジ重み、大規模グラフ向けの Louvain コミュニティ概要・詳細ページを提供します。
- **読みやすいレイアウト**：静的 ForceAtlas2 を使用し、孤立ノードを関係グラフの周囲に配置します。座標拡大と衝突解消によりノードの重なりを抑えます。
- **ナレッジベース管理**：ファイルの検索・絞り込み、原文のプレビュー・ダウンロード、主要エンティティの確認、ファイル削除、RAG 履歴のみの削除が可能です。
- **根拠箇所への移動**：ノードや関係をクリックすると出典チャンクへ移動し、現在の対象、その他の対象、関係説明を段階的にハイライトします。
- **文書ワークフロー**：プレビュー、ソース表示、リッチテキスト編集、下書き、文書履歴、版の復元、差分更新、グラフの自動再描画に対応します。
- **統合履歴**：グラフ履歴に文書スナップショットも保存し、グラフの復元時に文書も同期して復元します。
- **テーマ**：デフォルト、ダーク、ブルー、アイケアの 4 テーマで、本文、パネル、コード、下書き通知、根拠ハイライトの配色を統一しています。
- **処理の中断・再開**：テキストチャンクごとにチェックポイントを保存し、最後に完了した位置から再開できます。
- **AI の自動フェイルオーバー**：主 AI の要求失敗や不正な JSON 応答時に、予備 AI へ自動で切り替えます。
- **グラフ移行パッケージ**：原文、グラフページ、処理状態、RAG 履歴を含む `.kmn.zip` を書き出し、別環境へドロップするだけで AI を再実行せず復元できます。
- **組み込みガイド**：初回デプロイ時に、テキスト AI を必要としない処理済みの操作ガイドを自動で取り込みます。追加例は `backend/kmnzips` にあります。
- **柔軟なワークスペース**：原文、知識グラフ、RAG パネルを横並びに表示し、非表示や幅調整もできます。
- **実行時 AI 設定**：テキストモデルの Base URL や API キーなしでもバックエンドを起動し、Web 画面から接続テストと保存ができます。
- **単一プロセス構成**：フロントエンドのビルド後は FastAPI が `frontend/dist` を配信し、バックエンドだけで Web アプリ全体を提供できます。

## 最近の更新

- テキストモデル未設定でもバックエンドを起動でき、モデルが必要な操作では Web 設定を案内するようになりました。
- 保存せずに要求遅延も確認できる AI 接続テストを追加しました。
- カスタムノート種別と 3 段階の処理プロンプトエディターを追加しました。
- 失敗ファイルの再アップロードが誤って差分更新になる問題を修正しました。
- Markdown の生 HTML 無効化、DOMPurify、外部リンク属性、パス引数のエンコードによりフロントエンドの安全性を強化しました。
- フロントエンド依存関係と SVG 読み込み方式を更新し、現在 `npm audit` で既知の脆弱性はありません。
- 静的フロントエンド配信、SPA フォールバック、`/api` プレフィックス互換をバックエンドへ追加しました。
- 文書プレビュー、ソース表示、リッチテキスト編集、履歴復元、差分更新、自動グラフ再描画を追加しました。

## 改善予定

- ノート間の共通知識やトピック関係を見つけるための横断概要グラフを追加。
- 非常に大きな文書向けの遅延読み込み、ローディングスケルトン、分割描画を改善。
- ユーザー設定可能なテーマカラーとフォント密度を追加。

## 技術スタック

| 分野 | 技術 |
| --- | --- |
| バックエンド | FastAPI、OpenAI Python SDK、ChromaDB、SentenceTransformers |
| グラフ | NetworkX、PyVis、Louvain Community Detection |
| フロントエンド | Vue 3、Vite、Element Plus、Axios |
| コンテンツ描画 | Markdown-It、DOMPurify |
| デプロイ | FastAPI 静的配信、Docker Compose、Nginx |

## ドキュメントサイト

`docs-site/` には独立した VitePress ドキュメントサイトがあります。クイックスタート、主要機能、デプロイ、安全性、環境変数、HTTP API、FAQ を収録し、ローカル検索、ダークモード、モバイルナビゲーションにも対応しています。

```bash
cd docs-site
npm install
npm run dev
```

既定の URL は http://localhost:5173 です。本番用ビルドは `npm run build` を使用し、静的ファイルは `docs-site/docs/.vitepress/dist` に出力されます。

## クイックスタート

### 必要環境

- Python 3.10 以上
- フロントエンドのビルド・開発には Node.js 18 以上
- グラフ構築と RAG に使うテキストモデル API（バックエンド起動前の設定は不要）
- CUDA GPU は任意。CPU 環境では `DEVICE=cpu` を使用

初回起動時に埋め込みモデルとリランキングモデルを読み込むため、十分なディスク容量が必要です。Hugging Face からオンライン取得する場合はネットワーク接続も必要です。

初回デプロイで自動取り込みされるのは `backend/default_examples/本软件使用说明.kmn.zip` のみです。テキスト AI は呼び出さず、同名データも上書きしません。`backend/kmnzips` の追加パッケージはアップロード画面から手動で取り込めます。空の環境で始める場合は `backend/.env` に `DEFAULT_EXAMPLES_ENABLED=False` を設定してください。

### 1. リポジトリをクローン

```bash
git clone https://github.com/Xikcn/KnowledgeMapNotes.git
cd KnowledgeMapNotes
```

### 2. バックエンド設定を作成

```bash
cp backend/.env.example backend/.env
```

実際の認証情報を含む `backend/.env` はコミットしないでください。

テキストモデル設定は空のままでも起動できます。起動後、Web 画面の「設定 -> AI モデル設定」で Base URL、API キー、モデル名を入力し、接続テストに成功してから保存します。

CPU とオンラインモデル読み込み向けの設定例：

```dotenv
# プロンプト版：v1 は高速、v2 は時間がかかる代わりに高品質
PROMPTVISION=v1

# OpenAI 互換テキストモデル。Web 画面からの設定も可能
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

# PDF 画像認識（任意）
VL_API_KEY=
VL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VL_MODEL=qwen-vl-max-latest

# 埋め込み・リランキングモデル
IS_USE_LOCAL=False
EMBEDDINGS=BAAI/bge-base-zh
EMBEDDINGS_PATH=/absolute/path/to/bge-base-zh
RERANK_MODEL=BAAI/bge-reranker-base
DEVICE=cpu

# テキスト分割器
SIMPLE=[txt,pdf]
SEMANTIC=[]
CHARACTER=[md]

# backend/ からの相対実行データディレクトリ
CHROMADB_PATH=./chroma_data
UPLOAD_FOLDER=uploads
TXT_FOLDER=txt_files
RESULT_FOLDER=results
```

`SIMPLE`、`SEMANTIC`、`CHARACTER` は `[txt,pdf]` または `txt,pdf` 形式の拡張子一覧を受け取ります。同じ拡張子は 1 種類の分割器だけに設定してください。該当しない拡張子には既定の分割器が使われます。

ローカル埋め込みモデルを使う場合は `IS_USE_LOCAL=True` とし、`EMBEDDINGS_PATH` をモデルディレクトリへ向けます。現在の PDF 処理は `qwen-vl-max-latest` を使用します。`VL_MODEL` は予約設定であり、変更しても現時点では視覚モデルは切り替わりません。

| 変数 | 既定値 | 説明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | バックエンドの待受アドレス |
| `PORT` | `8000` | バックエンドの待受ポート |
| `FRONTEND_DIST` | `<project>/frontend/dist` | フロントエンドのビルド先。上書き時は絶対パスを推奨 |
| `RAG_WORKER_COUNT` | `4` | RAG スレッドプールのサイズ |
| `CORS_ALLOW_ORIGINS` | `*` | 許可するオリジン（カンマ区切り） |

### 3. バックエンド依存関係をインストール

標準の `venv` を使う場合：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

`uv` を使う場合：

```bash
uv venv
source .venv/bin/activate
uv pip install -r backend/requirements.txt
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 起動方法を選択

#### 方法 A：FastAPI からビルド済みフロントエンドを配信

```bash
cd frontend
npm ci
npm run build
cd ../backend
python main.py
```

- Web 画面：http://localhost:8000
- API ドキュメント：http://localhost:8000/docs
- ヘルスチェック：http://localhost:8000/health

バックエンドは `frontend/dist` を自動でマウントします。存在しない場合も API は起動し、ログに `npm run build` の案内が表示されます。

#### 方法 B：フロントエンド・バックエンド開発モード

ターミナル 1：

```bash
cd backend
python main.py
```

ターミナル 2：

```bash
cd frontend
npm ci
npm run dev
```

http://localhost:8080 を開きます。Vite は `/api` を `http://127.0.0.1:8000` へプロキシします。別サイトとして配置する場合は次を設定します。

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

## Docker デプロイ

`backend/.env` を作成・確認してから、リポジトリのルートで実行します。

```bash
docker compose up --build
```

バックグラウンド実行：

```bash
docker compose up -d --build
```

- Web 画面：http://localhost:8080
- バックエンド API：http://localhost:8000
- API ドキュメント：http://localhost:8000/docs

バックエンドイメージは初回に `BAAI/bge-base-zh` と `BAAI/bge-reranker-base` を取得します。Compose は `backend/` を `/app` にマウントし、実行データをホスト側の `backend/uploads`、`backend/txt_files`、`backend/results`、`backend/chroma_data` に保存します。

イメージ内のモデルを使う設定：

```dotenv
IS_USE_LOCAL=True
EMBEDDINGS_PATH=/app/models/bge-base-zh
RERANK_MODEL=/app/models/bge-reranker-base
```

## セキュリティ

本プロジェクトにはユーザーログインや API 認証が組み込まれていません。信頼できない公開ネットワークへバックエンドポートを直接公開しないでください。

- ローカル利用のみの場合は `HOST=127.0.0.1` を設定します。
- LAN・公開環境では、認証と HTTPS を備えたリバースプロキシを使用します。
- 公開環境では `CORS_ALLOW_ORIGINS` を実際のフロントエンドオリジンに限定します。
- `backend/.env`、ログ、アップロードファイル、ナレッジベースデータをコミットしないでください。
- AI 接続テストは固定の最小メッセージだけを送信し、アップロード文書の内容は送信しません。

## 使用方法

### AI モデルを設定

1. アプリを起動して設定パネルを開きます。
2. OpenAI 互換サービスの Base URL、API キー、モデル名を入力します。
3. サービスに合わせて温度と思考モードを設定します。
4. 「接続テスト」を実行します。設定は保存されず、最小限の要求だけが送信されます。
5. 成功後に「AI 設定を保存」を実行します。以後のグラフ抽出と RAG 要求へ直ちに適用されます。

実行時設定はバックエンドのメモリにのみ保存され、再起動後は `backend/.env` から読み直されます。API キー本体は返されません。既存キーを維持する場合は、保存・テスト時にキー欄を空にできます。

### ノート種別を選択

- **汎用**：現在のプロンプト版の汎用テンプレートを使用します。
- **ストーリー**：物語向けのグラフ処理を使用します。
- **カスタム**：エンティティ抽出、関係抽出、知識融合の各プロンプトを編集できます。

カスタムを初めて選ぶと汎用プロンプトが初期値になります。各プロンプトは最大 30,000 文字でブラウザのローカルストレージへ保存され、サーバーのテンプレートは変更しません。

### ファイルをアップロード・再処理

1. ノート種別を選び、スキャン PDF や画像を処理する場合は PDF 画像認識を有効にします。
2. `.txt`、`.md`、`.pdf` をクリックまたはドラッグでアップロードします。
3. ファイル一覧で状態とチャンク進捗を確認します。
4. 完了したファイルを選択して結果ワークスペースを開きます。

コンテキストメニューから処理を一時停止できます。現在のチャンクを完了してチェックポイントを保存した後に停止するため、完了済みの AI 要求を繰り返さず再開できます。

- 完全なデータがある同名ファイルは差分更新できます。
- 失敗した同名ファイルは残存データを削除して完全に再構築します。
- 完了ファイルは `.kmn.zip` として書き出し、別環境へドロップして復元できます。
- データが不完全な場合は常に完全処理を実行します。

### 結果を確認

- **原文**：Markdown プレビューとソースを切り替え、コピー・ダウンロードできます。
- **知識グラフ**：ノード、関係、重みを閲覧し、大規模グラフではコミュニティ概要と詳細を確認できます。
- **RAG 質疑応答**：現在のファイルについて質問し、ストリーミング、履歴、生成停止を利用できます。

### 関係重みと検索パラメータ

関係重みは `0` から `1` で、現在の文脈における重要度を表します。

| パラメータ | 既定値 | 説明 |
| --- | --- | --- |
| `top_k` | `1` | ベクトル検索件数 |
| `weight_threshold` | `0.3` | 質疑応答に使う関係の最小重み |
| `max_relations` | `20` | 使用する関係の最大数 |

## API 概要

完全な要求・応答仕様は、起動後の `/docs` を参照してください。次のパスは直接呼び出せるほか、ビルド版フロントエンド、Vite、Nginx からは `/api` プレフィックス付きでも利用できます。

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `GET` | `/ai-settings` | API キー本体を除くテキストモデル設定を取得 |
| `PUT` | `/ai-settings` | 現在のプロセスのモデル設定を更新 |
| `POST` | `/ai-settings/test` | 保存せず設定をテスト |
| `GET` | `/processing-prompts/defaults` | 汎用 3 段階プロンプトを取得 |
| `POST` | `/upload` | 文書をアップロードして完全処理または差分更新を開始 |
| `GET` | `/export-package/{filename}` | 移行可能な文書・グラフパッケージを取得 |
| `GET` | `/processing-status/{filename}` | 状態、チャンク進捗、残り時間を取得 |
| `POST` | `/pause-processing/{filename}` | 現在のチャンク後に一時停止 |
| `POST` | `/resume-processing/{filename}` | チェックポイントから再開 |
| `GET` | `/list-files` | ファイル一覧を取得 |
| `GET` | `/file-content/{filename}` | 変換済みテキストを取得 |
| `GET` | `/file-entities/{filename}?count=5` | 主要エンティティを取得 |
| `GET` | `/result/{filename}` | グラフのホームページを取得 |
| `GET` | `/result-page/{graph_name}/{page_name}` | グラフまたはコミュニティページを取得 |
| `DELETE` | `/delete/{filename}` | ファイルと関連データを削除 |
| `DELETE` | `/rag-history/{filename}` | RAG 履歴を削除 |
| `POST` | `/create_session` | 質疑応答セッションを作成 |
| `POST` | `/hybridrag` | 非ストリーミング HybridRAG |
| `POST` | `/hybridrag/stream` | SSE ストリーミング HybridRAG |
| `GET` | `/session_status/{session_id}` | セッション状態と待ち行列を取得 |
| `DELETE` | `/session/{session_id}` | アイドルセッションを削除 |

`POST /upload` は `multipart/form-data` を使用します。

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `file` | はい | `.txt`、`.md`、`.pdf` |
| `noteType` | いいえ | `general`、`story`、`custom`。既定は `general` |
| `use_img2txt` | いいえ | PDF 画像内容を認識するか |
| `entityPrompt` | custom で任意 | エンティティ抽出プロンプト |
| `relationshipPrompt` | custom で任意 | 関係抽出プロンプト |
| `fusionPrompt` | custom で任意 | 知識融合プロンプト |

HybridRAG 要求例：

```json
{
  "request": "この文書の主要な論点は何ですか？",
  "filename": "example.pdf",
  "flow": true,
  "top_k": 3,
  "weight_threshold": 0.3,
  "max_relations": 20,
  "messages": [],
  "session_id": null
}
```

## データとディレクトリ

```text
KnowledgeMapNotes/
├── backend/
│   ├── main.py                    # FastAPI エントリーポイント
│   ├── KnowledgeGraphManager/     # グラフ構築・融合・可視化
│   ├── LLM/                       # モデル呼び出しと RAG 出力
│   ├── OmniStore/                 # ChromaDB とナレッジベース
│   ├── OmniText/                  # PDF・Markdown テキスト抽出
│   ├── TextSlicer/                # テキスト分割器
│   ├── embedding_tools/           # 埋め込み・リランキング
│   ├── prompt/                    # v1/v2 プロンプト
│   ├── uploads/                   # アップロード原文
│   ├── txt_files/                 # 変換済みテキスト
│   ├── results/<document>/        # グラフページ
│   └── chroma_data/               # ChromaDB 永続データ
└── frontend/
    ├── src/                       # Vue 3 ソース
    ├── dist/                      # npm run build の出力
    ├── vite.config.js             # 開発サーバーと API プロキシ
    └── nginx.conf                 # Docker 用 Nginx 設定
```

`uploads`、`txt_files`、`results`、`chroma_data` は関連する一組の実行データです。移行、復元、バックアップでは整合性を保ってください。

## Douyin チャット JSON から TXT への変換

リポジトリには `douyin-chat-export` が出力した JSON を変換する補助スクリプトがあります。

```bash
python "backend/validation/将抖音聊天转txt.py" chat.json chat.txt
```

第 2 引数を省略すると、現在のディレクトリへ `result.txt` を出力します。標準入力からも読み込めます。

```bash
python "backend/validation/将抖音聊天转txt.py" < chat.json
```

通常メッセージ（`type=0`、`[系统消息]` を除く）と `type=24` のメッセージを残し、1 行ごとに `accountName:content` 形式で書き出します。生成した TXT はそのままアップロードできます。

## FAQ

### Base URL と API キーなしで起動できますか？

はい。起動後に Web 設定から構成できます。設定完了まではモデルが必要なアップロード・RAG API が明確な説明付きで `503` を返します。

### API は開くのに Web 画面が表示されないのはなぜですか？

`frontend/` で `npm run build` を実行し、`frontend/dist/index.html` を確認してください。独自の出力先を使う場合は `FRONTEND_DIST` を設定します。

### 起動時にプロンプトや `.env` が見つからないのはなぜですか？

バックエンドの多くのパスは `backend/` からの相対パスです。

```bash
cd backend
python main.py
```

### 接続テスト後、再起動すると AI 設定が消えるのはなぜですか？

Web から保存した設定は現在のバックエンドプロセスだけに適用されます。永続化するには `backend/.env` に記入して再起動してください。

### ローカル埋め込みモデルを使うには？

`IS_USE_LOCAL=True` を設定し、`EMBEDDINGS_PATH` をローカルモデルへ向けます。CUDA に対応する PyTorch がない場合は `DEVICE=cpu` を使用してください。

### 大規模グラフが複数ページになるのはなぜですか？

Louvain が複数コミュニティを検出し、ページ分割のしきい値に達すると、全体概要と大きなコミュニティの詳細ページを生成します。既定では 20 ノード以上が詳細ページの対象です。すべて生成するには `GRAPH_COMMUNITY_MIN_SIZE=1` を設定してグラフを再生成します。

### `.env` の変更が反映されないのはなぜですか？

環境変数はバックエンド起動時に読み込まれます。編集後に再起動してください。Docker では `docker compose restart backend` を実行します。

## ロードマップ

- ローカル知識グラフで回答できない場合に、必要に応じてオンライン知識を補完。
- テキスト分割とベクトル・トリプル融合を改善。
- ノートのファクトチェック、復習テスト、解説動画生成を追加。
- 個人情報のマスキングと復元フローを改善。

## ライセンス

本プロジェクトは GNU AGPL-3.0 の下でオープンソースとして公開され、デュアルライセンス方式を採用しています。

| 利用シーン | 料金 | 条件 |
| --- | --- | --- |
| 個人学習、研究、非商用利用 | 無料 | AGPL-3.0 を遵守し、変更内容を公開して著作権表示を保持すること |
| オープンソースプロジェクトでの二次開発 | 無料 | 派生作品を AGPL-3.0 で公開すること |
| 社内ツール（配布なし） | 無料 | AGPL-3.0 を遵守すること |
| クローズドソースでの商用利用・パッケージ販売 | 商用ライセンスが必要 | AGPL-3.0 ではクローズドソース配布はできません |
| ソースコードを公開しない SaaS / ネットワークサービス | 商用ライセンスが必要 | AGPL-3.0 はネットワーク利用者へのソース提供を求めます |
| プロプライエタリソフトウェアへの統合・再配布 | 商用ライセンスが必要 | AGPL-3.0 のコピーレフト要件に適合しません |

要約すると、個人利用とオープンソース利用は無料です。クローズドソースでの販売、またはソースを公開しない SaaS には商用ライセンスが必要です。

### 商用ライセンス

AGPL-3.0 の制約を受けない商用ライセンスについては、以下へお問い合わせください。

- QQ：`1615242125`
- WeChat：`XKJ1615242125`

AGPL-3.0 の全文は [LICENSE](LICENSE)、デュアルライセンスの説明は [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) を参照してください。

# 🏗️ Multi-Agent Otonom Mobil Uygulama Geliştirme: Hibrit Mimari & Production-Grade Öneriler

## 1. Hibrit Sistem Mimarisi (Inner Loop / Outer Loop)

Önerdiğiniz hibrit yaklaşım mükemmel bir başlangıç noktası. Aşağıda bunu production-grade seviyeye taşıyacak detaylı mimariyi sunuyorum.

### 1.1 İç Döngü (Inner Loop — Lokal / Hızlı)

```mermaid
graph LR
    A[Coder Agent] -->|Kod Yazar| B[Lokal Docker Container]
    B -->|Lint + Type Check| C{Syntax/Lint Hatası?}
    C -->|Evet| D[Self-Fix Agent]
    D -->|Düzeltilmiş Kod| B
    C -->|Hayır| E[Unit Test Runner]
    E -->|Test Sonuçları| F{Testler Geçti mi?}
    F -->|Hayır| D
    F -->|Evet| G[✅ PR'a Hazır]
```

**Detaylar:**

| Özellik | Açıklama |
|---------|----------|
| **Ortam** | Ajan başına izole Docker container (Node/Dart/Swift SDK kurulu) |
| **Lint Araçları** | ESLint + Prettier (React Native), Dart Analyzer + DCM (Flutter), SwiftLint (iOS) |
| **Self-Fix Mekanizması** | Lint çıktısı doğrudan Coder Agent'ın context'ine enjekte edilir. Ajan, hata mesajını okuyarak kendi kodunu düzeltir. |
| **Maks. Self-Fix Döngüsü** | **3 iterasyon** — sonsuz döngüyü önlemek için. 3 denemede düzelmezse Reviewer'a escalate edilir. |
| **Çıktı Formatı** | `git diff` formatında patch — her değişiklik izlenebilir |

**İç Döngü State Yapısı:**

```json
{
  "inner_loop_state": {
    "iteration": 1,
    "max_iterations": 3,
    "lint_results": [],
    "test_results": [],
    "patches": [],
    "status": "in_progress"
  }
}
```

---

### 1.2 Dış Döngü (Outer Loop — GitHub / CI)

```mermaid
graph TD
    A[İç Döngü ✅ Hazır] -->|git push + PR Aç| B[GitHub Repository]
    B -->|Webhook Tetikler| C[GitHub Actions CI Pipeline]
    C --> D[Build + Integration Tests]
    C --> E[E2E Tests - Detox/Patrol]
    C --> F[Security Scan - Snyk/Trivy]
    D & E & F -->|CI Logları| G[Reviewer Agent]
    G -->|GitHub PR Review API| H{Karar}
    H -->|✅ Approve| I[Auto-Merge + Deploy]
    H -->|❌ Request Changes| J[PR'a Yorum Yaz]
    J -->|Feedback JSON| K[Coder Agent]
    K -->|Fix + Force Push| B
```

**GitHub Entegrasyonu Detayları:**

| Bileşen | Teknoloji | Amaç |
|---------|-----------|------|
| **PR Oluşturma** | `PyGithub` veya `gh` CLI | Otomatik PR açma ve branch yönetimi |
| **CI Loglarını Okuma** | GitHub Actions API (`/repos/{owner}/{repo}/actions/runs`) | Reviewer Agent'ın CI çıktılarını parse etmesi |
| **PR Review** | GitHub Pull Request Review API | Satır bazlı yorum bırakma (inline comments) |
| **Auto-Merge** | Branch Protection Rules + Merge API | Tüm check'ler geçince otomatik merge |
| **Webhook** | GitHub Webhooks → FastAPI endpoint | CI tamamlandığında Reviewer'ı tetikleme |

**Dış Döngü State Yapısı:**

```json
{
  "outer_loop_state": {
    "pr_number": 42,
    "pr_url": "https://github.com/org/app/pull/42",
    "ci_status": "success",
    "ci_logs": { "build": "...", "test": "...", "security": "..." },
    "review_iteration": 1,
    "max_review_iterations": 5,
    "reviewer_comments": [],
    "status": "in_review"
  }
}
```

---

### 1.3 Döngüler Arası Geçiş Mantığı

```mermaid
stateDiagram-v2
    [*] --> InnerLoop
    
    state InnerLoop {
        [*] --> CodeGeneration
        CodeGeneration --> LintCheck
        LintCheck --> SelfFix: Hata Var
        SelfFix --> LintCheck
        LintCheck --> UnitTest: Hata Yok
        UnitTest --> SelfFix: Test Fail
        UnitTest --> Ready: Test Pass
    }
    
    InnerLoop --> OuterLoop: PR Açıldı
    InnerLoop --> EscalationReview: 3x Self-Fix Başarısız
    
    state OuterLoop {
        [*] --> CIPipeline
        CIPipeline --> ReviewerAnalysis
        ReviewerAnalysis --> PRApproved: PASS
        ReviewerAnalysis --> PRChangesRequested: FAIL
        PRChangesRequested --> InnerLoop_Fix
        InnerLoop_Fix --> CIPipeline
    }
    
    OuterLoop --> Production: Merged
    EscalationReview --> OuterLoop: Manuel Fix Sonrası
```

> [!IMPORTANT]
> **Sonsuz Döngü Koruması:** Her iki döngüde de `max_iterations` limiti olmalı. İç döngü 3, dış döngü 5 iterasyondan sonra insan müdahalesine escalate etmelidir.

---

## 2. Production-Grade Öneriler

### 2.1 🔐 Güvenlik Katmanı (Security Layer)

Mevcut mimarinizde güvenlik katmanı eksik. Production'da mutlaka eklenmeli:

```mermaid
graph LR
    A[Coder Agent Çıktısı] --> B[Security Scanner Agent]
    B --> C[SAST - Semgrep]
    B --> D[Dependency Audit - npm audit / pub audit]
    B --> E[Secret Detection - GitLeaks]
    C & D & E --> F{Güvenlik Skoru}
    F -->|Score ≥ 80| G[Reviewer'a Gönder]
    F -->|Score < 80| H[Coder'a Geri Gönder + CVE Detayları]
```

**Önerilen 4. Ajan: 🛡️ Security Agent**

| Özellik | Detay |
|---------|-------|
| **Model** | GPT-4o veya Gemini 2.5 Pro |
| **Görevleri** | OWASP Mobile Top 10 kontrolü, API key sızıntı tespiti, dependency vulnerability taraması |
| **Konumu** | İç döngü sonrası, dış döngü öncesi (gate keeper) |
| **Araçlar** | Semgrep, Snyk, GitLeaks, custom SAST kuralları |

---

### 2.2 📊 Gelişmiş Gözlemlenebilirlik (Advanced Observability)

LangSmith tek başına yeterli değil. Production-grade bir observability stack önerisi:

```
┌─────────────────────────────────────────────────┐
│                 Observability Stack              │
├────────────────┬────────────────┬───────────────┤
│   LangSmith    │   Prometheus   │   Grafana     │
│   (LLM Trace)  │   (Metrics)    │ (Dashboards)  │
├────────────────┼────────────────┼───────────────┤
│ • Token usage  │ • Loop count   │ • Real-time   │
│ • Latency      │ • Error rates  │   monitoring  │
│ • Chain steps  │ • Queue depth  │ • Alerting    │
│ • Cost per run │ • Docker stats │ • Cost graphs │
└────────────────┴────────────────┴───────────────┘
```

**Kritik Metrikler:**

| Metrik | Açıklama | Alert Eşiği |
|--------|----------|-------------|
| `agent.loop_count` | Bir görev için toplam döngü sayısı | > 8 → 🔴 Alert |
| `agent.token_usage` | Ajan başına token tüketimi | > 100K/task → ⚠️ Warning |
| `agent.cost_per_task` | Görev başına maliyet (USD) | > $5 → 🔴 Alert |
| `ci.build_time` | CI pipeline süresi | > 10 min → ⚠️ Warning |
| `review.rejection_rate` | Reviewer ret oranı | > 60% → 🔴 Alert (prompt sorunu) |
| `inner_loop.self_fix_rate` | Self-fix başarı oranı | < 40% → ⚠️ Warning |

---

### 2.3 🧩 Modüler Ajan Mimarisi (Scalable Agent Design)

Mevcut 3 ajan yerine, modüler ve ölçeklenebilir bir yapı öneriyorum:

```mermaid
graph TB
    subgraph "Orchestrator Layer"
        O[🎭 Orchestrator - LangGraph]
    end
    
    subgraph "Planning Agents"
        A1[🧠 Architect Agent]
        A2[📋 Task Planner Agent]
    end
    
    subgraph "Execution Agents"
        B1[💻 UI Coder Agent]
        B2[⚙️ Backend Coder Agent]
        B3[🗄️ Database Schema Agent]
    end
    
    subgraph "Quality Agents"
        C1[🕵️ Code Reviewer Agent]
        C2[🛡️ Security Agent]
        C3[🧪 Test Generator Agent]
    end
    
    subgraph "DevOps Agents"
        D1[🐳 Docker Manager Agent]
        D2[🚀 Deployment Agent]
    end
    
    O --> A1 & A2
    A1 & A2 --> B1 & B2 & B3
    B1 & B2 & B3 --> C1 & C2 & C3
    C1 & C2 & C3 --> D1 & D2
```

> [!TIP]
> **Coder Agent'ı 2-3 alt ajana bölmek** büyük projelerde paralelleşme sağlar. UI, iş mantığı ve veritabanı katmanları aynı anda farklı ajanlarca geliştirilebilir.

---

### 2.4 💾 State Management: Gelişmiş State Yapısı

Önerdiğiniz basit JSON state'i yerine, daha kapsamlı bir yapı:

```json
{
  "project": {
    "id": "uuid-v4",
    "name": "MyApp",
    "created_at": "2026-06-16T21:00:00Z",
    "user_prompt": "E-ticaret uygulaması istiyorum..."
  },
  "architecture": {
    "platform": "react_native",
    "language": "typescript",
    "state_management": "zustand",
    "design_pattern": "clean_architecture",
    "folder_structure": {},
    "adr_document": "markdown string..."
  },
  "modules": [
    {
      "name": "auth_module",
      "status": "approved",
      "files": [
        {
          "path": "src/features/auth/LoginScreen.tsx",
          "content_hash": "sha256:abc...",
          "inner_loop": { "lint_pass": true, "test_pass": true, "iterations": 2 },
          "outer_loop": { "pr_number": 12, "review_status": "approved", "iterations": 1 }
        }
      ]
    }
  ],
  "pipeline": {
    "current_phase": "coding",
    "current_module": "auth_module",
    "total_cost_usd": 3.42,
    "total_tokens": 287500,
    "error_log": []
  },
  "human_in_the_loop": {
    "pending_approvals": [],
    "escalations": [],
    "feedback_history": []
  }
}
```

---

### 2.5 🧪 Test Generator Agent (Yeni Özellik)

Mevcut mimaride testler elle yazılıyor veya yok. Production'da otomatik test üretimi kritik:

| Özellik | Detay |
|---------|-------|
| **Model** | Claude Sonnet 4 (kod üretiminde güçlü) |
| **Görevleri** | Unit test, widget test ve integration test üretimi |
| **Tetikleme** | Coder Agent her modülü tamamladığında |
| **Çıktı** | Test dosyaları + coverage raporu |
| **Hedef Coverage** | ≥ 70% line coverage (production threshold) |

```mermaid
sequenceDiagram
    participant C as Coder Agent
    participant T as Test Generator Agent
    participant D as Docker Runner
    participant R as Reviewer Agent
    
    C->>T: Modül kodu tamamlandı
    T->>T: Kodu analiz et + test yaz
    T->>D: Testleri çalıştır
    D->>T: Coverage: 78% ✅
    T->>R: Kod + Testler + Coverage Raporu
```

---

### 2.6 🔄 Human-in-the-Loop (HITL) Kontrol Noktaları

Tam otonom bir sistem risklidir. Kritik noktalarda insan onayı gerekir:

```mermaid
graph TD
    A[Architect Kararı] -->|🛑 HITL Gate 1| B{İnsan Onayı}
    B -->|Onay| C[Coder Başlasın]
    B -->|Revizyon| A
    
    C --> D[Kod Tamamlandı]
    D --> E[Security Scan]
    E -->|Kritik CVE Bulundu| F{🛑 HITL Gate 2}
    F -->|Risk Kabul| G[Devam]
    F -->|Düzelt| C
    
    G --> H[Reviewer Onayı]
    H -->|Production Deploy| I{🛑 HITL Gate 3}
    I -->|Deploy Onayı| J[🚀 Production]
```

**Zorunlu HITL Noktaları:**

1. **Mimari Kararlar** — Platform ve teknoloji seçimi geri dönüşü zor
2. **Kritik Güvenlik Bulguları** — CVE severity ≥ HIGH
3. **Production Deployment** — Son onay her zaman insanda olmalı
4. **Bütçe Aşımı** — Maliyet belirlenen threshold'u geçtiğinde

---

### 2.7 📦 Önerilen Ek Özellikler (Feature Backlog)

#### ✅ Öncelik 1 — MVP İçin Kritik

| # | Feature | Açıklama |
|---|---------|----------|
| 1 | **Conversation Memory** | Ajanlar arası uzun süreli bellek (Redis/ChromaDB ile). Önceki projelerdeki kararları hatırlama. |
| 2 | **Incremental Code Generation** | Tüm kodu tek seferde değil, modül modül üretme. Her modül bağımsız olarak test ve onay sürecinden geçer. |
| 3 | **Fallback Model Chain** | Claude API down ise → Gemini'ye otomatik geçiş. LiteLLM'in `fallbacks` özelliği ile. |
| 4 | **Cost Guardrails** | Proje bazında maksimum harcama limiti. Aşılırsa tüm ajanlar durdurulur. |

#### 🔶 Öncelik 2 — v2.0 İçin

| # | Feature | Açıklama |
|---|---------|----------|
| 5 | **Design Agent (Figma → Kod)** | Figma dosyasını alıp doğrudan UI koda çevirebilen ajan. (Figma MCP veya Figma API) |
| 6 | **RAG-Powered Coding** | Popüler kütüphanelerin dökümanlarını vektör DB'ye yükleyip, Coder Agent'ın güncel API'leri kullanmasını sağlama. |
| 7 | **Multi-Screen Parallelism** | Birden fazla ekranı aynı anda farklı Coder Agent instance'ları ile paralel geliştirme. |
| 8 | **Rollback Mechanism** | Hatalı deployment sonrası otomatik git revert + redeploy. |

#### 🔷 Öncelik 3 — Gelecek Vizyon

| # | Feature | Açıklama |
|---|---------|----------|
| 9 | **Self-Learning Loop** | Reviewer'ın sık yaptığı düzeltmeleri Coder Agent'ın system prompt'una otomatik ekleme (fine-tuning lite). |
| 10 | **Voice-to-App** | Whisper API ile sesli komuttan uygulama geliştirme başlatma. |
| 11 | **A/B Variant Generation** | Aynı ekranın 2-3 farklı versiyonunu üretip kullanıcıya seçtirme. |
| 12 | **Analytics Integration** | Üretilen uygulamaya otomatik Firebase Analytics / Mixpanel entegrasyonu. |

---

## 3. Önerilen Nihai Mimari (Production-Grade)

```mermaid
graph TB
    subgraph "💻 UI Katmanı (Frontend)"
        U[👤 Kullanıcı] -->|Etkileşim| FE[React / Next.js Dashboard]
        FE <-->|REST API & WebSockets| API[FastAPI Gateway]
        LGS[LangGraph Studio] <-->|Developer Graph GUI| LG[LangGraph Orchestrator]
    end
    
    subgraph "🌐 Giriş Katmanı"
        API -->|Auth + Rate Limit| Q[Redis Task Queue]
    end
    
    subgraph "🧠 Orkestrasyon Katmanı"
        Q --> LG[LangGraph Orchestrator]
        LG <-->|Model Routing| LL[LiteLLM Router SDK]
        LL <--> G[Gemini API]
        LL <--> CL[Claude API]
        LL <--> O[OpenAI API]
    end
    
    subgraph "🤖 Ajan Katmanı"
        LG --> AR[Architect Agent]
        LG --> CO[Coder Agent - UI]
        LG --> CO2[Coder Agent - Logic]
        LG --> TG[Test Generator Agent]
        LG --> SE[Security Agent]
        LG --> RE[Reviewer Agent]
        LG --> DE[Deployer Agent]
    end
    
    subgraph "🐳 Execution Katmanı"
        CO & CO2 --> DK1[Docker: Inner Loop]
        TG --> DK2[Docker: Test Runner]
        SE --> DK3[Docker: Security Scan]
    end
    
    subgraph "📦 Depolama Katmanı"
        GH[GitHub Repository]
        RD[Redis - State/Cache]
        CH[ChromaDB - RAG Memory]
        PG[PostgreSQL - Project History / Checkpoints]
    end
    
    subgraph "📊 Gözlemlenebilirlik"
        LS[LangSmith - LLM Traces]
        PR[Prometheus - Metrics]
        GR[Grafana - Dashboards]
        PD[PagerDuty - Alerts]
    end
    
    DK1 -->|Lint Pass| GH
    GH -->|CI Webhook| RE
    RE -->|Approve| DE
```

---

### 3.1 UI / Frontend Mimarisi (Kullanıcı Paneli)

UI, bu mimaride arka plan işlemlerini kontrol etmek, izlemek ve insan onay mekanizmalarını (HITL) yönetmek için bir **istemci (client)** olarak yer alır. Kod tabanında `/frontend` dizininde konumlandırılır.

#### 1. Teknoloji Seçimi
* **Core:** React 19 + TypeScript + Vite (Hızlı build ve zengin ekosistem).
* **Styling (CSS):** Vanilla CSS + CSS Variables (Gelişmiş temalar, karanlık mod ve özel mikro-animasyonlar için).
* **UI Components:** Radix UI primitives (veya Headless UI) ile erişilebilir bileşenler.
* **Grafikler & İkonlar:** Lucide React (ikonlar), Recharts (token ve maliyet grafikleri).
* **State Management:** Zustand (hafif ve performanslı istemci state'i).

#### 2. UI - Backend İletişim Kanalları
1. **REST API (HTTP):**
   * `/api/projects` (POST): Yeni proje talebi (Prompt, Platform, Tercihler).
   * `/api/projects` (GET): Mevcut projelerin listesi.
   * `/api/projects/{id}/history`: Projenin geçmiş adım ve log kayıtları.
   * `/api/hitl/{id}/approve` (POST): HITL onay kararlarının gönderilmesi (Approve/Reject/Feedback).
2. **WebSockets (Çift Yönlü Canlı İletişim):**
   * `/api/projects/{id}/stream`: LangGraph orkestratörünün anlık durumunu, aktif ajan bilgisini, maliyet güncellemelerini ve iç döngü terminal loglarını arayüze canlı olarak basar.

#### 3. Kritik UI Ekranları ve Özellikleri
* **Ajan İş Akışı Görselleştirici (Graph Viewer):** LangGraph şemasının canlı bir kopyası. Hangi düğümün (node) o an çalıştığı, hangilerinin tamamlandığı görsel olarak parlar (aktiftir).
* **HITL Etkileşim Paneli:** Onay bekleyen adımlarda (Mimari Karar ADR'si, Kritik Güvenlik Bulgu Raporu, Deploy Öncesi Kod İnceleme) arayüzde bir modal/panel açılır. Kullanıcı kod diff'lerini satır satır inceleyip feedback yazarak süreci yönlendirebilir.
* **Canlı Konsol (Live Terminal Logs):** Docker container'larındaki lint ve test çıktıları, ajanların iç sesleri (thoughts) canlı akan bir terminal arayüzünde gösterilir.
* **Maliyet ve Kaynak Monitörü:** Projenin o ana kadar harcadığı USD cinsinden toplam maliyet, harcanan toplam token ve geçen süre canlı grafiklerle izlenir.

---

## 4. Teknoloji Seçimi Karşılaştırması

### Orkestrasyon Alternatifleri

| Teknoloji | Avantaj | Dezavantaj | Öneri |
|-----------|---------|------------|-------|
| **LangGraph** | Döngüsel workflow, state management, checkpointing | Learning curve | ✅ **Birincil seçim** |
| **CrewAI** | Basit ajan tanımlama, hızlı prototipleme | Sınırlı kontrol, döngü yönetimi zayıf | ❌ Production için yetersiz |
| **AutoGen** | Microsoft desteği, multi-agent conversation | Karmaşık konfigürasyon | 🔶 Alternatif |
| **Custom (FastAPI + Celery)** | Tam kontrol, esneklik | Her şey sıfırdan yazılmalı | 🔶 İleri seviye takımlar için |

### Model Seçimi (2026 Güncel)

| Ajan | Model | Fallback | Gerekçe |
|------|-------|----------|---------|
| Architect | **Gemini 2.5 Pro** | Claude Sonnet 4 | Geniş context, üstün reasoning |
| Coder | **Claude Sonnet 4** | Gemini 2.5 Pro | Endüstri lideri kod üretimi |
| Reviewer | **GPT-4o** | Claude Opus 4 | Kusur bulma ve analitik düşünme |
| Security | **GPT-4o** | Gemini 2.5 Pro | OWASP analizi ve güvenlik mantığı |
| Test Generator | **Claude Sonnet 4** | GPT-4o | Test kodu üretiminde güçlü |

---

## 5. Teknik Araştırma Bulguları & Implementasyon Kararları

Aşağıdaki kararlar, LangGraph ve LiteLLM ekosisteminin 2025-2026 güncel araştırmasına dayanmaktadır.

### 5.1 LangGraph: StateGraph + Annotated Reducer Pattern

State alanlarında `Annotated` ile reducer fonksiyonları kullanarak, her node'un state'i güvenli şekilde güncellemesini sağlıyoruz.

```python
from typing import TypedDict, Annotated
from operator import add
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages

# Reducer pattern: her alan için birleştirme stratejisi
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # Mesajları append eder
    total_cost: Annotated[float, add]        # Maliyeti toplar
    iteration_count: Annotated[int, add]     # Sayacı artırır
    current_agent: str                       # Son yazan kazanır (reducer yok)
```

**Neden bu pattern?**
- Node'lar partial dict döndürür, state mutation yok
- `add_messages` mesaj deduplikasyonu ve sıralama sağlar
- `operator.add` sayısal alanları otomatik toplar
- Thread-safe, paralel node çalışmasına uygun

---

### 5.2 LiteLLM: Router SDK ile In-Process Fallback

Proxy sunucusu yerine, doğrudan Python SDK `Router` sınıfı kullanıyoruz. Daha basit, daha az altyapı.

```python
from litellm import Router

model_list = [
    {
        "model_name": "architect-model",
        "litellm_params": {
            "model": "gemini/gemini-2.5-pro",
            "api_key": "os.environ/GOOGLE_API_KEY",
        }
    },
    {
        "model_name": "coder-model",
        "litellm_params": {
            "model": "anthropic/claude-sonnet-4-20250514",
            "api_key": "os.environ/ANTHROPIC_API_KEY",
        }
    },
    {
        "model_name": "reviewer-model",
        "litellm_params": {
            "model": "openai/gpt-4o",
            "api_key": "os.environ/OPENAI_API_KEY",
        }
    },
]

router = Router(
    model_list=model_list,
    fallbacks=[
        {"architect-model": ["coder-model"]},   # Gemini down → Claude
        {"coder-model": ["architect-model"]},    # Claude down → Gemini
        {"reviewer-model": ["coder-model"]},     # GPT-4o down → Claude
    ],
    num_retries=2,
    timeout=30,
)

# LangGraph node'larında kullanım
def architect_node(state: AgentState) -> dict:
    response = router.completion(
        model="architect-model",
        messages=[{"role": "user", "content": state["messages"][-1].content}]
    )
    return {"messages": [response.choices[0].message]}
```

**Proxy vs SDK Router karşılaştırması:**

| Özellik | LiteLLM Proxy (Docker) | LiteLLM Router (SDK) |
|---------|----------------------|---------------------|
| Kurulum | Docker container gerekli | `pip install litellm` yeterli |
| Fallback | Config dosyası ile | Python kodu ile |
| Ek altyapı | Ayrı servis yönetimi | Sıfır — uygulama içinde çalışır |
| Performans | Network hop (latency) | In-process (hızlı) |
| **Karar** | ❌ Gereksiz karmaşıklık | ✅ **Tercih edilen** |

---

### 5.3 Hibrit State Yaklaşımı (TypedDict İç / Pydantic Dış)

"Boundary Rule" prensibi: İç state hafif (TypedDict), dış sınırlar güvenli (Pydantic).

```python
# ── İÇ STATE: TypedDict (hafif, hızlı, LangGraph uyumlu) ──
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
import operator

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    iteration_count: Annotated[int, operator.add]
    current_agent: str
    architecture_spec: dict
    source_code: dict
    review_notes: list
    security_score: float
    total_cost_usd: Annotated[float, operator.add]

# ── DIŞ SINIRLAR: Pydantic (validasyonlu, API-safe) ──
from pydantic import BaseModel, Field

class UserRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=5000)
    session_id: str
    preferences: dict = Field(default_factory=dict)

class AgentResponse(BaseModel):
    answer: str
    sources: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    cost_usd: float = Field(ge=0.0)
```

---

### 5.4 Otomatik LangSmith Trace (Zero-Config)

Ekstra kod yazmaya gerek yok. Sadece environment variable'lar yeterli:

```bash
# .env dosyası
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxxxxxx
LANGSMITH_PROJECT=multi-agent-mobile-dev
```

LangGraph otomatik olarak tüm graph çalışmalarını, LLM çağrılarını ve tool invocation'larını trace eder. Dashboard'da görünenler:
- Hierarchical span'lar (her graph step)
- LLM call latency, token usage, costs
- State transitions between nodes
- Visual graph execution traces

---

### 5.5 Supervisor Pattern: `create_react_agent` + Handoff Tools

Modern LangGraph pattern'i: Her ajan `create_react_agent` ile oluşturulur, supervisor `handoff tools` ile görev dağıtır.

```python
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent
from langgraph.types import Command

# Worker ajanlar
architect_agent = create_react_agent(
    model=router,  # LiteLLM Router
    tools=[analyze_requirements_tool],
    name="architect",
    prompt="Sen bir yazılım mimarısın..."
)

coder_agent = create_react_agent(
    model=router,
    tools=[generate_code_tool, lint_tool],
    name="coder",
    prompt="Sen bir yazılım geliştiricisisin..."
)

# Handoff tool: Supervisor → Worker yönlendirmesi
def make_handoff_tool(agent_name: str):
    def handoff(task: str) -> Command:
        return Command(goto=agent_name)
    handoff.__name__ = f"transfer_to_{agent_name}"
    return handoff

# Supervisor ajan
supervisor = create_react_agent(
    model=router,
    tools=[
        make_handoff_tool("architect"),
        make_handoff_tool("coder"),
        make_handoff_tool("reviewer"),
    ],
    name="supervisor",
    prompt="Sen orkestratörsün. Görevleri doğru ajana yönlendir."
)

# Graph assembly
builder = StateGraph(AgentState)
builder.add_node("supervisor", supervisor)
builder.add_node("architect", architect_agent)
builder.add_node("coder", coder_agent)
builder.add_edge(START, "supervisor")
builder.add_edge("architect", "supervisor")  # Worker → Supervisor'a dönüş
builder.add_edge("coder", "supervisor")

app = builder.compile(checkpointer=memory)
```

---

### 5.6 ⚠️ CVE-2025-67644: Checkpointer Güvenlik Açığı

> [!CAUTION]
> **CVE-2025-67644** — SQLite ve Redis checkpointer'larda SQL injection açığı. Kullanıcı kontrollü filtreler üzerinden sömürülebilir.
>
> **Etkilenen paketler:**
> - `langgraph-checkpoint-sqlite < 3.0.1`
> - `langgraph < 1.0.10`  
> - `langgraph-checkpoint-redis < 1.0.2`
>
> **Çözüm:**
> - Production'da **PostgreSQL checkpointer** kullanılacak
> - Minimum versiyon: `langgraph >= 1.0.10`
> - `langgraph-checkpoint-postgres >= 2.0` zorunlu

**Checkpointer Konfigürasyonu:**

```python
# Development (InMemorySaver — sadece test için)
from langgraph.checkpoint.memory import InMemorySaver
memory = InMemorySaver()

# Production (PostgreSQL — güvenli)
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

pool = ConnectionPool("postgresql://user:pass@host:5432/dbname")
memory = PostgresSaver(pool)

# Compile
app = builder.compile(checkpointer=memory)
```

---

## 6. Kritik Uyarılar ve Anti-Pattern'ler

> [!CAUTION]
> ### Kaçınılması Gereken Hatalar
> 1. **Sonsuz Döngü:** Mutlaka `max_iterations` koyun. Hem iç hem dış döngüde.
> 2. **Token Patlaması:** Büyük dosyaları tüm olarak LLM'e göndermeyin. Chunk'lara bölün veya sadece diff gönderin.
> 3. **Tek Monolitik Prompt:** Her ajanın system prompt'u ayrı dosyada olmalı, version controlled olmalı.
> 4. **State Kaybı:** LangGraph checkpointing mutlaka aktif olmalı. Sistem çökse bile kaldığı yerden devam edebilmeli.
> 5. **API Key Sızıntısı:** Ajanların ürettiği kodda `.env` dosyalarına hardcoded key yazması engellenmelidir (GitLeaks).
> 6. **⚠️ CVE-2025-67644:** SQLite/Redis checkpointer kullanmayın. Production'da mutlaka PostgreSQL checkpointer kullanın (`langgraph >= 1.0.10`).
> 7. **State Mutation:** Node'larda state'i doğrudan değiştirmeyin. Her zaman partial dict döndürün — LangGraph reducer'ları birleştirmeyi halleder.
> 8. **Recursion Limit:** LangGraph default `recursion_limit=25`. Karmaşık döngülerde bunu açıkça artırın.

> [!WARNING]
> ### Maliyet Kontrolü
> Tahmini maliyet hesabı (tek bir orta ölçekli uygulama için):
> - Architect Agent: ~5K token → ~$0.05
> - Coder Agent (5 modül × 3 iterasyon): ~150K token → ~$1.50
> - Reviewer Agent (5 modül × 2 iterasyon): ~50K token → ~$0.50
> - Test Generator: ~30K token → ~$0.30
> - **Toplam tahmini maliyet: $2-5 / proje** (basit uygulama)
> - **Karmaşık uygulama: $15-30 / proje**
>
> `guardrails.yaml` ile proje bazında maliyet limiti belirlenmeli.

# 🚀 Implementation Plan: Multi-Agent Mobil Uygulama Geliştirme Sistemi

Tüm onaylanan özellikleri (Security Agent, Test Generator, Observability, HITL, Gelişmiş State, Fallback Chain, Güncel Modeller) içeren production-grade sistemin implementasyon planı.

---

## Faz 1: Proje İskeleti & LiteLLM Konfigürasyonu

Projenin temel yapısını oluşturma ve LLM erişim altyapısını kurma.

### [NEW] pyproject.toml
- Python 3.11+ proje konfigürasyonu
- **Kritik bağımlılık versiyonları:**
  - `langgraph >= 1.0.10` (⚠️ CVE-2025-67644 düzeltmesi)
  - `langgraph-checkpoint-postgres >= 2.0` (Production checkpointer)
  - `litellm >= 1.50` (Router SDK fallback desteği)
  - `langsmith >= 0.2`, `langchain-core >= 0.3`
  - `pydantic >= 2.0` (API sınır validasyonu)
  - `fastapi`, `uvicorn`, `pygithub`, `docker`, `rich`, `prometheus-client`
  - `psycopg[pool]` (PostgreSQL connection pooling)

### [NEW] config/litellm_config.yaml
- Model tanımları: Gemini 2.5 Pro, Claude Sonnet 4, GPT-4o
- **⚡ Karar: LiteLLM Proxy yerine Router SDK kullanılacak**
  - Proxy sunucusu gerektirmez, in-process çalışır
  - `litellm.Router` sınıfı ile fallback chain tanımı
  - Ajan başına model routing: `architect-model`, `coder-model`, `reviewer-model`
- Fallback zincirleri: Gemini ↔ Claude ↔ GPT-4o
- `num_retries=2`, `timeout=30` konfigürasyonu

### [NEW] config/guardrails.yaml
- Maks. iç döngü iterasyonu: 3
- Maks. dış döngü iterasyonu: 5
- Maks. proje maliyeti: $10 (default, ayarlanabilir)
- Token limitleri (ajan başına)

### [NEW] .env.example
- `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- `GITHUB_TOKEN`, `LANGSMITH_API_KEY`
- `LANGSMITH_TRACING=true` (otomatik trace — ekstra kod gerekmez)
- `LANGSMITH_PROJECT=multi-agent-mobile-dev`
- `DATABASE_URL` (PostgreSQL — checkpointing için)
- `REDIS_URL`, `DOCKER_HOST`

### [NEW] src/\_\_init\_\_.py
### [NEW] src/integrations/litellm_client.py
- **`litellm.Router` SDK** wrapper sınıfı (proxy sunucusu KULLANILMIYOR)
- `Router(model_list=..., fallbacks=..., num_retries=2)` ile in-process fallback
- Ajan bazlı model routing (`router.completion(model="architect-model", ...)`) 
- Token kullanım tracking
- Maliyet hesaplama (model başına fiyat tablosu)

---

## Faz 2: State Yapısı & LangGraph Orchestrator

Tüm sistemin kalbi — state machine ve iş akışı.

### [NEW] src/orchestrator/state.py
- **⚡ Hibrit State Yaklaşımı (Boundary Rule):**
  - **İç state:** `TypedDict` + `Annotated` reducer pattern (hafif, hızlı, LangGraph uyumlu)
  - **Dış sınırlar:** `Pydantic BaseModel` (API validasyonu, kullanıcı girdi/çıktısı)
- Reducer'lı alanlar:
  - `messages: Annotated[list, add_messages]` — mesaj birleştirme
  - `total_cost_usd: Annotated[float, operator.add]` — maliyet toplama
  - `iteration_count: Annotated[int, operator.add]` — sayaç
- State bileşenleri: `architecture_spec`, `source_code`, `review_notes`, `security_score`
- Pydantic modeller: `UserRequest`, `AgentResponse` (API sınırları)

### [NEW] src/orchestrator/graph.py
- `StateGraph(AgentState)` tanımı (LangGraph v1.0+)
- **⚡ Supervisor Pattern:** `create_react_agent` + handoff tools
  - Her ajan `create_react_agent()` ile oluşturulur
  - Supervisor, `make_handoff_tool("agent_name")` ile görev dağıtır
  - Worker ajanlar işi bitirince supervisor'a döner
- Node'lar: `supervisor`, `architect`, `coder`, `inner_loop_check`, `security_scan`, `test_generator`, `reviewer`, `hitl_gate`, `deployer`
- Conditional edge'ler:
  - `inner_loop_check` → lint/test fail ise `coder`'a geri dönüş
  - `inner_loop_check` → 3 iterasyon aşıldıysa escalation
  - `security_scan` → kritik CVE bulunduysa HITL gate
  - `reviewer` → PASS ise deploy, FAIL ise `coder`'a geri dönüş
- **⚠️ Checkpointing (CVE-2025-67644 uyumlu):**
  - Development: `InMemorySaver` (sadece test)
  - Production: `PostgresSaver` + `psycopg_pool.ConnectionPool`
  - ~~SQLite checkpointer~~ → **KULLANILMAYACAK** (güvenlik açığı)

### [NEW] src/orchestrator/nodes.py
- Her ajan için bir node fonksiyonu
- State'i okuyan, ajanı çağıran ve **partial dict döndüren** wrapper'lar
- Node'lar state'i doğrudan mutate ETMEYecek — reducer'lar birleştirmeyi halleder

### [NEW] src/orchestrator/edges.py
- `should_continue_inner_loop()` — iterasyon ve sonuç kontrolü
- `should_escalate()` — maks. iterasyon aşımı kontrolü
- `review_decision()` — approve/reject routing
- `security_gate()` — CVE severity kontrolü
- `cost_check()` — bütçe aşımı kontrolü

---

## Faz 3: Architect Agent

Kullanıcı fikrinden mimari kararlar üreten ajan.

### [NEW] config/prompts/architect_system.md
- Sistem promptu: Platform seçimi, mimari desen, state management, klasör yapısı
- Çıktı formatı: Yapılandırılmış JSON (ADR belgesi)

### [NEW] src/agents/architect/agent.py
- `ArchitectAgent` sınıfı
- Primary model: **Gemini 2.5 Pro**, Fallback: Claude Sonnet 4
- `analyze_requirements()` — kullanıcı promptunu parse etme
- `generate_adr()` — Mimari Karar Belgesi (Architecture Decision Record) üretimi
- `select_tech_stack()` — Platform, dil, framework seçimi

### [NEW] src/agents/architect/schemas.py
- Pydantic output şemaları: `ArchitectureDecision`, `FolderStructure`, `TechStack`

---

## Faz 4: Coder Agent & İç Döngü

Mimari kurallara göre kod üreten ajan + lokal self-fix mekanizması.

### [NEW] config/prompts/coder_system.md
- Sistem promptu: Architect'in ADR'sine uygun kod üretimi
- Çıktı formatı: Dosya yolu + içerik çiftleri

### [NEW] src/agents/coder/agent.py
- `CoderAgent` sınıfı
- Primary model: **Claude Sonnet 4**, Fallback: Gemini 2.5 Pro
- `generate_module()` — Tek bir modülün kodunu üretme
- `self_fix()` — Lint/test hatalarını okuyup düzeltme
- Modül bazlı incremental üretim

### [NEW] src/agents/coder/inner_loop.py
- `InnerLoopRunner` sınıfı
- Docker container'da lint çalıştırma (ESLint/Dart Analyzer/SwiftLint)
- Unit test çalıştırma
- Maks. 3 iterasyon self-fix döngüsü
- Sonuç raporlama (state güncelleme)

### [NEW] src/integrations/docker_runner.py
- Docker API wrapper
- Container oluşturma, kod kopyalama, komut çalıştırma, log toplama
- Platforma göre doğru Docker image seçimi

---

## Faz 5: Security Agent & Test Generator Agent

### [NEW] config/prompts/security_system.md
- OWASP Mobile Top 10 kontrol listesi
- Güvenlik analiz formatı

### [NEW] src/agents/security/agent.py
- `SecurityAgent` sınıfı
- Primary model: **GPT-4o**, Fallback: Gemini 2.5 Pro
- `scan_code()` — SAST analizi (Semgrep kuralları ile)
- `audit_dependencies()` — npm audit / pub audit sonuçlarını analiz
- `detect_secrets()` — GitLeaks entegrasyonu, hardcoded API key tespiti
- Güvenlik skoru hesaplama (0-100)
- Kritik CVE bulunursa → HITL gate tetikleme

### [NEW] src/agents/security/owasp_rules.py
- OWASP Mobile Top 10 kural tanımları
- Her kural için açıklama ve severity

### [NEW] config/prompts/test_generator_system.md
- Test üretim kuralları, coverage hedefi ≥ 70%

### [NEW] src/agents/test_generator/agent.py
- `TestGeneratorAgent` sınıfı
- Primary model: **Claude Sonnet 4**, Fallback: GPT-4o
- `generate_unit_tests()` — Fonksiyon bazlı unit test üretimi
- `generate_widget_tests()` — UI bileşen testleri (Flutter/RN)
- `generate_integration_tests()` — Modüller arası entegrasyon testleri
- Coverage analizi ve rapor

---

## Faz 6: Reviewer Agent & GitHub Entegrasyonu

### [NEW] config/prompts/reviewer_system.md
- Code review kuralları: SOLID, Clean Code, güvenlik, performans
- Yapılandırılmış feedback formatı

### [NEW] src/agents/reviewer/agent.py
- `ReviewerAgent` sınıfı
- Primary model: **GPT-4o**, Fallback: Claude Opus 4
- `review_code()` — Kod kalite analizi
- `analyze_ci_logs()` — GitHub Actions loglarını parse etme
- `create_pr_review()` — GitHub PR'a approve/request_changes + inline comments
- Karar: `PASS` → deploy'a yönlendir, `FAIL` → feedback + Coder'a geri gönder

### [NEW] src/integrations/github_client.py
- PyGithub wrapper
- `create_branch()`, `commit_files()`, `create_pull_request()`
- `get_ci_logs()` — Actions API'den build/test logları
- `submit_review()` — PR review + inline comments
- `auto_merge()` — Tüm check'ler geçince otomatik merge

---

## Faz 7: Observability, HITL & Guardrails

### [NEW] src/observability/langsmith_tracer.py
- LangSmith callback handler
- Her ajan çağrısını trace etme (token, latency, cost)
- Hata durumlarını loglama

### [NEW] src/observability/metrics.py
- Prometheus metrikleri:
  - `agent_loop_count` (Counter)
  - `agent_token_usage` (Histogram)
  - `agent_cost_per_task` (Gauge)
  - `ci_build_duration_seconds` (Histogram)
  - `review_rejection_total` (Counter)
- Metrik endpoint: `/metrics`

### [NEW] monitoring/prometheus.yml
- Prometheus scrape konfigürasyonu

### [NEW] monitoring/grafana/dashboards/agents.json
- Grafana dashboard: Ajan performansı, maliyet, döngü sayısı, hata oranları

### [NEW] src/orchestrator/hitl.py
- `HITLGate` sınıfı
- 3 kontrol noktası:
  1. **Mimari onay** — Architect kararları sonrası
  2. **Güvenlik escalation** — CVE severity ≥ HIGH
  3. **Deploy onayı** — Production öncesi
- Bekleme mekanizması (webhook veya polling)
- Timeout sonrası otomatik escalation

### [NEW] src/orchestrator/guardrails.py
- Maliyet kontrolü: Threshold aşımında tüm ajanları durdurma
- Token limiti: Ajan başına maksimum token kullanımı
- Iterasyon limiti: Sonsuz döngü koruması
- `guardrails.yaml` dosyasını okuyarak konfigürasyon

---

### [NEW] src/api/main.py
- FastAPI entry point
- `/api/projects` — Yeni proje oluşturma (kullanıcı promptu alma)
- `/api/projects/{id}/status` — Proje durumu sorgulama
- `/api/hitl/{id}/approve` — HITL onay endpoint'i
- WebSocket: Real-time ilerleme güncellemeleri

### [NEW] docker-compose.yml
- Services: `app` (FastAPI), `frontend` (React Dashboard), `redis`, `prometheus`, `grafana`
- Volumes ve network konfigürasyonu

### [NEW] README.md
- Kurulum talimatları, API kullanımı, mimari açıklama

---

## Faz 8: Web Dashboard (UI Layer)

Sistemin kullanıcı arayüzü ve insan-onay (HITL) kontrol mekanizması.

### [NEW] frontend/package.json & frontend/vite.config.ts
- Vite + React 19 + TypeScript konfigürasyonu.

### [NEW] frontend/index.html & frontend/src/index.css
- Global CSS, modern karanlık tema CSS değişkenleri, premium yazı tipleri (Inter, Outfit).

### [NEW] frontend/src/hooks/useWebSocket.ts
- FastAPI WebSocket endpoint'ine bağlanarak canlı state güncellemelerini, maliyet ve terminal loglarını dinleyen custom hook.

### [NEW] frontend/src/components/AgentGraph.tsx
- LangGraph durumunu görselleştiren dinamik akış bileşeni. Çalışan ajanı yeşil/parlak renkle gösterir.

### [NEW] frontend/src/components/HITLPanel.tsx
- İnsan onay adımları tetiklendiğinde (Architect ADR, Security High Severity CVE, Deploy) açılan ve kararı (`approve`/`reject` + feedback) API'ye post eden form arayüzü.

### [NEW] frontend/src/components/TerminalLogs.tsx
- Docker container çıktılarını ve ajanların düşünce loglarını (inner voice) renkli ve kaydırılabilir bir terminal formatında gösteren bileşen.

### [NEW] frontend/src/components/MetricCards.tsx
- Toplam maliyet (USD), token tüketimi, geçen süre ve aktif ajan sayısı gibi metrikleri Recharts grafikleriyle görselleştiren kartlar.

### [NEW] frontend/src/App.tsx
- Dashboard layout'u, proje başlatma formu ve detay pencerelerinin yönetimi.

---

## Doğrulama Planı

### Otomatik Testler
```bash
# Unit testler
pytest tests/ -v

# Orchestrator akış testi (mock LLM ile)
pytest tests/test_e2e_workflow.py -v

# Type checking
mypy src/ --strict

# Frontend Type Checking & Linter
cd frontend && npm run build
```

### Manuel Doğrulama
- Basit bir kullanıcı promptu ile uçtan uca akışı test etme (örn: "Basit bir todo uygulaması yap")
- HITL gate'lerin doğru çalıştığını frontend üzerinden doğrulama (ADR onayı, güvenlik riski onayı)
- Fallback chain'in tetiklendiğini doğrulama (mock API failure)
- Grafana dashboard'ların metrik gösterdiğini doğrulama
- UI'daki grafik ve log akışının real-time olduğunu doğrulama

---

> [!IMPORTANT]
> **Toplam Dosya Sayısı:** ~43 dosya (35 Backend/Config + 8 Frontend)
> **Tahmini Süre:** ~50 gün (Tüm fazlar sıralı olarak kodlanacaktır)
